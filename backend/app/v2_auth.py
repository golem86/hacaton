"""Сховище ідентичності й персонального контуру Dashboard V2 (V2_AUTH_DB).

Окрема SQLite-база: акаунти, сесії, OTP-виклики, ліміти спроб і персональні спроби.
Анонімних відповідей тут немає і бути не може — вони лише в INTEGRITY_DB (Survey API).

Що змінено відносно прототипу (V2 Integration Contract):
  - схема версіонується через PRAGMA user_version (MIG-4) з резервною копією і перевірками;
  - сесія ротується після 2FA (S7);
  - dev-скринька з OTP існує лише в режимі development (S3);
  - імена cookie з префіксом __Host- у режимі Secure (S8, CSRF 3.0).
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import smtplib
import sqlite3
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from . import settings

AUTH_SCHEMA_VERSION = 1
SESSION_TTL_HOURS = 12


class MailNotConfigured(RuntimeError):
    """У release немає SMTP — надіслати код неможливо (відкрите питання №5: провайдер)."""


class MailDeliveryError(RuntimeError):
    """SMTP недоступний або не пройшов перевірку TLS — лист не надіслано, код не збережено."""


class AuthMigrationError(RuntimeError):
    """Міграцію V2_AUTH_DB не виконано; база лишилась без змін."""


def auth_db_path() -> Path:
    return Path(os.environ.get("V2_AUTH_DB", Path(__file__).resolve().parent.parent / "v2_auth.db"))


def session_cookie_name() -> str:
    return "__Host-v2_session" if settings.secure_cookies() else "v2_session"


def preauth_cookie_name() -> str:
    return "__Host-v2_preauth" if settings.secure_cookies() else "v2_preauth"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _connect() -> sqlite3.Connection:
    path = auth_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Схема і міграції (MIG-4)
# ---------------------------------------------------------------------------

_SCHEMA = """
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

# Таблиця з OTP відкритим текстом — ЛИШЕ для development (S3)
_DEV_MAIL_SCHEMA = """
CREATE TABLE IF NOT EXISTS v2_dev_mail (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

_COUNTED_TABLES = ("v2_users", "v2_sessions", "v2_user_attempts", "v2_challenges")


def _tables(db: sqlite3.Connection) -> set[str]:
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def auth_schema_version() -> int:
    with _connect() as db:
        return db.execute("PRAGMA user_version").fetchone()[0]


def _backup(db: sqlite3.Connection) -> Path:
    path = auth_db_path()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.stem}.backup-{stamp}{path.suffix}")
    with sqlite3.connect(target) as dst:
        db.backup(dst)
    return target


def migrate_auth_db() -> dict[str, Any]:
    """
    Доводить V2_AUTH_DB до AUTH_SCHEMA_VERSION.
      - порожня БД: створюється схема, версія 1;
      - БД прототипу (версія 0): резервна копія → у транзакції додаються відсутні колонки →
        перевірка кількості рядків, foreign_key_check, integrity_check → версія 1; при помилці відкат;
      - актуальна БД: нічого не змінюється.
    """
    report: dict[str, Any] = {"action": "up_to_date", "backup": None}
    db = _connect()
    try:
        existing = _tables(db)
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if not existing & set(_COUNTED_TABLES):
            db.executescript(_SCHEMA)
            report["action"] = "created"
        elif version < AUTH_SCHEMA_VERSION:
            report["backup"] = str(_backup(db))
            before = {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in _COUNTED_TABLES if t in existing}
            db.isolation_level = None
            db.execute("BEGIN")
            try:
                for statement in _SCHEMA.split(";"):
                    if statement.strip():
                        db.execute(statement)
                columns = {r[1] for r in db.execute("PRAGMA table_info(v2_sessions)")}
                if "two_factor_verified" not in columns:
                    db.execute("ALTER TABLE v2_sessions ADD COLUMN two_factor_verified INTEGER NOT NULL DEFAULT 0")
                columns = {r[1] for r in db.execute("PRAGMA table_info(v2_user_attempts)")}
                if "assessment_id" not in columns:
                    db.execute("ALTER TABLE v2_user_attempts ADD COLUMN assessment_id TEXT NOT NULL DEFAULT 'legacy'")
                if "updated_at" not in columns:
                    db.execute("ALTER TABLE v2_user_attempts ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")
                after = {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in before}
                problems = [f"{t}: {before[t]} → {after[t]}" for t in before if before[t] != after[t]]
                if db.execute("PRAGMA foreign_key_check").fetchall():
                    problems.append("порушено зовнішні ключі")
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    problems.append("integrity_check не ok")
                if problems:
                    raise AuthMigrationError("; ".join(problems))
                db.execute(f"PRAGMA user_version = {AUTH_SCHEMA_VERSION}")
                db.execute("COMMIT")
            except Exception as exc:
                db.execute("ROLLBACK")
                raise AuthMigrationError(f"Міграцію V2_AUTH_DB відкочено: {exc}. Копія: {report['backup']}") from exc
            report.update(action="migrated", rows=before)
        if settings.dev_mail_enabled():
            db.executescript(_DEV_MAIL_SCHEMA)
        db.execute(f"PRAGMA user_version = {AUTH_SCHEMA_VERSION}")
        db.commit()
    finally:
        db.close()
    return report


def check_auth_schema() -> None:
    """MIG-1 для release: лише перевірка, без змін."""
    path = auth_db_path()
    if not path.exists():
        raise RuntimeError(f"V2_AUTH_DB не знайдено ({path}); створіть її явною міграцією")
    version = auth_schema_version()
    if version != AUTH_SCHEMA_VERSION:
        raise RuntimeError(f"V2_AUTH_DB має версію {version}, очікується {AUTH_SCHEMA_VERSION}; "
                           "виконайте явну міграцію після перевіреної резервної копії")


def init_auth_db() -> None:
    """Сумісність з прототипом і CLI: створення/міграція в режимі development."""
    migrate_auth_db()


# ---------------------------------------------------------------------------
# Ліміти спроб
# ---------------------------------------------------------------------------

def consume_rate_limit(scope: str, subject: str, limit: int, window_minutes: int) -> bool:
    """Зараховує спробу і повертає, чи вона ще в межах ліміту."""
    now = _utc_now()
    with _connect() as db:
        row = db.execute("SELECT window_started, attempts FROM v2_rate_limits WHERE scope = ? AND subject = ?",
                         (scope, subject)).fetchone()
        if row is None or datetime.fromisoformat(row["window_started"]) + timedelta(minutes=window_minutes) <= now:
            db.execute(
                "INSERT INTO v2_rate_limits(scope, subject, window_started, attempts) VALUES (?, ?, ?, 1) "
                "ON CONFLICT(scope, subject) DO UPDATE SET window_started=excluded.window_started, attempts=1",
                (scope, subject, now.isoformat()))
            return True
        if int(row["attempts"]) >= limit:
            return False
        db.execute("UPDATE v2_rate_limits SET attempts = attempts + 1 WHERE scope = ? AND subject = ?", (scope, subject))
        return True


def is_rate_limited(scope: str, subject: str, limit: int, window_minutes: int) -> bool:
    """Перевіряє ліміт БЕЗ зарахування спроби (для лічильників лише невдалих спроб)."""
    with _connect() as db:
        row = db.execute("SELECT window_started, attempts FROM v2_rate_limits WHERE scope = ? AND subject = ?",
                         (scope, subject)).fetchone()
    if row is None:
        return False
    if datetime.fromisoformat(row["window_started"]) + timedelta(minutes=window_minutes) <= _utc_now():
        return False
    return int(row["attempts"]) >= limit


def clear_rate_limit(scope: str, subject: str) -> None:
    with _connect() as db:
        db.execute("DELETE FROM v2_rate_limits WHERE scope = ? AND subject = ?", (scope, subject))


# ---------------------------------------------------------------------------
# Користувачі й паролі
# ---------------------------------------------------------------------------

def normalize_email(email: str) -> str:
    return email.strip().lower()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16_384, r=8, p=1)
    return f"scrypt$16384$8$1${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode("utf-8"), salt=_unb64(salt), n=int(n), r=int(r), p=int(p))
        return secrets.compare_digest(actual, _unb64(expected))
    except (ValueError, TypeError):
        return False


def public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return {"id": int(row["id"]), "name": row["name"], "email": row["email"], "role": row["role"]}


def user_exists(email: str) -> bool:
    with _connect() as db:
        return db.execute("SELECT 1 FROM v2_users WHERE email = ?", (normalize_email(email),)).fetchone() is not None


def find_user_id(email: str) -> int | None:
    with _connect() as db:
        row = db.execute("SELECT id FROM v2_users WHERE email = ?", (normalize_email(email),)).fetchone()
    return int(row[0]) if row else None


def create_user(name: str, email: str, password: str, role: str = "user") -> dict[str, Any]:
    if role not in {"user", "admin"}:
        raise ValueError("Непідтримувана роль")
    now = _utc_now().isoformat()
    with _connect() as db:
        try:
            cursor = db.execute(
                "INSERT INTO v2_users(name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (name.strip(), normalize_email(email), hash_password(password), role, now))
        except sqlite3.IntegrityError as error:
            raise ValueError("Користувач з таким email уже існує") from error
        row = db.execute("SELECT id, name, email, role FROM v2_users WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return public_user(row)


def authenticate(email: str, password: str) -> dict[str, Any] | None:
    with _connect() as db:
        row = db.execute("SELECT * FROM v2_users WHERE email = ?", (normalize_email(email),)).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        return None
    return public_user(row)


# ---------------------------------------------------------------------------
# Сесії
# ---------------------------------------------------------------------------

def create_session(user_id: int, two_factor_verified: bool = False) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires = _utc_now() + timedelta(hours=SESSION_TTL_HOURS)
    with _connect() as db:
        db.execute("DELETE FROM v2_sessions WHERE expires_at <= ?", (_utc_now().isoformat(),))
        db.execute(
            "INSERT INTO v2_sessions(user_id, token_hash, expires_at, created_at, two_factor_verified) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, token_hash(token), expires.isoformat(), _utc_now().isoformat(), int(two_factor_verified)))
    return token, expires


def user_for_session(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    with _connect() as db:
        row = db.execute(
            "SELECT u.id, u.name, u.email, u.role, s.two_factor_verified FROM v2_sessions s "
            "JOIN v2_users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ?",
            (token_hash(token), _utc_now().isoformat())).fetchone()
    if not row:
        return None
    user = public_user(row)
    user["two_factor_verified"] = bool(row["two_factor_verified"])
    return user


def rotate_session_after_2fa(old_token: str, user_id: int) -> tuple[str, datetime]:
    """S7: після 2FA видається НОВИЙ токен, старий (pending) видаляється."""
    delete_session(old_token)
    return create_session(user_id, two_factor_verified=True)


def delete_session(token: str | None) -> None:
    if not token:
        return
    with _connect() as db:
        db.execute("DELETE FROM v2_sessions WHERE token_hash = ?", (token_hash(token),))


# ---------------------------------------------------------------------------
# OTP-коди і пошта
# ---------------------------------------------------------------------------

def issue_challenge(user_id: int, purpose: str, recipient: str) -> datetime:
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = _utc_now() + timedelta(minutes=10)
    subject = ("Integrity Dashboard V2: скидання паролю" if purpose == "password_reset"
               else "Integrity Dashboard V2: код підтвердження")
    deliver_mail(recipient, subject, f"Ваш код: {code}. Код дійсний 10 хвилин.")
    with _connect() as db:
        db.execute("UPDATE v2_challenges SET consumed = 1 WHERE user_id = ? AND purpose = ? AND consumed = 0",
                   (user_id, purpose))
        db.execute("INSERT INTO v2_challenges(user_id, purpose, code_hash, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
                   (user_id, purpose, token_hash(code), expires.isoformat(), _utc_now().isoformat()))
    return expires


def verify_challenge(user_id: int, purpose: str, code: str) -> bool:
    with _connect() as db:
        row = db.execute("SELECT id, code_hash, expires_at, attempts FROM v2_challenges "
                         "WHERE user_id = ? AND purpose = ? AND consumed = 0 ORDER BY id DESC LIMIT 1",
                         (user_id, purpose)).fetchone()
        if not row or row["attempts"] >= 5 or row["expires_at"] <= _utc_now().isoformat():
            return False
        db.execute("UPDATE v2_challenges SET attempts = attempts + 1 WHERE id = ?", (row["id"],))
        valid = secrets.compare_digest(row["code_hash"], token_hash(code))
        if valid:
            db.execute("UPDATE v2_challenges SET consumed = 1 WHERE id = ?", (row["id"],))
        return valid


def update_password(user_id: int, password: str) -> None:
    with _connect() as db:
        db.execute("UPDATE v2_users SET password_hash = ? WHERE id = ?", (hash_password(password), user_id))
        db.execute("DELETE FROM v2_sessions WHERE user_id = ?", (user_id,))


def deliver_mail(recipient: str, subject: str, body: str) -> None:
    """
    development + V2_AUTH_DEV_MAIL=1 → локальна скринька v2_dev_mail (OTP відкритим текстом лише тут).
    Налаштований SMTP → лист.
    Інакше в release → MailNotConfigured (код не надсилається і ніде не зберігається).
    """
    if settings.dev_mail_enabled():
        with _connect() as db:
            db.executescript(_DEV_MAIL_SCHEMA)
            db.execute("INSERT INTO v2_dev_mail(recipient, subject, body, created_at) VALUES (?, ?, ?, ?)",
                       (recipient, subject, body, _utc_now().isoformat()))
        return
    smtp_host = os.environ.get("V2_SMTP_HOST")
    if not smtp_host:
        raise MailNotConfigured("Поштовий сервіс не налаштовано")
    message = EmailMessage()
    message["From"] = os.environ.get("V2_SMTP_FROM", "no-reply@localhost")
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(smtp_host, int(os.environ.get("V2_SMTP_PORT", "587")), timeout=10) as smtp:
            # STARTTLS обов'язковий: без нього (або з помилкою TLS) облікові дані й код не надсилаються.
            # Контекст перевіряє ланцюжок до довіреного CA і hostname V2_SMTP_HOST.
            smtp.starttls(context=smtp_tls_context())
            user = os.environ.get("V2_SMTP_USER")
            if user:
                smtp.login(user, os.environ.get("V2_SMTP_PASSWORD", ""))
            smtp.send_message(message)
    except (smtplib.SMTPException, ssl.SSLError, OSError) as error:
        # Подробиці (зокрема адресу сервера) не віддаємо клієнту; маршрут відповідає 503.
        raise MailDeliveryError("Не вдалося безпечно надіслати лист") from error


def smtp_tls_context() -> ssl.SSLContext:
    """TLS для SMTP: системні довірені CA, CERT_REQUIRED, check_hostname, мінімум TLS 1.2."""
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def latest_dev_mail(recipient: str | None = None) -> dict[str, Any] | None:
    """Лише development (dev-скринька). У release таблиці немає."""
    with _connect() as db:
        if "v2_dev_mail" not in _tables(db):
            return None
        row = db.execute("SELECT recipient, subject, body, created_at FROM v2_dev_mail "
                         + ("WHERE recipient = ? " if recipient else "") + "ORDER BY id DESC LIMIT 1",
                         ((recipient,) if recipient else ())).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Персональні спроби (S5: власник лише з сесії)
# ---------------------------------------------------------------------------

_ATTEMPT_COLUMNS = "id, assessment_id, assessment_name, status, answers_json, started_at, completed_at, updated_at"


def create_attempt(user_id: int, attempt_id: str, assessment_name: str, status: str, answers_json: str,
                   started_at: str, completed_at: str | None, assessment_id: str = "legacy") -> None:
    if status not in {"draft", "completed"}:
        raise ValueError("Непідтримуваний стан спроби")
    now = _utc_now().isoformat()
    with _connect() as db:
        existing = db.execute("SELECT user_id, status FROM v2_user_attempts WHERE id = ?", (attempt_id,)).fetchone()
        if existing and int(existing["user_id"]) != user_id:
            raise PermissionError("Спроба належить іншому користувачу")
        if existing and existing["status"] == "completed":
            raise ValueError("Завершену спробу не можна змінити")
        if existing:
            db.execute("UPDATE v2_user_attempts SET assessment_id = ?, assessment_name = ?, status = ?, answers_json = ?, "
                       "completed_at = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                       (assessment_id, assessment_name, status, answers_json, completed_at, now, attempt_id, user_id))
        else:
            db.execute(f"INSERT INTO v2_user_attempts({_ATTEMPT_COLUMNS.replace('id, ', 'id, user_id, ', 1)}) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (attempt_id, user_id, assessment_id, assessment_name, status, answers_json, started_at,
                        completed_at, now))


def list_attempts(user_id: int) -> list[dict[str, Any]]:
    with _connect() as db:
        rows = db.execute(f"SELECT {_ATTEMPT_COLUMNS} FROM v2_user_attempts WHERE user_id = ? ORDER BY started_at DESC",
                          (user_id,)).fetchall()
    return [dict(row) for row in rows]


def get_attempt(user_id: int, attempt_id: str) -> dict[str, Any] | None:
    with _connect() as db:
        row = db.execute(f"SELECT {_ATTEMPT_COLUMNS} FROM v2_user_attempts WHERE id = ? AND user_id = ?",
                         (attempt_id, user_id)).fetchone()
    return dict(row) if row else None


def complete_attempt(user_id: int, attempt_id: str, completed_at: str, answers_json: str | None = None) -> dict[str, Any]:
    now = _utc_now().isoformat()
    with _connect() as db:
        row = db.execute("SELECT id, status FROM v2_user_attempts WHERE id = ? AND user_id = ?",
                         (attempt_id, user_id)).fetchone()
        if row is None:
            raise LookupError("Спробу не знайдено")
        if row["status"] == "completed":
            raise ValueError("Тестування вже завершено")
        db.execute("UPDATE v2_user_attempts SET status = 'completed', answers_json = COALESCE(?, answers_json), "
                   "completed_at = ?, updated_at = ? WHERE id = ? AND user_id = ? AND status = 'draft'",
                   (answers_json, completed_at, now, attempt_id, user_id))
        result = db.execute(f"SELECT {_ATTEMPT_COLUMNS} FROM v2_user_attempts WHERE id = ? AND user_id = ?",
                            (attempt_id, user_id)).fetchone()
    return dict(result)
