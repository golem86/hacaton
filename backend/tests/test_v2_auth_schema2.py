"""
V2_AUTH_DB schema 2 (docs/V2_HARDENING_CONTRACT.md, розділ 2): роль data_officer, append-only v2_role_changes.

  - міграція 1→2 зі СПРАВЖНЬОГО DDL schema 1 (release TLSFIX5): рядки, pending-сесії, лічильник
    AUTOINCREMENT і DDL інших таблиць зберігаються; результат ідентичний свіжій БД;
  - перевірена резервна копія ДО міграції; помилка → відкат, БД не змінена;
  - версія > 2 → відмова без змін; код ніколи не знижує user_version;
  - check_auth_schema у release лише читає і перевіряє версію, таблиці, CHECK з data_officer і тригери;
  - init_auth_db у release існуючу БД не мігрує.
"""
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from app import v2_auth
from app.v2_auth import AuthMigrationError

BACKEND = Path(__file__).resolve().parents[1]

# Дослівно _SCHEMA з backend/app/v2_auth.py release TLSFIX5 (AUTH_SCHEMA_VERSION = 1)
SCHEMA1_DDL = """
CREATE TABLE IF NOT EXISTS v2_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'admin')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS v2_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES v2_users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    two_factor_verified INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_v2_sessions_token ON v2_sessions(token_hash);
CREATE TABLE IF NOT EXISTS v2_user_attempts (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES v2_users(id) ON DELETE CASCADE,
    assessment_id TEXT NOT NULL DEFAULT 'legacy',
    assessment_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft', 'completed')),
    answers_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_v2_attempts_user ON v2_user_attempts(user_id, started_at DESC);
CREATE TABLE IF NOT EXISTS v2_challenges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES v2_users(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL CHECK (purpose IN ('login_2fa', 'password_reset')),
    code_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    consumed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS v2_rate_limits (
    scope TEXT NOT NULL,
    subject TEXT NOT NULL,
    window_started TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (scope, subject)
);
"""
DATA_TABLES = ("v2_users", "v2_sessions", "v2_user_attempts", "v2_challenges", "v2_rate_limits")


@pytest.fixture
def auth_db(tmp_path, monkeypatch):
    path = tmp_path / "v2_auth.db"
    monkeypatch.setenv("V2_AUTH_DB", str(path))
    return path


def make_schema1(path: Path) -> None:
    with closing(sqlite3.connect(path)) as db:
        db.executescript(SCHEMA1_DDL)
        db.executescript("""
            INSERT INTO v2_users VALUES (1, 'Admin', 'a@example.test', 'scrypt$16384$8$1$s$d', 'admin', '2026-11-17');
            INSERT INTO v2_users VALUES (2, 'User', 'u@example.test', 'scrypt$16384$8$1$s$e', 'user', '2026-11-17');
            INSERT INTO v2_users VALUES (3, 'Gone', 'g@example.test', 'scrypt$16384$8$1$s$f', 'user', '2026-11-17');
            DELETE FROM v2_users WHERE id = 3;
            INSERT INTO v2_sessions VALUES (1, 1, 'verified-hash', '2099-01-01', '2026-11-17', 1);
            INSERT INTO v2_sessions VALUES (2, 2, 'pending-hash', '2099-01-01', '2026-11-17', 0);
            INSERT INTO v2_user_attempts VALUES ('a1', 2, 'personal-2026-q4', 'Q4', 'draft', '{"q1":3}',
                                                 '2026-11-17', NULL, '2026-11-17');
            INSERT INTO v2_challenges VALUES (1, 2, 'login_2fa', 'c', '2099-01-01', 1, 0, '2026-11-17');
            INSERT INTO v2_rate_limits VALUES ('login', 'u@example.test|198.51.100.1', '2026-11-17', 2);
            PRAGMA user_version = 1;
        """)
        db.commit()


def dump(path: Path) -> dict:
    with closing(sqlite3.connect(path)) as db:
        return {t: db.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() for t in DATA_TABLES}


def catalog(path: Path) -> list:
    with closing(sqlite3.connect(path)) as db:
        return sorted((r[0], r[1], r[2], " ".join((r[3] or "").split()))
                      for r in db.execute("SELECT type, name, tbl_name, sql FROM sqlite_master"))


def ddl(path: Path, name: str) -> str:
    with closing(sqlite3.connect(path)) as db:
        return db.execute("SELECT sql FROM sqlite_master WHERE name = ?", (name,)).fetchone()[0]


def version(path: Path) -> int:
    with closing(sqlite3.connect(path)) as db:
        return db.execute("PRAGMA user_version").fetchone()[0]


def test_migration_1_to_2_keeps_rows_pending_sessions_and_sequence(auth_db, tmp_path, monkeypatch):
    make_schema1(auth_db)
    before, sessions_ddl = dump(auth_db), ddl(auth_db, "v2_sessions")
    report = v2_auth.migrate_auth_db()
    assert report["action"] == "migrated" and report["from_version"] == 1
    backup = Path(report["backup"])
    assert version(backup) == 1 and dump(backup) == before
    with closing(sqlite3.connect(backup)) as copy:
        assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert version(auth_db) == 2
    assert dump(auth_db) == before                                      # усі рядки, включно з pending
    assert ddl(auth_db, "v2_sessions") == sessions_ddl                  # REFERENCES v2_users(id) не переписано
    with closing(sqlite3.connect(auth_db)) as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT seq FROM sqlite_sequence WHERE name = 'v2_users'").fetchone()[0] == 3
        assert db.execute("SELECT name FROM sqlite_master WHERE name LIKE '%schema1%'").fetchall() == []
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("UPDATE v2_users SET role = 'data_officer' WHERE id = 2")
        new_id = db.execute("INSERT INTO v2_users(name, email, password_hash, role, created_at) "
                            "VALUES ('N', 'n@example.test', 'h', 'user', 't')").lastrowid
        assert new_id == 4                                              # id видаленого акаунта не повторюється
        db.rollback()
    v2_auth.check_auth_schema()
    fresh = tmp_path / "fresh.db"
    monkeypatch.setenv("V2_AUTH_DB", str(fresh))
    monkeypatch.setenv("V2_AUTH_DEV_MAIL", "0")
    v2_auth.migrate_auth_db()
    migrated_catalog = [o for o in catalog(auth_db) if o[1] != "v2_dev_mail"]
    assert migrated_catalog == catalog(fresh)                           # DDL мігрованої = DDL свіжої


def test_prototype_v0_is_migrated_straight_to_2(auth_db):
    with closing(sqlite3.connect(auth_db)) as db:
        db.executescript("""
            CREATE TABLE v2_users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'admin')), created_at TEXT NOT NULL);
            CREATE TABLE v2_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES v2_users(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE, expires_at TEXT NOT NULL, created_at TEXT NOT NULL);
            INSERT INTO v2_users VALUES (1, 'User', 'u@example.test', 'scrypt$x', 'user', '2026-11-17');
            INSERT INTO v2_sessions VALUES (1, 1, 'hash1', '2099-01-01', '2026-11-17');
        """)
    assert v2_auth.migrate_auth_db()["action"] == "migrated"
    assert version(auth_db) == 2
    v2_auth.check_auth_schema()


def test_newer_version_is_refused_without_any_change(auth_db):
    make_schema1(auth_db)
    with closing(sqlite3.connect(auth_db)) as db:
        db.execute("PRAGMA user_version = 3")
        db.commit()
    before = auth_db.read_bytes()
    with pytest.raises(AuthMigrationError, match="новішу"):
        v2_auth.migrate_auth_db()
    with pytest.raises(RuntimeError, match="версію 3"):
        v2_auth.check_auth_schema()
    assert auth_db.read_bytes() == before
    assert sorted(p.name for p in auth_db.parent.iterdir()) == ["v2_auth.db"]     # жодної резервної копії


def test_current_version_is_never_rewritten_or_downgraded(auth_db):
    assert v2_auth.migrate_auth_db()["action"] == "created"
    before = auth_db.read_bytes()
    for _ in range(2):
        assert v2_auth.migrate_auth_db() == {"action": "up_to_date", "backup": None}
    assert version(auth_db) == 2
    assert list(auth_db.parent.glob("*.backup-*")) == []
    with closing(sqlite3.connect(auth_db)) as db:                       # версія не знижується навіть без змін
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
    assert auth_db.read_bytes() == before


def test_failed_migration_rolls_back_to_schema1(auth_db):
    make_schema1(auth_db)
    with closing(sqlite3.connect(auth_db)) as db:                       # сирітська сесія: foreign_key_check
        db.execute("INSERT INTO v2_sessions VALUES (9, 99, 'orphan', '2099-01-01', '2026-11-17', 0)")
        db.commit()
    before, users_ddl = dump(auth_db), ddl(auth_db, "v2_users")
    with pytest.raises(AuthMigrationError, match="відкочено"):
        v2_auth.migrate_auth_db()
    assert version(auth_db) == 1 and dump(auth_db) == before
    assert ddl(auth_db, "v2_users") == users_ddl
    with closing(sqlite3.connect(auth_db)) as db:
        assert "v2_role_changes" not in {r[0] for r in db.execute("SELECT name FROM sqlite_master")}
    assert len(list(auth_db.parent.glob("v2_auth.backup-*.db"))) == 1


def test_unverified_backup_stops_migration_before_changes(auth_db, monkeypatch):
    make_schema1(auth_db)
    before = auth_db.read_bytes()
    real_counts, calls = v2_auth._counts, []

    def counts(db, tables):
        calls.append(1)
        result = real_counts(db, tables)
        return {} if len(calls) == 2 else result                        # «копія» з іншою кількістю рядків
    monkeypatch.setattr(v2_auth, "_counts", counts)
    with pytest.raises(AuthMigrationError, match="Резервна копія"):
        v2_auth.migrate_auth_db()
    assert auth_db.read_bytes() == before


def test_role_changes_are_append_only_and_do_not_block_user_deletion(auth_db):
    v2_auth.migrate_auth_db()
    with closing(sqlite3.connect(auth_db)) as db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("INSERT INTO v2_users VALUES (1, 'A', 'a@example.test', 'h', 'admin', 't')")
        db.execute("INSERT INTO v2_users VALUES (2, 'B', 'b@example.test', 'h', 'user', 't')")
        db.execute("INSERT INTO v2_role_changes(actor_user_id, target_user_id, old_role, new_role, changed_at) "
                   "VALUES (1, 2, 'user', 'data_officer', 't')")
        db.commit()
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("UPDATE v2_role_changes SET new_role = 'admin'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("DELETE FROM v2_role_changes")
        db.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO v2_role_changes(actor_user_id, target_user_id, old_role, new_role, changed_at) "
                       "VALUES (1, 2, 'user', 'superadmin', 't')")
        db.execute("DELETE FROM v2_users WHERE id = 2")                 # немає FK → видалення не блокується
        db.commit()
        assert db.execute("SELECT actor_user_id, target_user_id, old_role, new_role FROM v2_role_changes"
                          ).fetchall() == [(1, 2, "user", "data_officer")]


def test_release_check_is_read_only_and_strict(auth_db):
    with pytest.raises(RuntimeError, match="не знайдено"):
        v2_auth.check_auth_schema()
    assert not auth_db.exists()                                         # перевірка не створює файл
    v2_auth.migrate_auth_db()
    v2_auth.check_auth_schema()
    with closing(sqlite3.connect(auth_db)) as db:
        db.execute("DROP TRIGGER v2_role_changes_no_delete")
        db.commit()
    before = auth_db.read_bytes()
    with pytest.raises(RuntimeError, match="v2_role_changes_no_delete"):
        v2_auth.check_auth_schema()
    assert auth_db.read_bytes() == before


def test_release_check_rejects_version_2_without_data_officer(auth_db):
    make_schema1(auth_db)
    with closing(sqlite3.connect(auth_db)) as db:                       # підроблена «версія 2» зі старим CHECK
        for statement in v2_auth._statements(v2_auth._SCHEMA):
            if "v2_role_changes" in statement:
                db.execute(statement)
        db.execute("PRAGMA user_version = 2")
        db.commit()
    with pytest.raises(RuntimeError, match="data_officer"):
        v2_auth.check_auth_schema()


def test_release_init_does_not_migrate_existing_db(auth_db, monkeypatch):
    make_schema1(auth_db)
    before = auth_db.read_bytes()
    monkeypatch.setenv("APP_ENV", "release")
    with pytest.raises(RuntimeError, match="версію 1"):
        v2_auth.init_auth_db()
    assert auth_db.read_bytes() == before and version(auth_db) == 1


def test_explicit_migration_command_brings_auth_db_to_2(tmp_path):
    auth = tmp_path / "a.db"
    make_schema1(auth)
    env = {**os.environ, "INTEGRITY_DB": str(tmp_path / "i.db"), "V2_AUTH_DB": str(auth), "APP_ENV": "release",
           "V2_AUTH_DEV_MAIL": "0"}
    applied = subprocess.run([sys.executable, "-m", "app.migrations", "--apply", "--confirm-verified-backup"],
                             cwd=BACKEND, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert applied.returncode == 0, applied.stderr
    assert version(auth) == 2
    assert len(list(tmp_path.glob("a.backup-*.db"))) == 1
