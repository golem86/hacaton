"""
Міграція INTEGRITY_DB до schema 5 (docs/V2_HARDENING_CONTRACT.md, розділ 2; аудит D14).

Вихідні бази — справжня структура версій 3 (сервер TLSFIX5) і 4 (Recommendations Tracker)
з відкритими кодами в access_tokens.token (tests/legacy_schemas.py). Дані синтетичні.
"""
import hashlib
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import migrations
from app.database import get_db
from app.main import app
from app.migrations import SCHEMA_VERSION, MigrationError, check_schema, migrate
from legacy_schemas import LEGACY_CODES, make_legacy_db, table_rows


def sha(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def columns(path, table) -> list[str]:
    with closing(sqlite3.connect(path)) as con:
        return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def version(path) -> int:
    with closing(sqlite3.connect(path)) as con:
        return con.execute("PRAGMA user_version").fetchone()[0]


@pytest.fixture(params=[3, 4])
def legacy(request, tmp_path):
    path = tmp_path / "integrity.db"
    make_legacy_db(path, request.param)
    engine = create_engine(f"sqlite:///{path}")
    yield request.param, path, engine
    engine.dispose()


def test_schema_5_version():
    assert SCHEMA_VERSION == 5


def test_legacy_database_is_migrated_to_5_without_data_loss(legacy):
    old_version, path, engine = legacy
    before = table_rows(path)
    with closing(sqlite3.connect(path)) as con:
        audit_before = con.execute("SELECT * FROM audit_events ORDER BY id").fetchall()

    report = migrate(engine)

    assert report["action"] == "migrated" and report["access_tokens_hashed"] == len(LEGACY_CODES)
    assert version(path) == 5
    # Резервна копія — точна копія вихідної бази (і перевірена)
    backup = Path(report["backup"])
    assert backup.exists() and version(backup) == old_version and table_rows(backup) == before
    with closing(sqlite3.connect(backup)) as con:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    # Коди: лише SHA-256, id і позначки used збережені, політики вказують на ті самі рядки
    assert columns(path, "access_tokens") == ["id", "cycle_id", "token_hash", "used"]
    with closing(sqlite3.connect(path)) as con:
        tokens = con.execute("SELECT id, cycle_id, token_hash, used FROM access_tokens ORDER BY id").fetchall()
        assert tokens == [(i, c, sha(code), used) for i, c, code, used in LEGACY_CODES]
        assert con.execute("SELECT * FROM audit_events ORDER BY id").fetchall() == [r + (None,) for r in audit_before]
        assert con.execute("SELECT COUNT(*) FROM instance_meta").fetchone()[0] == 0
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        dump = "\n".join(con.iterdump())
    assert not any(code in dump for _, _, code, _ in LEGACY_CODES)     # відкритих кодів у БД більше немає
    after = table_rows(path)
    assert {t: rows for t, rows in after.items() if t in before} == before
    assert set(after) - set(before) <= {"instance_meta", "recommendation_actions"}
    assert "actor_user_id" in columns(path, "audit_events")
    check_schema(engine)


def test_old_plaintext_code_is_accepted_after_migration(legacy):
    _, path, engine = legacy
    migrate(engine)
    Session = sessionmaker(bind=engine)

    def override():
        with Session() as s:
            yield s

    body = {"respondent_category": "cadets", "unit": "Факультет 1", "questionnaire_version": "demo-v1",
            "answers": [{"question_id": 1, "value": 3}, {"question_id": 2, "value": 4}]}
    app.dependency_overrides[get_db] = override
    try:
        client = TestClient(app)
        url = "/api/assessments/1/submissions"
        assert client.post(url, json={**body, "token": "legacy-open-code-unused-1"}).status_code == 201
        assert client.post(url, json={**body, "token": "legacy-open-code-unused-1"}).status_code == 403
        assert client.post(url, json={**body, "token": "legacy-open-code-used-2"}).status_code == 403
        assert client.post(url, json={**body, "token": sha("legacy-open-code-unused-3")}).status_code == 403
    finally:
        app.dependency_overrides.clear()
    with closing(sqlite3.connect(path)) as con:
        assert con.execute("SELECT used FROM access_tokens WHERE id = 1").fetchone() == (1,)
        assert con.execute("SELECT used FROM access_tokens WHERE id = 3").fetchone() == (0,)


def test_second_run_changes_nothing(legacy):
    _, path, engine = legacy
    migrate(engine)
    engine.dispose()
    snapshot = path.read_bytes()
    assert migrate(engine) == {"action": "up_to_date", "backup": None}
    engine.dispose()
    assert path.read_bytes() == snapshot
    assert len(list(path.parent.glob("integrity.backup-*.db"))) == 1


def test_newer_version_is_refused_without_changes(legacy):
    _, path, engine = legacy
    with closing(sqlite3.connect(path)) as con:
        con.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        con.commit()
    before = path.read_bytes()
    with pytest.raises(MigrationError, match="newer"):
        migrate(engine)
    engine.dispose()
    assert path.read_bytes() == before
    assert list(path.parent.glob("*.backup-*")) == []


def test_failed_check_rolls_back_everything(legacy, monkeypatch):
    old_version, path, engine = legacy
    before = table_rows(path)
    original = migrations.schema_problems
    calls = []

    def injected(con):
        calls.append(1)
        return original(con) + ["штучна помилка перевірки"]

    monkeypatch.setattr(migrations, "schema_problems", injected)
    with pytest.raises(MigrationError, match="відкочено"):
        migrate(engine)
    engine.dispose()
    assert calls
    assert version(path) == old_version and table_rows(path) == before
    assert columns(path, "access_tokens") == ["id", "cycle_id", "token", "used"]
    assert "actor_user_id" not in columns(path, "audit_events")
    with closing(sqlite3.connect(path)) as con:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "instance_meta" not in tables and not any(t.startswith("_legacy") for t in tables)
    assert len(list(path.parent.glob("integrity.backup-*.db"))) == 1


def test_unknown_access_tokens_shape_is_refused(tmp_path):
    path = tmp_path / "integrity.db"
    make_legacy_db(path, 4)
    with closing(sqlite3.connect(path)) as con:
        con.execute("ALTER TABLE access_tokens ADD COLUMN note TEXT")
        con.commit()
    engine = create_engine(f"sqlite:///{path}")
    with pytest.raises(MigrationError, match="access_tokens"):
        migrate(engine)
    engine.dispose()
    assert version(path) == 4 and "token" in columns(path, "access_tokens")


def test_release_check_refuses_legacy_database_without_changing_it(legacy):
    _, path, engine = legacy
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="Автоміграція в release вимкнена"):
        check_schema(engine)
    engine.dispose()
    assert path.read_bytes() == before


def test_explicit_cli_migration_reaches_schema_5(tmp_path):
    path = tmp_path / "integrity.db"
    make_legacy_db(path, 3)
    env = {**os.environ, "INTEGRITY_DB": str(path), "V2_AUTH_DB": str(tmp_path / "auth.db")}
    backend = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-m", "app.migrations", "--apply", "--confirm-verified-backup"],
                            cwd=backend, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert result.returncode == 0, result.stderr
    assert version(path) == 5
    assert columns(path, "access_tokens") == ["id", "cycle_id", "token_hash", "used"]
