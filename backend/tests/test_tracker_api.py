"""
Recommendations Tracker API: рішення посадової особи, відповідальний, строк, статуси, Audit Trail.

Більшість перевірок — у демо-режимі X-Role (як test_scoring.py); CSRF перевіряється на справжній
сесії V2 з 2FA (v2_helpers.login). Пропозиції формує синтетична методика
(INTEGRITY_ANALYTICS_DEMO=1) для закритих seed-циклів: 1 (2025-II) і 2 (2026-I); цикл 3 відкритий.
Кожен тест починає і завершує роботу з порожньою таблицею recommendation_actions.
"""
import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from app.database import SessionLocal, engine
from app.main import app
from app.migrations import SCHEMA_VERSION, migrate
from app.models import AuditEvent, RecommendationAction
from app.routes.tracker import _clean_owner

from v2_helpers import login, make_user

client = TestClient(app)
ADMIN = {"X-Role": "admin"}
PARAMS = {"methodology": "team-results-demo-0.1"}
FIRST, LATER, OPEN = 1, 2, 3
_audit_start = {"id": 0}            # журнал не очищаємо: рахуємо лише записи, додані цим тестом


def _clear() -> None:
    with SessionLocal() as db:
        db.query(RecommendationAction).delete()
        db.commit()


@pytest.fixture(autouse=True)
def demo(monkeypatch):
    monkeypatch.setenv("INTEGRITY_ANALYTICS_DEMO", "1")
    _clear()
    with SessionLocal() as db:
        last = db.query(AuditEvent).order_by(AuditEvent.id.desc()).first()
        _audit_start["id"] = last.id if last else 0
    yield
    _clear()


def proposals(assessment_id: int = FIRST) -> list[dict]:
    response = client.get(f"/api/assessments/{assessment_id}/recommendations", params=PARAMS, headers=ADMIN)
    assert response.status_code == 200
    items = response.json()["proposals"]
    assert len(items) >= 2, "seed-цикл має давати щонайменше дві пропозиції"
    return items


def future(days: int = 30) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def accept_body(proposal: dict, **overrides) -> dict:
    return {"recommendation_id": proposal["id"], "decision": "accepted", "owner": "Навчальний відділ",
            "due_date": future(), "reason": "Погоджено на нараді з доброчесності", **overrides}


def decide(body: dict, assessment_id: int = FIRST, headers: dict = ADMIN):
    return client.post(f"/api/assessments/{assessment_id}/tracker/decisions", json=body, headers=headers)


def move(action_id: int, headers: dict = ADMIN, **body):
    return client.post(f"/api/tracker/{action_id}/transition", json=body, headers=headers)


def tracker(assessment_id: int = FIRST, headers: dict = ADMIN):
    return client.get(f"/api/assessments/{assessment_id}/tracker", headers=headers)


def tracker_events(assessment_id: int) -> list[tuple[str, str, str]]:
    """Записи журналу трекера для циклу, додані в поточному тесті: (дія, роль, details)."""
    with SessionLocal() as db:
        rows = (db.query(AuditEvent).filter(AuditEvent.id > _audit_start["id"],
                                            AuditEvent.assessment_id == assessment_id,
                                            AuditEvent.action.like("tracker.%"))
                .order_by(AuditEvent.id).all())
        return [(row.action, row.actor_role, row.details) for row in rows]


def accepted_action(proposal: dict, assessment_id: int = FIRST) -> int:
    response = decide(accept_body(proposal), assessment_id)
    assert response.status_code == 201, response.text
    return response.json()["id"]


# --- Доступ: вхід, ролі, CSRF ---------------------------------------------------------------

def test_tracker_requires_login_and_admin_for_changes():
    body = accept_body(proposals()[0])
    assert tracker(headers={}).status_code == 401
    assert decide(body, headers={}).status_code == 401
    assert move(1, headers={}, status="in_progress", reason="x").status_code == 401
    assert tracker(headers={"X-Role": "respondent"}).status_code == 403
    manager = {"X-Role": "manager"}
    assert tracker(headers=manager).status_code == 200                 # читати можуть аналітичні ролі
    assert decide(body, headers=manager).status_code == 403            # змінювати — лише admin
    assert move(1, headers=manager, status="in_progress", reason="x").status_code == 403
    assert tracker().json()["actions"] == []


def test_session_changes_require_csrf_token():
    proposal = proposals()[0]
    admin, csrf = login(make_user("admin"))
    path = f"/api/assessments/{FIRST}/tracker/decisions"
    refused = admin.post(path, json=accept_body(proposal))
    assert refused.status_code == 403 and "CSRF" in refused.json()["detail"]
    assert admin.post(path, json=accept_body(proposal), headers={"X-CSRF-Token": "wrong"}).status_code == 403
    created = admin.post(path, json=accept_body(proposal), headers=csrf)
    assert created.status_code == 201
    action_id = created.json()["id"]
    refused = admin.post(f"/api/tracker/{action_id}/transition", json={"status": "in_progress", "reason": "Почато"})
    assert refused.status_code == 403 and "CSRF" in refused.json()["detail"]
    moved = admin.post(f"/api/tracker/{action_id}/transition", json={"status": "in_progress", "reason": "Почато"},
                       headers=csrf)
    assert moved.status_code == 200 and moved.json()["status"] == "in_progress"
    assert admin.get(f"/api/assessments/{FIRST}/tracker").json()["actions"][0]["status"] == "in_progress"

    user, user_csrf = login(make_user("user"))
    assert user.get(f"/api/assessments/{FIRST}/tracker").status_code == 403
    assert user.post(path, json=accept_body(proposals()[1]), headers=user_csrf).status_code == 403


def test_decisions_need_analytics_demo_flag_but_reading_does_not(monkeypatch):
    proposal = proposals()[0]
    monkeypatch.delenv("INTEGRITY_ANALYTICS_DEMO")
    assert decide(accept_body(proposal)).status_code == 503
    assert tracker().status_code == 200


# --- Рішення: прийняти / відхилити ---------------------------------------------------------

def test_unknown_recommendation_or_cycle_is_404_and_open_cycle_409():
    proposal = proposals()[0]
    assert decide(accept_body(proposal, recommendation_id="0" * 24)).status_code == 404
    other_cycle = proposals(LATER)[0]                     # id з іншого циклу тут невідомий
    assert decide(accept_body(other_cycle)).status_code == 404
    assert decide(accept_body(proposal), assessment_id=999999).status_code == 404
    assert decide(accept_body(proposal), assessment_id=OPEN).status_code == 409
    assert tracker(999999).status_code == 404
    assert tracker_events(FIRST) == []


def test_duplicate_decision_is_409_and_text_comes_from_server():
    proposal = proposals()[0]
    response = decide(accept_body(proposal))
    assert response.status_code == 201
    action = response.json()
    assert action["text"] == proposal["text"] and action["rule_id"] == proposal["rule_id"]
    assert action["component_code"] == proposal["component_code"]
    assert action["status"] == "accepted" and action["allowed_transitions"] == ["in_progress"]
    assert action["owner"] == "Навчальний відділ" and action["overdue"] is False
    assert action["history"][0] | {"at": None} == {
        "from_status": "proposed", "to_status": "accepted", "on_date": date.today().isoformat(), "at": None,
        "actor_role": "admin", "reason": "Погоджено на нараді з доброчесності", "evidence_refs": [],
        "owner": "Навчальний відділ", "due_date": action["due_date"]}
    assert decide(accept_body(proposal)).status_code == 409
    assert decide({"recommendation_id": proposal["id"], "decision": "rejected", "reason": "Інше"}).status_code == 409
    # Пропозиції лишаються детермінованими: рішення їх не змінює
    assert [p["id"] for p in proposals()] == [p["id"] for p in proposals()]
    assert proposal["id"] in {p["id"] for p in proposals()}
    # Клієнт не може підмінити текст пропозиції
    other = proposals()[1]
    assert decide(accept_body(other, text="Підмінений текст")).status_code == 422
    assert decide(accept_body(other, status="verified")).status_code == 422


@pytest.mark.parametrize("change", [
    {"owner": None}, {"due_date": None}, {"owner": "  "}, {"owner": "аб"}, {"owner": "в" * 121},
    {"owner": "Іваненко Іван Іванович"}, {"owner": "І. І. Іваненко"}, {"owner": "owner@example.test"},
    {"owner": "+380 50 123 45 67"},
    {"due_date": (date.today() - timedelta(days=1)).isoformat()}, {"due_date": "2026-02-30"},
    {"due_date": "20.12.2026"}, {"due_date": future(6 * 366)},
    {"reason": ""}, {"reason": "   "}, {"reason": "x" * 1001},
    {"decision": "verified"}, {"recommendation_id": "НЕ-ХЕШ"},
])
def test_invalid_decision_is_422_and_not_stored(change):
    proposal = proposals()[0]
    response = decide(accept_body(proposal, **change))
    assert response.status_code == 422, response.text
    assert tracker().json()["actions"] == []
    assert tracker_events(FIRST) == []


@pytest.mark.parametrize("owner", ["Головна інспекція", "Заступник начальника з навчальної роботи",
                                   "Відділ 2", "Уповноважений з антикорупції", "Кафедра №3"])
def test_positions_and_units_are_valid_owners(owner):
    assert _clean_owner(f"  {owner}  ") == owner


def test_due_date_today_is_allowed_and_not_overdue():
    response = decide(accept_body(proposals()[0], due_date=date.today().isoformat()))
    assert response.status_code == 201 and response.json()["overdue"] is False


def test_rejection_needs_only_reason_and_closes_the_proposal():
    proposal = proposals()[0]
    assert decide({"recommendation_id": proposal["id"], "decision": "rejected", "reason": "Нерелевантно",
                   "owner": "Навчальний відділ"}).status_code == 422
    assert decide({"recommendation_id": proposal["id"], "decision": "rejected", "reason": " "}).status_code == 422
    response = decide({"recommendation_id": proposal["id"], "decision": "rejected", "reason": "Вже виконується"})
    assert response.status_code == 201
    action = response.json()
    assert action["status"] == "rejected" and action["owner"] is None and action["due_date"] is None
    assert action["allowed_transitions"] == [] and action["decision_reason"] == "Вже виконується"
    assert move(action["id"], status="in_progress", reason="Спроба").status_code == 409
    summary = tracker().json()["summary"]
    assert summary["rejected"] == 1 and summary["accepted_total"] == 0
    assert tracker_events(FIRST) == [("tracker.rejected", "admin", "{}")]


# --- Статуси і перевірка наступним оцінюванням ------------------------------------------------

def test_happy_path_through_verified_with_audit_trail():
    proposal = proposals()[0]
    action_id = accepted_action(proposal)
    started = move(action_id, status="in_progress", reason="Робочу групу створено")
    assert started.status_code == 200 and started.json()["allowed_transitions"] == ["completed"]
    assert move(action_id, status="completed", reason="Виконано").status_code == 422          # без доказів
    assert move(action_id, status="completed", reason="Виконано", evidence_refs=[" "]).status_code == 422
    done = move(action_id, status="completed", reason="План погоджено",
                evidence_refs=["Наказ №15 від 2026-12-01", "Протокол наради 7"])
    assert done.status_code == 200
    assert done.json()["evidence_refs"] == ["Наказ №15 від 2026-12-01", "Протокол наради 7"]
    assert done.json()["allowed_transitions"] == ["in_progress", "verified"]

    check = {"status": "verified", "reason": "Бал компонента зріс", "evidence_refs": ["Звіт циклу 2026-I"]}
    assert move(action_id, **check).status_code == 422                                  # без оцінювання
    for wrong in (FIRST, OPEN, 999999):                    # те саме, відкрите, неіснуюче
        assert move(action_id, **check, verified_in_assessment_id=wrong).status_code == 422, wrong
    assert move(action_id, **{**check, "evidence_refs": []}, verified_in_assessment_id=LATER).status_code == 422
    verified = move(action_id, **check, verified_in_assessment_id=LATER)
    assert verified.status_code == 200
    action = verified.json()
    assert action["status"] == "verified" and action["verified_in_assessment_id"] == LATER
    assert action["allowed_transitions"] == [] and action["overdue"] is False
    assert action["evidence_refs"] == ["Наказ №15 від 2026-12-01", "Протокол наради 7", "Звіт циклу 2026-I"]
    assert [(h["from_status"], h["to_status"]) for h in action["history"]] == [
        ("proposed", "accepted"), ("accepted", "in_progress"), ("in_progress", "completed"), ("completed", "verified")]
    assert all(h["actor_role"] == "admin" and h["reason"] and h["at"].endswith("Z") for h in action["history"])
    assert action["history"][-1]["verified_in_assessment_id"] == LATER
    assert move(action_id, status="in_progress", reason="Ще раз").status_code == 409

    data = tracker().json()
    assert [a["id"] for a in data["actions"]] == [action_id]
    assert data["summary"] == {"accepted_total": 1, "accepted": 0, "in_progress": 0, "completed": 0,
                               "verified": 1, "rejected": 0, "overdue": 0}
    # Журнал: кожна зміна, лише роль і цикл; невдалі спроби (409/422) не журналюються
    assert tracker_events(FIRST) == [(f"tracker.{status}", "admin", "{}")
                                     for status in ("accepted", "in_progress", "completed", "verified")]
    with SessionLocal() as db:
        text = " ".join(f"{e.action} {e.details}" for e in db.query(AuditEvent).all())
    assert "Навчальний відділ" not in text and "Наказ" not in text and "Погоджено" not in text


def test_verification_needs_a_later_cycle():
    proposal = proposals(LATER)[0]
    action_id = accepted_action(proposal, assessment_id=LATER)
    move(action_id, status="in_progress", reason="Почато")
    move(action_id, status="completed", reason="Виконано", evidence_refs=["Наказ 1"])
    earlier = move(action_id, status="verified", reason="Перевірено", evidence_refs=["Звіт"],
                   verified_in_assessment_id=FIRST)
    assert earlier.status_code == 422 and "пізніше" in earlier.json()["detail"]


@pytest.mark.parametrize("status,body", [
    ("completed", {"evidence_refs": ["Наказ 1"]}),
    ("verified", {"evidence_refs": ["Звіт"], "verified_in_assessment_id": LATER}),
])
def test_skipping_states_is_409(status, body):
    action_id = accepted_action(proposals()[0])
    assert move(action_id, status=status, reason="Пропустити крок", **body).status_code == 409
    assert tracker().json()["actions"][0]["status"] == "accepted"


def test_completed_can_return_to_work_and_invalid_inputs_are_rejected():
    action_id = accepted_action(proposals()[0])
    assert move(999999, status="in_progress", reason="x").status_code == 404
    assert move(action_id, status="accepted", reason="x").status_code == 422            # лише через рішення
    assert move(action_id, status="in_progress", reason=" ").status_code == 422
    assert move(action_id, status="in_progress", reason="x", verified_in_assessment_id=LATER).status_code == 422
    assert move(action_id, status="in_progress", reason="x", owner="Інший відділ").status_code == 422
    move(action_id, status="in_progress", reason="Почато")
    move(action_id, status="completed", reason="Виконано", evidence_refs=["Наказ 1"])
    reopened = move(action_id, status="in_progress", reason="Доказів недостатньо")
    assert reopened.status_code == 200 and reopened.json()["status"] == "in_progress"
    assert [(h["from_status"], h["to_status"]) for h in reopened.json()["history"]][-2:] == [
        ("in_progress", "completed"), ("completed", "in_progress")]
    assert tracker_events(FIRST)[-1][0] == "tracker.in_progress"


def test_overdue_is_derived_from_deadline_and_status():
    first, second, third = proposals()[:3]
    late = accepted_action(first)
    in_work = accepted_action(second)
    done = accepted_action(third)
    move(in_work, status="in_progress", reason="Почато")
    move(done, status="in_progress", reason="Почато")
    move(done, status="completed", reason="Виконано", evidence_refs=["Наказ 1"])
    with SessionLocal() as db:                    # строк минув учора (через API так не призначити)
        for row in db.query(RecommendationAction).all():
            row.due_date = date.today() - timedelta(days=1)
        db.commit()
    actions = {a["id"]: a for a in tracker().json()["actions"]}
    assert actions[late]["overdue"] is True and actions[in_work]["overdue"] is True
    assert actions[done]["overdue"] is False                          # виконане не прострочене
    assert tracker().json()["summary"]["overdue"] == 2


# --- Зберігання і міграція ------------------------------------------------------------------

def test_tracker_table_has_no_identity_columns():
    columns = {c["name"] for c in inspect(engine).get_columns("recommendation_actions")}
    assert {"owner", "due_date", "status", "decision_reason", "history_json"} <= columns
    assert not columns & {"user_id", "name", "email", "actor_id", "actor_name", "owner_name", "ip"}


def test_v3_database_gets_tracker_table_with_backup(tmp_path):
    db_file = tmp_path / "integrity.db"
    temp_engine = create_engine(f"sqlite:///{db_file}")
    assert migrate(temp_engine)["action"] == "created"
    RecommendationAction.__table__.drop(temp_engine)                # імітуємо базу версії 3
    with closing(sqlite3.connect(db_file)) as con:
        con.execute("INSERT INTO cycles (id, name, start_date, status, min_group_size) "
                    "VALUES (1, 'SYN', '2026-01-01', 'closed', 5)")
        con.execute("PRAGMA user_version = 3")
        con.commit()

    report = migrate(temp_engine)

    assert report["action"] == "migrated" and report["backup"]
    with closing(sqlite3.connect(db_file)) as con:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert con.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 7
        assert "recommendation_actions" in tables
        assert con.execute("SELECT name FROM cycles").fetchall() == [("SYN",)]
    with closing(sqlite3.connect(report["backup"])) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 3
    assert migrate(temp_engine)["action"] == "up_to_date"
    temp_engine.dispose()


def test_history_is_json_without_personal_fields():
    action_id = accepted_action(proposals()[0])
    with SessionLocal() as db:
        row = db.get(RecommendationAction, action_id)
        history = json.loads(row.history_json)
        assert isinstance(row.created_at, datetime)
    assert set(history[0]) == {"from_status", "to_status", "on_date", "at", "actor_role", "reason",
                               "evidence_refs", "owner", "due_date"}
