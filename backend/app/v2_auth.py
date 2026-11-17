"""Ізольована авторизація Dashboard 2.0.

Цей модуль навмисно використовує окрему SQLite-базу, яку задає V2_AUTH_DB.
Він не читає і не змінює integrity.db/demo-dashboard.db та не змінює стару
демо-модель X-Role у /api.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import smtplib
import sqlite3
from email.message import EmailMessage
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

AUTH_DB_PATH = Path(os.environ.get("V2_AUTH_DB", Path(__file__).resolve().parent.parent / "v2_auth.db"))
SESSION_COOKIE = "v2_session"
CSRF_COOKIE = "v2_csrf"
SESSION_TTL_HOURS = 12
SECURE_COOKIE = os.environ.get("V2_AUTH_SECURE_COOKIE", "0") == "1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _connect() -> sqlite3.Connection:
    AUTH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(AUTH_DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def init_auth_db() -> None:
    with _connect() as db:
        db.executescript(
            """
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
            CREATE TABLE IF NOT EXISTS v2_dev_mail (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
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
        )
        columns = {row[1] for row in db.execute("PRAGMA table_info(v2_sessions)").fetchall()}
        if "two_factor_verified" not in columns:
            db.execute("ALTER TABLE v2_sessions ADD COLUMN two_factor_verified INTEGER NOT NULL DEFAULT 0")
        attempt_columns = {row[1] for row in db.execute("PRAGMA table_info(v2_user_attempts)").fetchall()}
        if "assessment_id" not in attempt_columns:
            db.execute("ALTER TABLE v2_user_attempts ADD COLUMN assessment_id TEXT NOT NULL DEFAULT 'legacy'")
        if "updated_at" not in attempt_columns:
            db.execute("ALTER TABLE v2_user_attempts ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def consume_rate_limit(scope: str, subject: str, limit: int, window_minutes: int) -> bool:
    """Record one attempt and return whether it is still within the limit."""
    now = _utc_now()
    with _connect() as db:
        row = db.execute(
            "SELECT window_started, attempts FROM v2_rate_limits WHERE scope = ? AND subject = ?",
            (scope, subject),
        ).fetchone()
        if row is None or datetime.fromisoformat(row["window_started"]) + timedelta(minutes=window_minutes) <= now:
            db.execute(
                "INSERT INTO v2_rate_limits(scope, subject, window_started, attempts) VALUES (?, ?, ?, 1) "
                "ON CONFLICT(scope, subject) DO UPDATE SET window_started=excluded.window_started, attempts=1",
                (scope, subject, now.isoformat()),
            )
            return True
        if int(row["attempts"]) >= limit:
            return False
        db.execute(
            "UPDATE v2_rate_limits SET attempts = attempts + 1 WHERE scope = ? AND subject = ?",
            (scope, subject),
        )
        return True


def clear_rate_limit(scope: str, subject: str) -> None:
    with _connect() as db:
        db.execute("DELETE FROM v2_rate_limits WHERE scope = ? AND subject = ?", (scope, subject))


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


def create_user(name: str, email: str, password: str, role: str = "user") -> dict[str, Any]:
    if role not in {"user", "admin"}:
        raise ValueError("Непідтримувана роль")
    now = _utc_now().isoformat()
    with _connect() as db:
        try:
            cursor = db.execute(
                "INSERT INTO v2_users(name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (name.strip(), normalize_email(email), hash_password(password), role, now),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("Користувач з таким email уже існує") from error
        row = db.execute("SELECT id, name, email, role FROM v2_users WHERE id = ?", (cursor.lastrowid,)).fetchone()
        assert row is not None
        return public_user(row)


def authenticate(email: str, password: str) -> dict[str, Any] | None:
    with _connect() as db:
        row = db.execute("SELECT * FROM v2_users WHERE email = ?", (normalize_email(email),)).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        return None
    return public_user(row)


def create_session(user_id: int) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires = _utc_now() + timedelta(hours=SESSION_TTL_HOURS)
    with _connect() as db:
        db.execute("DELETE FROM v2_sessions WHERE expires_at <= ?", (_utc_now().isoformat(),))
        db.execute(
            "INSERT INTO v2_sessions(user_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (user_id, hashlib.sha256(token.encode()).hexdigest(), expires.isoformat(), _utc_now().isoformat()),
        )
    return token, expires


def user_for_session(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    with _connect() as db:
        row = db.execute(
            "SELECT u.id, u.name, u.email, u.role, s.two_factor_verified FROM v2_sessions s JOIN v2_users u ON u.id = s.user_id "
            "WHERE s.token_hash = ? AND s.expires_at > ?",
            (hashlib.sha256(token.encode()).hexdigest(), _utc_now().isoformat()),
        ).fetchone()
    if not row:
        return None
    user = public_user(row)
    user["two_factor_verified"] = bool(row["two_factor_verified"])
    return user


def verify_session_2fa(token: str | None) -> None:
    if not token:
        return
    with _connect() as db:
        db.execute("UPDATE v2_sessions SET two_factor_verified = 1 WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))


def issue_challenge(user_id: int, purpose: str, recipient: str) -> tuple[str, datetime]:
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = _utc_now() + timedelta(minutes=10)
    with _connect() as db:
        db.execute("UPDATE v2_challenges SET consumed = 1 WHERE user_id = ? AND purpose = ? AND consumed = 0", (user_id, purpose))
        db.execute("INSERT INTO v2_challenges(user_id, purpose, code_hash, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
                   (user_id, purpose, hashlib.sha256(code.encode()).hexdigest(), expires.isoformat(), _utc_now().isoformat()))
    subject = "Integrity Dashboard V2: код підтвердження"
    if purpose == "password_reset":
        subject = "Integrity Dashboard V2: скидання паролю"
    body = f"Ваш код: {code}. Код дійсний 10 хвилин."
    deliver_mail(recipient, subject, body)
    return code, expires


def verify_challenge(user_id: int, purpose: str, code: str) -> bool:
    with _connect() as db:
        row = db.execute("SELECT id, code_hash, expires_at, attempts FROM v2_challenges WHERE user_id = ? AND purpose = ? AND consumed = 0 ORDER BY id DESC LIMIT 1", (user_id, purpose)).fetchone()
        if not row or row["attempts"] >= 5 or row["expires_at"] <= _utc_now().isoformat():
            return False
        db.execute("UPDATE v2_challenges SET attempts = attempts + 1 WHERE id = ?", (row["id"],))
        valid = secrets.compare_digest(row["code_hash"], hashlib.sha256(code.encode()).hexdigest())
        if valid:
            db.execute("UPDATE v2_challenges SET consumed = 1 WHERE id = ?", (row["id"],))
        return valid


def update_password(user_id: int, password: str) -> None:
    with _connect() as db:
        db.execute("UPDATE v2_users SET password_hash = ? WHERE id = ?", (hash_password(password), user_id))
        db.execute("DELETE FROM v2_sessions WHERE user_id = ?", (user_id,))


def deliver_mail(recipient: str, subject: str, body: str) -> None:
    """SMTP is opt-in; otherwise retain a local outbox for safe development."""
    with _connect() as db:
        db.execute("INSERT INTO v2_dev_mail(recipient, subject, body, created_at) VALUES (?, ?, ?, ?)", (recipient, subject, body, _utc_now().isoformat()))
    smtp_host = os.environ.get("V2_SMTP_HOST")
    if not smtp_host:
        print(f"[V2 DEV MAIL] to={recipient} subject={subject} body={body}")
        return
    message = EmailMessage()
    message["From"] = os.environ.get("V2_SMTP_FROM", "no-reply@localhost")
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(smtp_host, int(os.environ.get("V2_SMTP_PORT", "587")), timeout=10) as smtp:
        smtp.starttls()
        smtp.login(os.environ["V2_SMTP_USER"], os.environ["V2_SMTP_PASSWORD"])
        smtp.send_message(message)


def latest_dev_mail(recipient: str | None = None) -> dict[str, Any] | None:
    with _connect() as db:
        row = db.execute("SELECT recipient, subject, body, created_at FROM v2_dev_mail " + ("WHERE recipient = ? " if recipient else "") + "ORDER BY id DESC LIMIT 1", ((recipient,) if recipient else ())).fetchone()
    return dict(row) if row else None


def delete_session(token: str | None) -> None:
    if not token:
        return
    with _connect() as db:
        db.execute("DELETE FROM v2_sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))


def create_attempt(
    user_id: int,
    attempt_id: str,
    assessment_name: str,
    status: str,
    answers_json: str,
    started_at: str,
    completed_at: str | None,
    assessment_id: str = "legacy",
) -> None:
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
            db.execute(
                "UPDATE v2_user_attempts SET assessment_id = ?, assessment_name = ?, status = ?, answers_json = ?, "
                "completed_at = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (assessment_id, assessment_name, status, answers_json, completed_at, now, attempt_id, user_id),
            )
        else:
            db.execute(
                "INSERT INTO v2_user_attempts(id, user_id, assessment_id, assessment_name, status, answers_json, started_at, completed_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (attempt_id, user_id, assessment_id, assessment_name, status, answers_json, started_at, completed_at, now),
            )


def list_attempts(user_id: int) -> list[dict[str, Any]]:
    with _connect() as db:
        rows = db.execute(
            "SELECT id, assessment_id, assessment_name, status, answers_json, started_at, completed_at, updated_at FROM v2_user_attempts "
            "WHERE user_id = ? ORDER BY started_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_attempt(user_id: int, attempt_id: str) -> dict[str, Any] | None:
    with _connect() as db:
        row = db.execute(
            "SELECT id, assessment_id, assessment_name, status, answers_json, started_at, completed_at, updated_at "
            "FROM v2_user_attempts WHERE id = ? AND user_id = ?",
            (attempt_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def complete_attempt(user_id: int, attempt_id: str, completed_at: str, answers_json: str | None = None) -> dict[str, Any]:
    now = _utc_now().isoformat()
    with _connect() as db:
        row = db.execute(
            "SELECT id, status FROM v2_user_attempts WHERE id = ? AND user_id = ?",
            (attempt_id, user_id),
        ).fetchone()
        if row is None:
            raise LookupError("Спробу не знайдено")
        if row["status"] == "completed":
            raise ValueError("Тестування вже завершено")
        db.execute(
            "UPDATE v2_user_attempts SET status = 'completed', answers_json = COALESCE(?, answers_json), completed_at = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ? AND status = 'draft'",
            (answers_json, completed_at, now, attempt_id, user_id),
        )
        result = db.execute(
            "SELECT id, assessment_id, assessment_name, status, answers_json, started_at, completed_at, updated_at "
            "FROM v2_user_attempts WHERE id = ? AND user_id = ?",
            (attempt_id, user_id),
        ).fetchone()
    assert result is not None
    return dict(result)
