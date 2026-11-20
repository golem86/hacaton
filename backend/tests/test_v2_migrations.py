"""
Міграції V2 (V2 Integration Contract, розділ 5): MIG-1 і MIG-4.
Кожен тест працює з власними тимчасовими файлами БД.
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app import v2_auth
from app.main import create_app

# Схема V2_AUTH_DB у ранній редакції прототипу: без two_factor_verified, assessment_id, updated_at
PROTOTYPE_AUTH_DDL = """
CREATE TABLE v2_users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'admin')), created_at TEXT NOT NULL);
CREATE TABLE v2_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES v2_users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE, expires_at TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE v2_user_attempts (id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES v2_users(id) ON DELETE CASCADE,
    assessment_name TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ('draft', 'completed')),
    answers_json TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT);
CREATE TABLE v2_challenges (id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES v2_users(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL, code_hash TEXT NOT NULL, expires_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0, consumed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
INSERT INTO v2_users VALUES (1, 'User', 'u@example.test', 'scrypt$x', 'user', '2026-11-17');
INSERT INTO v2_sessions VALUES (1, 1, 'hash1', '2099-01-01', '2026-11-17');
INSERT INTO v2_user_attempts VALUES ('a1', 1, 'Q4', 'completed', '{"q1":3}', '2026-11-17', '2026-11-17');
"""


@pytest.fixture
def auth_db(tmp_path, monkeypatch):
    path = tmp_path / "v2_auth.db"
    monkeypatch.setenv("V2_AUTH_DB", str(path))
    return path


def snapshot(path: Path) -> dict:
    con = sqlite3.connect(path)
    data = {
        "version": con.execute("PRAGMA user_version").fetchone()[0],
        "users": con.execute("SELECT * FROM v2_users ORDER BY id").fetchall(),
        "attempts": con.execute("SELECT id, user_id, status, answers_json FROM v2_user_attempts").fetchall(),
        "sessions": con.execute("SELECT COUNT(*) FROM v2_sessions").fetchone()[0],
        "session_cols": [r[1] for r in con.execute("PRAGMA table_info(v2_sessions)")],
        "attempt_cols": [r[1] for r in con.execute("PRAGMA table_info(v2_user_attempts)")],
    }
    con.close()
    return data


# --- MIG-4: версіонування V2_AUTH_DB --------------------------------------------

def test_mig4_prototype_auth_db_is_migrated_with_backup_and_no_data_loss(auth_db):
    with sqlite3.connect(auth_db) as con:
        con.executescript(PROTOTYPE_AUTH_DDL)
    before = snapshot(auth_db)
    report = v2_auth.migrate_auth_db()
    after = snapshot(auth_db)
    assert report["action"] == "migrated"
    assert Path(report["backup"]).exists() and snapshot(Path(report["backup"]))["version"] == 0
    assert after["version"] == v2_auth.AUTH_SCHEMA_VERSION == 2      # auth schema 2: прототип → 2 одразу
    assert after["users"] == before["users"] and after["attempts"] == before["attempts"]
    assert after["sessions"] == before["sessions"]
    assert "two_factor_verified" in after["session_cols"]
    assert {"assessment_id", "updated_at"} <= set(after["attempt_cols"])
    with sqlite3.connect(auth_db) as con:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []


def test_mig4_migration_is_idempotent(auth_db):
    with sqlite3.connect(auth_db) as con:
        con.executescript(PROTOTYPE_AUTH_DDL)
    v2_auth.migrate_auth_db()
    first = snapshot(auth_db)
    assert v2_auth.migrate_auth_db()["action"] == "up_to_date"
    assert snapshot(auth_db) == first
    assert len(list(auth_db.parent.glob("v2_auth.backup-*.db"))) == 1


def test_mig4_empty_auth_db_is_created_at_current_version(auth_db):
    assert v2_auth.migrate_auth_db()["action"] == "created"
    assert snapshot(auth_db)["version"] == 2


def test_mig4_release_check_refuses_old_or_missing_auth_db(auth_db):
    with pytest.raises(RuntimeError, match="не знайдено"):
        v2_auth.check_auth_schema()
    with sqlite3.connect(auth_db) as con:
        con.executescript(PROTOTYPE_AUTH_DDL)
    with pytest.raises(RuntimeError, match="версію 0"):
        v2_auth.check_auth_schema()
    assert snapshot(auth_db)["version"] == 0           # перевірка нічого не змінила


# --- MIG-1: у release БД не змінюється автоматично --------------------------------

def test_mig1_release_does_not_migrate_old_integrity_db(tmp_path, monkeypatch):
    """Стара INTEGRITY_DB (версія 1, без журналу дій): release не стартує і БД не змінюється."""
    db = tmp_path / "integrity.db"
    with sqlite3.connect(db) as con:
        con.executescript("CREATE TABLE cycles (id INTEGER PRIMARY KEY); PRAGMA user_version = 1;")
    before = db.read_bytes()

    import app.database as database
    from sqlalchemy import create_engine
    monkeypatch.setattr("app.main.engine", create_engine(f"sqlite:///{db}"))
    monkeypatch.setenv("APP_ENV", "release")
    monkeypatch.setenv("V2_SECRET_KEY", "x" * 40)
    monkeypatch.setenv("V2_AUTH_DEV_MAIL", "0")
    monkeypatch.setenv("INTEGRITY_DEMO_XROLE", "0")
    monkeypatch.setenv("TRUSTED_PROXIES", "127.0.0.1")   # A15: обов'язковий у release
    monkeypatch.delenv("V2_CATALOG_NOW", raising=False)   # A15: заборонений у release
    with pytest.raises(RuntimeError, match="Автоміграція в release вимкнена"):
        create_app()
    assert db.read_bytes() == before                    # файл БД не змінено
    assert database.engine is not None


def test_mig1_explicit_migration_requires_confirmed_backup(tmp_path):
    # Дочірній процес пише UTF-8 незалежно від кодової сторінки консолі (cp866/cp1251 у Windows)
    env = {**os.environ, "INTEGRITY_DB": str(tmp_path / "i.db"), "V2_AUTH_DB": str(tmp_path / "a.db"),
           "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    backend = Path(__file__).resolve().parents[1]
    refused = subprocess.run([sys.executable, "-X", "utf8", "-m", "app.migrations", "--apply"], cwd=backend, env=env,
                             capture_output=True, text=True, encoding="utf-8")
    assert refused.returncode != 0 and "--confirm-verified-backup" in (refused.stdout + refused.stderr)
    assert not (tmp_path / "i.db").exists() or (tmp_path / "i.db").stat().st_size == 0
    applied = subprocess.run([sys.executable, "-X", "utf8", "-m", "app.migrations", "--apply",
                              "--confirm-verified-backup"],
                             cwd=backend, env=env, capture_output=True, text=True, encoding="utf-8")
    assert applied.returncode == 0, applied.stderr
    with sqlite3.connect(tmp_path / "i.db") as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 5
