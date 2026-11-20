"""
Регресійні тести посилення даних і анонімності за аудитом backend (docs/V2_HARDENING_CONTRACT.md).
Номери D1–D13 — з плану виправлень потоку «дані, анонімність, міграція, стійкість API».
Усі дані синтетичні.
"""
import hashlib
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app import seed, settings
from app.database import SessionLocal, engine
from app.main import app
from app.migrations import SCHEMA_VERSION, check_schema, migrate
from app.models import AccessToken, AuditEvent, InstanceMeta, Question, ResponseSet, hash_access_code
from app.routes.analytics import demo_enabled
from app.v2_auth import find_user_id
from app.v2_catalog import PERSONAL_ASSESSMENTS, is_open
from v2_helpers import login, make_user

client = TestClient(app)
ADMIN = {"X-Role": "admin"}
DATA_OFFICER = {"X-Role": "data_officer"}
MANAGER = {"X-Role": "manager"}
UNITS = ["Факультет 1", "Факультет 2", "Кафедра загальних дисциплін"]


def answers(value=3):
    with SessionLocal() as db:
        return [{"question_id": q.id, "value": value} for q in db.query(Question).filter_by(kind="survey")]


def new_cycle(categories=("cadets",), k=5, activate=True, description="Синтетичний опис") -> int:
    response = client.post("/api/assessments", headers=ADMIN, json={
        "name": "Синтетичний D", "description": description, "start_date": date.today().isoformat(),
        "categories": list(categories), "min_group_size": k, "questionnaire_version": "demo-v1"})
    assert response.status_code == 201, response.text
    cycle_id = response.json()["id"]
    if activate:
        assert client.post(f"/api/assessments/{cycle_id}/activate", headers=ADMIN).status_code == 200
    return cycle_id


def issue(cycle_id, count, category="cadets") -> list[str]:
    response = client.post(f"/api/assessments/{cycle_id}/tokens", headers=DATA_OFFICER,
                           params={"count": count, "category": category})
    assert response.status_code == 201, response.text
    return response.json()["tokens"]


def submit(cycle_id, code, category="cadets", unit=UNITS[0], value=3):
    return client.post(f"/api/assessments/{cycle_id}/submissions", json={
        "token": code, "respondent_category": category, "unit": unit,
        "questionnaire_version": "demo-v1", "answers": answers(value)})


# --- D1 (переглянуто рішенням власника): коди видають admin і data_officer; ризик n−1 для admin прийнято,
# залишковий захист — журнал tokens.issue з роллю й actor_user_id і поріг k --------------------------------

def test_admin_and_data_officer_issue_codes_and_every_issue_is_journaled():
    cycle_id = new_cycle()
    path = f"/api/assessments/{cycle_id}/tokens?count=4&category=cadets"
    assert client.post(path, headers=MANAGER).status_code == 403
    admin, csrf = login(make_user("admin"))                                # справжня сесія admin з 2FA і CSRF
    assert admin.post(path, headers=csrf).status_code == 201
    assert client.post(path, headers=DATA_OFFICER).status_code == 201
    with SessionLocal() as db:
        events = db.query(AuditEvent).filter_by(assessment_id=cycle_id, action="tokens.issue").order_by(AuditEvent.id).all()
        assert [event.actor_role for event in events] == ["admin", "data_officer"]
        assert events[0].actor_user_id is not None and events[0].details == '{"count": 4}'


def test_participation_for_admin_and_data_officer_but_results_not_for_data_officer():
    for headers, status in ((ADMIN, 200), (DATA_OFFICER, 200), (MANAGER, 403), ({"X-Role": "auditor"}, 403)):
        assert client.get("/api/assessments/1/participation", headers=headers).status_code == status
    assert client.get("/api/assessments/1/results", headers=DATA_OFFICER).status_code == 403
    assert client.get("/api/audit-events", headers=DATA_OFFICER).status_code == 403


# --- D3: seed --------------------------------------------------------------------

@pytest.fixture
def seed_db(tmp_path, monkeypatch):
    path = tmp_path / "seed" / "integrity.db"
    path.parent.mkdir()
    tmp_engine = create_engine(f"sqlite:///{path}")
    monkeypatch.setattr(seed, "engine", tmp_engine)
    monkeypatch.setattr(seed, "SessionLocal", sessionmaker(bind=tmp_engine))
    yield path, tmp_engine
    tmp_engine.dispose()


def test_seed_refuses_in_release(seed_db, monkeypatch):
    path, _ = seed_db
    monkeypatch.setenv("APP_ENV", "release")
    with pytest.raises(seed.SeedRefused, match="release"):
        seed.run(reset=True)
    assert not path.exists() or path.stat().st_size == 0


def test_seed_cli_refuses_in_release(tmp_path):
    target = tmp_path / "cli.db"
    env = {**os.environ, "APP_ENV": "release", "INTEGRITY_DB": str(target), "V2_AUTH_DB": str(tmp_path / "a.db")}
    result = subprocess.run([sys.executable, "-m", "app.seed", "--reset"], cwd=Path(__file__).resolve().parents[1],
                            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert result.returncode == 2
    assert not target.exists() or target.stat().st_size == 0


def test_seed_reset_does_not_wipe_database_of_newer_schema(seed_db):
    path, tmp_engine = seed_db
    assert seed.run(reset=False) is True
    with closing(sqlite3.connect(path)) as con:
        con.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        con.commit()
    tmp_engine.dispose()
    before = path.read_bytes()
    with pytest.raises(seed.SeedRefused, match="новіша"):
        seed.run(reset=True)
    tmp_engine.dispose()
    assert path.read_bytes() == before
    assert sorted(p.name for p in path.parent.iterdir()) == ["integrity.db"]   # і без резервних копій


def test_seed_reset_makes_verified_backup_before_wiping(seed_db):
    path, tmp_engine = seed_db
    assert seed.run(reset=False) is True
    with closing(sqlite3.connect(path)) as con:
        con.execute("INSERT INTO units (name) VALUES ('Синтетичний маркер до reset')")
        con.commit()
        counts = {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                  for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert seed.run(reset=True) is True
    [backup] = list(path.parent.glob("integrity.backup-*.db"))
    with closing(sqlite3.connect(backup)) as con:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in counts} == counts
        assert con.execute("SELECT 1 FROM units WHERE name='Синтетичний маркер до reset'").fetchone()
    with closing(sqlite3.connect(path)) as con:
        assert not con.execute("SELECT 1 FROM units WHERE name='Синтетичний маркер до reset'").fetchone()
        assert con.execute("SELECT value FROM instance_meta WHERE key='dataset'").fetchone() == ("synthetic",)


# --- D4: приховані клітинки не перелічуються ------------------------------------

def test_hidden_cells_are_not_enumerated_anywhere():
    """Сценарій аудиту: єдиний керівник у підрозділі не «підтверджується» назвою прихованої клітинки."""
    cycle_id = new_cycle(categories=("mgmt", "npp", "cadets"))
    for category, unit, n in (("mgmt", UNITS[2], 1), ("npp", UNITS[0], 6), ("npp", UNITS[1], 6),
                              ("cadets", UNITS[0], 6)):
        for code in issue(cycle_id, n, category):
            assert submit(cycle_id, code, category, unit).status_code == 201
    assert client.post(f"/api/assessments/{cycle_id}/close", headers=ADMIN).status_code == 200
    base = f"/api/assessments/{cycle_id}"
    participation = client.get(base + "/participation", headers=DATA_OFFICER).json()
    by_unit = client.get(base + "/participation?by_unit=true", headers=ADMIN).json()
    results = client.get(base + "/results", headers=ADMIN).json()

    for data in (participation, by_unit, results):
        assert "mgmt" not in str(data) and UNITS[2] not in str(data)
        assert data["suppressed"] is True
    assert participation["groups"] == [{"category": "npp", "responses": 12, "hidden": False}]
    assert by_unit["groups"] == [{"category": "npp", "unit": UNITS[0], "responses": 6, "hidden": False},
                                 {"category": "npp", "unit": UNITS[1], "responses": 6, "hidden": False}]
    assert [c["category"] for c in results["categories"]] == ["npp"]
    # «підсумок − видимі» = сума всіх прихованих (cadets 6 + mgmt 1), а не одна мала група
    assert participation["responses_total"] - 12 == 7 >= 5
    assert results["responses_total"] == 19


# --- D5: у БД лише хеші кодів ---------------------------------------------------------

def test_codes_are_stored_only_as_sha256():
    cycle_id = new_cycle()
    codes = issue(cycle_id, 3)
    with closing(sqlite3.connect(engine.url.database)) as con:
        columns = [r[1] for r in con.execute("PRAGMA table_info(access_tokens)")]
        rows = con.execute("SELECT * FROM access_tokens WHERE cycle_id = ?", (cycle_id,)).fetchall()
    assert columns == ["id", "cycle_id", "token_hash", "used"]
    assert sorted(r[2] for r in rows) == sorted(hashlib.sha256(c.encode()).hexdigest() for c in codes)
    assert not any(code in str(rows) for code in codes)


def test_wrong_and_used_codes_get_identical_answer():
    cycle_id = new_cycle()
    [code] = issue(cycle_id, 1)
    assert submit(cycle_id, code).status_code == 201
    used = submit(cycle_id, code)
    wrong = submit(cycle_id, "0" * 32)
    assert used.status_code == wrong.status_code == 403
    assert used.json() == wrong.json() == {"detail": "Недійсний або вже використаний код доступу"}


# --- D6: параметри SQL не потрапляють у тексти помилок ------------------------------

def test_engine_hides_sql_parameters_in_errors():
    assert engine.hide_parameters is True
    secret_hash = hash_access_code("synthetic-hidden-parameter")
    cycle_id = new_cycle()
    with SessionLocal() as db:
        db.add(AccessToken(cycle_id=cycle_id, token_hash=secret_hash, used=False))
        db.commit()
        db.add(AccessToken(cycle_id=cycle_id, token_hash=secret_hash, used=False))
        with pytest.raises(IntegrityError) as error:
            db.commit()
        db.rollback()
    assert secret_hash not in str(error.value)
    assert "hide_parameters" in str(error.value)


# --- D7: участь у відкритому циклі не дає точного часу подань ---------------------------

def test_open_cycle_counts_are_rounded_and_only_shown_from_k():
    cycle_id = new_cycle()
    codes = issue(cycle_id, 12)
    path = f"/api/assessments/{cycle_id}/participation"
    seen = []
    for n, code in enumerate(codes, start=1):
        assert submit(cycle_id, code).status_code == 201
        for by_unit in (False, True):
            data = client.get(path, params={"by_unit": by_unit}, headers=DATA_OFFICER).json()
            assert data["counts_exact"] is False and data["groups"] is None
            assert data["tokens_issued"] == 12
            expected_total = n - n % 5 if n >= 5 else None
            assert data["responses_total"] == expected_total
            unused = 12 - n
            assert data["tokens_unused"] == (unused - unused % 5 if n >= 5 and unused >= 5 else None)
            assert data["participation_percent"] == (round(100 * expected_total / 12, 1) if expected_total else None)
        seen.append(data["responses_total"])
    # значення змінюється не після кожного подання, а лише на межах кратних 5
    assert seen == [None] * 4 + [5] * 5 + [10] * 3
    assert client.post(f"/api/assessments/{cycle_id}/close", headers=ADMIN).status_code == 200
    closed = client.get(path, headers=ADMIN).json()
    assert closed["counts_exact"] is True and closed["responses_total"] == 12 and closed["tokens_unused"] == 0


# --- D9: чернетки не публічні ---------------------------------------------------------

def test_drafts_are_hidden_from_anonymous_and_user():
    draft_id = new_cycle(activate=False, description="Внутрішня нотатка планування")
    anon = TestClient(app)
    assert draft_id not in [a["id"] for a in anon.get("/api/assessments").json()]
    assert "Внутрішня нотатка" not in anon.get("/api/assessments").text
    for path in (f"/api/assessments/{draft_id}", f"/api/assessments/{draft_id}/questionnaires"):
        assert anon.get(path).status_code == 404
    assert anon.post(f"/api/assessments/{draft_id}/submissions", json={
        "token": "x", "respondent_category": "cadets", "unit": UNITS[0], "answers": answers()}).status_code == 404
    user, _ = login(make_user())
    assert draft_id not in [a["id"] for a in user.get("/api/assessments").json()]
    assert user.get(f"/api/assessments/{draft_id}").status_code == 404
    # admin бачить чернетки (демо-роль і справжня сесія)
    assert draft_id in [a["id"] for a in client.get("/api/assessments", headers=ADMIN).json()]
    admin, _ = login(make_user("admin"))
    assert admin.get(f"/api/assessments/{draft_id}").json()["status"] == "draft"
    assert draft_id in [a["id"] for a in admin.get("/api/assessments").json()]


# --- D10: check_schema не створює файл і звіряє колонки ----------------------------------

def test_check_schema_does_not_create_missing_file(tmp_path):
    missing = tmp_path / "missing.db"
    tmp_engine = create_engine(f"sqlite:///{missing}")
    with pytest.raises(RuntimeError, match="не знайдено"):
        check_schema(tmp_engine)
    tmp_engine.dispose()
    assert not missing.exists()


def test_check_schema_compares_columns_with_models(tmp_path):
    target = tmp_path / "altered.db"
    with closing(sqlite3.connect(engine.url.database)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
    tmp_engine = create_engine(f"sqlite:///{target}")
    check_schema(tmp_engine)                                               # копія поточної БД — придатна
    with closing(sqlite3.connect(target)) as con:
        con.execute("DROP TABLE cycle_configs")
        con.execute("CREATE TABLE cycle_configs (cycle_id INTEGER PRIMARY KEY)")
        con.commit()
    with pytest.raises(RuntimeError, match="cycle_configs: бракує колонок"):
        check_schema(tmp_engine)
    tmp_engine.dispose()


# --- D11: журнал фіксує id користувача сесії -----------------------------------------

def test_audit_records_actor_user_id_for_session_and_null_for_demo_header():
    email = make_user("admin")
    admin, csrf = login(email)
    created = admin.post("/api/assessments", headers=csrf, json={
        "name": "Синтетичний журнал", "start_date": date.today().isoformat(), "categories": ["cadets"],
        "min_group_size": 5, "questionnaire_version": "demo-v1"})
    assert created.status_code == 201
    cycle_id = created.json()["id"]
    [event] = admin.get("/api/audit-events", params={"assessment_id": cycle_id}).json()
    assert event["action"] == "assessment.create" and event["actor_role"] == "admin"
    assert event["actor_user_id"] == find_user_id(email)
    assert "@" not in str(event)
    client.post(f"/api/assessments/{cycle_id}/activate", headers=ADMIN)
    newest = client.get("/api/audit-events", params={"assessment_id": cycle_id}, headers=ADMIN).json()[0]
    assert newest["action"] == "assessment.activate" and newest["actor_user_id"] is None


def test_record_refuses_invalid_actor_user_id():
    from app import audit
    with SessionLocal() as db:
        for bad in (0, -1, "7", True):
            with pytest.raises(ValueError):
                audit.record(db, "admin", "assessment.close", None, actor_user_id=bad)
        db.rollback()


# --- D12: демо-аналітика в release лише на синтетичній БД -------------------------------

def test_analytics_demo_in_release_requires_synthetic_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("INTEGRITY_ANALYTICS_DEMO", "1")
    target = tmp_path / "marker.db"
    tmp_engine = create_engine(f"sqlite:///{target}")
    migrate(tmp_engine)
    Session = sessionmaker(bind=tmp_engine)
    with Session() as db:
        demo_enabled(db)                                                   # development: лише прапорець
        monkeypatch.setattr(settings, "is_release", lambda: True)
        with pytest.raises(HTTPException) as error:
            demo_enabled(db)
        assert error.value.status_code == 503
        db.add(InstanceMeta(key="dataset", value="production"))
        db.commit()
        with pytest.raises(HTTPException):
            demo_enabled(db)
        db.execute(text("UPDATE instance_meta SET value='synthetic' WHERE key='dataset'"))
        db.commit()
        demo_enabled(db)                                                   # прапорець + позначка
        monkeypatch.delenv("INTEGRITY_ANALYTICS_DEMO")
        with pytest.raises(HTTPException):
            demo_enabled(db)
    tmp_engine.dispose()


def test_seeded_database_is_marked_synthetic():
    with SessionLocal() as db:
        assert db.get(InstanceMeta, "dataset").value == "synthetic"


# --- D13: V2_CATALOG_NOW без часового поясу ------------------------------------------

def test_naive_catalog_now_is_treated_as_utc(monkeypatch):
    monkeypatch.setenv("V2_CATALOG_NOW", "2026-11-18T12:00:00")
    assert is_open(PERSONAL_ASSESSMENTS[0]) is True
    assert is_open(PERSONAL_ASSESSMENTS[1]) is False
    assert is_open(PERSONAL_ASSESSMENTS[0], now=datetime(2026, 11, 25, 0, 0)) is False
    user, _ = login(make_user())
    assert user.get("/v2/user/assessments").status_code == 200
