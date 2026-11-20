"""
Release-конфігурація і bootstrap адміністратора (docs/V2_HARDENING_CONTRACT.md, розділи 2 і 3):
  - A15: у release TRUSTED_PROXIES обов'язковий, V2_CATALOG_NOW заборонений;
  - A17: з V2_SMTP_HOST потрібна справжня V2_SMTP_FROM; V2_SMTP_TLS_MODE — лише starttls|implicit;
  - A16: bootstrap не створює другого admin без --allow-additional-admin і в release не мігрує БД.
"""
import sqlite3
from contextlib import closing

import pytest

from app import settings, v2_auth, v2_bootstrap_admin
from app.database import SessionLocal
from app.models import AuditEvent

from v2_helpers import PASSWORD, new_email


@pytest.fixture
def release(monkeypatch):
    monkeypatch.setenv("APP_ENV", "release")
    monkeypatch.setenv("V2_SECRET_KEY", "x" * 40)
    monkeypatch.setenv("V2_AUTH_DEV_MAIL", "0")
    monkeypatch.setenv("INTEGRITY_DEMO_XROLE", "0")
    monkeypatch.setenv("TRUSTED_PROXIES", "127.0.0.1")
    for name in ("V2_CATALOG_NOW", "V2_AUTH_SECURE_COOKIE", "V2_SMTP_HOST", "V2_SMTP_FROM", "V2_SMTP_TLS_MODE"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_valid_release_config_passes(release):
    settings.validate_release_config()
    release.setenv("V2_SMTP_HOST", "smtp.example.test")
    release.setenv("V2_SMTP_FROM", "Integrity Dashboard <no-reply@example.test>")
    release.setenv("V2_SMTP_TLS_MODE", "implicit")
    settings.validate_release_config()


@pytest.mark.parametrize("change, message", [
    (lambda m: m.delenv("TRUSTED_PROXIES"), "TRUSTED_PROXIES"),
    (lambda m: m.setenv("TRUSTED_PROXIES", " , "), "TRUSTED_PROXIES"),
    (lambda m: m.setenv("V2_CATALOG_NOW", "2026-11-18T12:00:00+00:00"), "V2_CATALOG_NOW"),
    (lambda m: m.setenv("V2_SMTP_HOST", "smtp.example.test"), "V2_SMTP_FROM"),
    (lambda m: (m.setenv("V2_SMTP_HOST", "smtp.example.test"), m.setenv("V2_SMTP_FROM", "no-reply@localhost")),
     "V2_SMTP_FROM"),
    (lambda m: (m.setenv("V2_SMTP_HOST", "smtp.example.test"), m.setenv("V2_SMTP_FROM", "not-an-address")),
     "V2_SMTP_FROM"),
    (lambda m: m.setenv("V2_SMTP_TLS_MODE", "plain"), "V2_SMTP_TLS_MODE"),
])
def test_unsafe_release_config_is_refused(release, change, message):
    change(release)
    with pytest.raises(RuntimeError, match=message):
        settings.validate_release_config()


def test_development_ignores_release_only_rules(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
    settings.validate_release_config()                        # conftest задає V2_CATALOG_NOW для тестів


# --- A16: bootstrap адміністратора --------------------------------------------------------------------------

@pytest.fixture
def bootstrap(tmp_path, monkeypatch):
    db = tmp_path / "v2_auth.db"
    monkeypatch.setenv("V2_AUTH_DB", str(db))
    monkeypatch.setattr(v2_bootstrap_admin.getpass, "getpass", lambda prompt="": PASSWORD)

    def run(*extra: str, email: str | None = None):
        v2_bootstrap_admin.main(["--name", "Local Admin", "--email", email or new_email(), *extra])
    return db, run


def admins(db) -> int:
    with closing(sqlite3.connect(db)) as con:
        return con.execute("SELECT COUNT(*) FROM v2_users WHERE role = 'admin'").fetchone()[0]


def test_bootstrap_creates_first_admin_and_refuses_a_second(bootstrap, capsys):
    db, run = bootstrap
    with SessionLocal() as session:
        before = session.query(AuditEvent).filter(AuditEvent.action == "user.create_admin").count()
    email = new_email()
    run(email=email)
    assert admins(db) == 1
    assert email not in capsys.readouterr().out                 # email не виводиться в журнал консолі
    with pytest.raises(SystemExit, match="уже існує"):
        run()
    assert admins(db) == 1
    run("--allow-additional-admin")
    assert admins(db) == 2
    with SessionLocal() as session:
        assert session.query(AuditEvent).filter(AuditEvent.action == "user.create_admin").count() == before + 2


def test_bootstrap_check_and_insert_are_one_transaction(bootstrap, monkeypatch):
    db, run = bootstrap
    v2_auth.migrate_auth_db()
    monkeypatch.setattr(v2_bootstrap_admin, "admin_exists", lambda: False)      # гонка: перевірка пройшла раніше
    v2_auth.create_user("Other", new_email(), PASSWORD, role="admin")
    with pytest.raises(SystemExit, match="уже існує"):
        run()
    assert admins(db) == 1


def test_bootstrap_in_release_does_not_migrate_existing_db(bootstrap, monkeypatch):
    db, run = bootstrap
    with closing(sqlite3.connect(db)) as con:                    # БД schema 1 (до міграції)
        con.executescript("CREATE TABLE v2_users (id INTEGER PRIMARY KEY, email TEXT); PRAGMA user_version = 1;")
    before = db.read_bytes()
    monkeypatch.setenv("APP_ENV", "release")
    asked = []
    monkeypatch.setattr(v2_bootstrap_admin.getpass, "getpass", lambda prompt="": asked.append(prompt) or PASSWORD)
    with pytest.raises(RuntimeError, match="версію 1"):
        run()
    assert db.read_bytes() == before and asked == []            # ні міграції, ні запиту пароля
