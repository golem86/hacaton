"""Сховище ідентичності й персонального контуру Dashboard V2 (V2_AUTH_DB).

Окрема SQLite-база: акаунти, сесії, OTP-виклики, ліміти спроб, журнал змін ролей і персональні спроби.
Анонімних відповідей тут немає і бути не може — вони лише в INTEGRITY_DB (Survey API).

Що змінено відносно прототипу (V2 Integration Contract) і за аудитом (docs/V2_HARDENING_CONTRACT.md):
  - схема версіонується через PRAGMA user_version (MIG-4); версія 2 додає роль data_officer
    і append-only журнал v2_role_changes; код ніколи не знижує версію і відмовляє на новішій;
  - сесія ротується після 2FA (S7) лише в тій самій транзакції, що й споживання коду,
    і лише якщо pending-сесія ще існує (гонка не «воскрешає» відкликані сесії);
  - кожна зміна стану автентифікації — одна транзакція BEGIN IMMEDIATE на одному з'єднанні;
  - OTP зберігається як HMAC-SHA256(V2_SECRET_KEY, "otp:{purpose}:{user_id}:{code}");
  - scrypt N=2^17, r=8, p=1; старі хеші переобчислюються після успішного входу;
  - dev-скринька з OTP існує лише в режимі development (S3);
  - імена cookie з префіксом __Host- у режимі Secure (S8, CSRF 3.0).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import smtplib
import sqlite3
import ssl
import threading
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from pathlib import Path
from typing import Any, Iterator

from . import settings

AUTH_SCHEMA_VERSION = 2
ROLES = ("user", "admin", "data_officer")
# Ролі, які призначає й знімає лише власник сервера (app.v2_role_cli), і код відмови для веб-зміни (403).
# Порядок важливий: зміна admin ↔ data_officer відхиляється кодом admin_role_server_only.
SERVER_ONLY_ROLE_ERRORS = {"admin": "admin_role_server_only", "data_officer": "data_officer_role_server_only"}
# Актор серверної команди app.v2_role_cli у v2_role_changes.actor_user_id: колонка NOT NULL без FK і CHECK,
# id користувачів починаються з 1 (AUTOINCREMENT), тож 0 ні з ким не збігається і означає «власник сервера».
SERVER_ACTOR_ID = 0

SESSION_TTL_HOURS = 12                 # verified-сесія після 2FA: абсолютний строк
PENDING_SESSION_TTL_MINUTES = 15       # pending-сесія між паролем і 2FA
OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5                   # перевірок коду на один challenge (навіть за паралельних запитів)
ACCOUNT_WINDOW_MINUTES = 24 * 60
TWO_FACTOR_FAIL_LIMIT = 10             # невдалих кодів 2FA на акаунт за 24 год → блокування (429)
RESET_FAIL_LIMIT = 10                  # невдалих підтверджень скидання на акаунт за 24 год
RESET_ISSUE_LIMIT = 5                  # кодів скидання на акаунт за 24 год
BUSY_TIMEOUT_MS = 5000

# scrypt (A9). Пам'ять одного обчислення ≈ 128 * r * N = 128 MiB, тому одночасних обчислень не більше
# SCRYPT_MAX_CONCURRENCY — інакше хвиля входів вичерпала б пам'ять сервера.
SCRYPT_N = 2 ** 17
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAXMEM = 256 * 1024 * 1024
SCRYPT_MAX_CONCURRENCY = 4
_SCRYPT_SLOTS = threading.BoundedSemaphore(SCRYPT_MAX_CONCURRENCY)

_FAIL_2FA_SCOPE = "2fa_fail"
_FAIL_RESET_SCOPE = "reset_fail"


class MailNotConfigured(RuntimeError):
    """У release немає SMTP — надіслати код неможливо (відкрите питання №5: провайдер)."""


class MailDeliveryError(RuntimeError):
    """SMTP недоступний або не пройшов перевірку TLS — лист не надіслано, код не збережено."""


class AuthMigrationError(RuntimeError):
    """Міграцію V2_AUTH_DB не виконано; база лишилась без змін."""


class AuthDatabaseBusy(RuntimeError):
    """V2_AUTH_DB зайнята довше за busy_timeout. Маршрути відповідають 503, а не 500."""


class SessionRevoked(LookupError):
    """Pending-сесії вже немає (вихід, скидання пароля, зміна ролі): нову сесію не видано."""


class TwoFactorLocked(RuntimeError):
    """Ліміт невдалих кодів 2FA на акаунт вичерпано: verify, resend і видача коду під час входу — 429."""


class AdminExists(RuntimeError):
    """Адміністратор уже існує; додатковий створюється лише явним рішенням (--allow-additional-admin)."""


class RoleChangeError(ValueError):
    """Зміна ролі або відкликання сесій відхилені. code: self_change, not_found, conflict, actor_unauthorized,
    invalid_role, admin_role_server_only (роль admin у вебі не призначається й не знімається; сесії іншого
    admin у вебі не завершуються), data_officer_role_server_only (те саме для ролі data_officer),
    unchanged і last_admin (лише серверна команда app.v2_role_cli)."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


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
    connection.execute(f"PRAGMA busy_timeout = {int(BUSY_TIMEOUT_MS)}")
    return connection


def is_busy_error(error: BaseException) -> bool:
    """SQLITE_BUSY / SQLITE_LOCKED (у т.ч. розширені коди) — БД зайнята іншою транзакцією."""
    if not isinstance(error, sqlite3.OperationalError):
        return False
    code = getattr(error, "sqlite_errorcode", None)
    if code is not None:
        return code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
    message = str(error).lower()
    return "locked" in message or "busy" in message


@contextmanager
def _immediate() -> Iterator[sqlite3.Connection]:
    """
    Одна транзакція BEGIN IMMEDIATE на одному з'єднанні: блокування запису береться ДО першого читання,
    тож перевірка й зміна стану не перемежовуються з іншими записами. Успіх → COMMIT; будь-яка помилка
    (зокрема свідома відмова всередині блоку) → ROLLBACK. Зайнята БД → AuthDatabaseBusy.
    """
    db = _connect()
    db.isolation_level = None
    try:
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        db.execute("COMMIT")
    except sqlite3.OperationalError as error:
        if is_busy_error(error):
            raise AuthDatabaseBusy("V2_AUTH_DB тимчасово зайнята") from error
        raise
    finally:
        db.close()


@contextmanager
def _reader() -> Iterator[sqlite3.Connection]:
    """З'єднання для читання; закривається одразу; зайнята БД → AuthDatabaseBusy."""
    db = _connect()
    try:
        yield db
    except sqlite3.OperationalError as error:
        if is_busy_error(error):
            raise AuthDatabaseBusy("V2_AUTH_DB тимчасово зайнята") from error
        raise
    finally:
        db.close()


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
    role TEXT NOT NULL CHECK (role IN ('user', 'admin', 'data_officer')),
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
CREATE TABLE IF NOT EXISTS v2_role_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_user_id INTEGER NOT NULL,
    target_user_id INTEGER NOT NULL,
    old_role TEXT NOT NULL CHECK (old_role IN ('user', 'admin', 'data_officer')),
    new_role TEXT NOT NULL CHECK (new_role IN ('user', 'admin', 'data_officer')),
    changed_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS v2_role_changes_no_update BEFORE UPDATE ON v2_role_changes
BEGIN
    SELECT RAISE(ABORT, 'v2_role_changes is append-only');
END;
CREATE TRIGGER IF NOT EXISTS v2_role_changes_no_delete BEFORE DELETE ON v2_role_changes
BEGIN
    SELECT RAISE(ABORT, 'v2_role_changes is append-only');
END;
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

_COUNTED_TABLES = ("v2_users", "v2_sessions", "v2_user_attempts", "v2_challenges", "v2_rate_limits")
REQUIRED_TABLES = _COUNTED_TABLES + ("v2_role_changes",)
APPEND_ONLY_TRIGGERS = {"v2_role_changes_no_update": "UPDATE", "v2_role_changes_no_delete": "DELETE"}
_SCHEMA1_USERS = "_v2_users_schema1"


def _statements(script: str) -> list[str]:
    """Розбиває SQL-скрипт на інструкції (з урахуванням тіл тригерів BEGIN … END)."""
    statements, buffer = [], ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        raise ValueError("Незавершена SQL-інструкція в схемі")
    return statements


def _create_statement(name: str) -> str:
    return next(s for s in _statements(_SCHEMA) if s.split("(", 1)[0].split()[-1] == name)


def _tables(db: sqlite3.Connection) -> set[str]:
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _user_version(db: sqlite3.Connection) -> int:
    return int(db.execute("PRAGMA user_version").fetchone()[0])


def _counts(db: sqlite3.Connection, tables: set[str]) -> dict[str, int]:
    return {t: db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in _COUNTED_TABLES if t in tables}


def auth_schema_version() -> int:
    with _reader() as db:
        return _user_version(db)


def schema_problems(db: sqlite3.Connection) -> list[str]:
    """Структурні розбіжності з auth schema 2: таблиці, колонки, CHECK ролей, append-only тригери."""
    problems = []
    tables = _tables(db)
    missing = [t for t in REQUIRED_TABLES if t not in tables]
    if missing:
        problems.append(f"відсутні таблиці: {', '.join(missing)}")
    columns = {
        "v2_sessions": {"two_factor_verified"},
        "v2_user_attempts": {"assessment_id", "updated_at"},
        "v2_role_changes": {"actor_user_id", "target_user_id", "old_role", "new_role", "changed_at"},
    }
    for table, required in columns.items():
        if table in tables:
            present = {r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}
            if required - present:
                problems.append(f"{table}: відсутні колонки {', '.join(sorted(required - present))}")
    users_sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='v2_users'").fetchone()
    if users_sql is not None and "'data_officer'" not in (users_sql[0] or ""):
        problems.append("v2_users.role CHECK не містить data_officer")
    triggers = {r[0]: (r[1] or "").upper() for r in db.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name='v2_role_changes'")}
    for name, event in APPEND_ONLY_TRIGGERS.items():
        sql = " ".join(triggers.get(name, "").split())
        if f"BEFORE {event} ON V2_ROLE_CHANGES" not in sql or "RAISE(ABORT" not in sql:
            problems.append(f"немає append-only тригера {name}")
    return problems


def _backup(db: sqlite3.Connection, version: int) -> Path:
    """
    Резервна копія ПЕРЕД міграцією (SQLite backup API) з перевіркою самої копії:
    integrity_check = ok, та сама user_version і та сама кількість рядків. Інакше міграція не починається.
    """
    path = auth_db_path()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = path.with_name(f"{path.stem}.backup-{stamp}{path.suffix}")
    source_counts = _counts(db, _tables(db))
    with closing(sqlite3.connect(target)) as dst:
        db.backup(dst)
    with closing(sqlite3.connect(f"{target.resolve().as_uri()}?mode=ro", uri=True)) as copy:
        integrity = copy.execute("PRAGMA integrity_check").fetchone()[0]
        copy_version = _user_version(copy)
        copy_counts = _counts(copy, _tables(copy))
    if integrity != "ok" or copy_version != version or copy_counts != source_counts:
        raise AuthMigrationError(f"Резервна копія V2_AUTH_DB не пройшла перевірку ({target}); міграцію не виконано")
    return target


def migrate_auth_db() -> dict[str, Any]:
    """
    Доводить V2_AUTH_DB до AUTH_SCHEMA_VERSION (у release — лише явною командою
    python -m app.migrations --apply --confirm-verified-backup).
      - версія новіша за підтримувану → AuthMigrationError, БД і каталог не змінюються;
      - порожня БД: схема створюється в одній транзакції, версія 2;
      - БД версій 0 (прототип) і 1: перевірена резервна копія → одна транзакція (перебудова v2_users з
        роллю data_officer, v2_role_changes з append-only тригерами, відсутні колонки прототипу) →
        перевірка кількості рядків, foreign_key_check, integrity_check → версія 2; при помилці відкат;
      - актуальна БД: нічого не змінюється. Версія ніколи не знижується.
    """
    report: dict[str, Any] = {"action": "up_to_date", "backup": None}
    db = _connect()
    try:
        version = _user_version(db)
        if version > AUTH_SCHEMA_VERSION:
            raise AuthMigrationError(
                f"V2_AUTH_DB має версію {version}, новішу за підтримувану {AUTH_SCHEMA_VERSION}; "
                "міграцію відхилено без змін")
        existing = _tables(db)
        if not existing & set(_COUNTED_TABLES):
            db.executescript(f"BEGIN IMMEDIATE;\n{_SCHEMA}\nPRAGMA user_version = {AUTH_SCHEMA_VERSION};\nCOMMIT;")
            report["action"] = "created"
        elif version < AUTH_SCHEMA_VERSION:
            report.update(_migrate_to_current(db, version))
        if settings.dev_mail_enabled():
            db.executescript(_DEV_MAIL_SCHEMA)
    finally:
        db.close()
    return report


def _migrate_to_current(db: sqlite3.Connection, version: int) -> dict[str, Any]:
    backup = _backup(db, version)
    db.isolation_level = None
    db.execute("PRAGMA foreign_keys = OFF")          # перебудова таблиці за процедурою SQLite
    db.execute("PRAGMA legacy_alter_table = ON")     # RENAME не переписує REFERENCES інших таблиць
    try:
        if db.execute("PRAGMA foreign_keys").fetchone()[0] != 0:
            raise AuthMigrationError("не вдалося вимкнути foreign_keys для перебудови")
        db.execute("BEGIN IMMEDIATE")
        try:
            existing = _tables(db)
            before = _counts(db, existing)
            with closing(sqlite3.connect(f"{backup.resolve().as_uri()}?mode=ro", uri=True)) as copy:
                if _counts(copy, _tables(copy)) != before:
                    raise AuthMigrationError("БД змінилась після резервної копії")
            if "v2_users" in existing:
                _rebuild_users(db)
            for statement in _statements(_SCHEMA):     # відсутні таблиці прототипу, v2_role_changes, тригери
                db.execute(statement)
            columns = {r[1] for r in db.execute("PRAGMA table_info(v2_sessions)")}
            if "two_factor_verified" not in columns:
                db.execute("ALTER TABLE v2_sessions ADD COLUMN two_factor_verified INTEGER NOT NULL DEFAULT 0")
            columns = {r[1] for r in db.execute("PRAGMA table_info(v2_user_attempts)")}
            if "assessment_id" not in columns:
                db.execute("ALTER TABLE v2_user_attempts ADD COLUMN assessment_id TEXT NOT NULL DEFAULT 'legacy'")
            if "updated_at" not in columns:
                db.execute("ALTER TABLE v2_user_attempts ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")
            after = _counts(db, set(before))
            problems = [f"{t}: {before[t]} → {after[t]}" for t in before if before[t] != after[t]]
            if db.execute("PRAGMA foreign_key_check").fetchall():
                problems.append("порушено зовнішні ключі")
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                problems.append("integrity_check не ok")
            problems.extend(schema_problems(db))
            if problems:
                raise AuthMigrationError("; ".join(problems))
            db.execute(f"PRAGMA user_version = {AUTH_SCHEMA_VERSION}")
            db.execute("COMMIT")
        except Exception as exc:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise AuthMigrationError(f"Міграцію V2_AUTH_DB відкочено: {exc}. Копія: {backup}") from exc
    finally:
        db.execute("PRAGMA legacy_alter_table = OFF")
        db.execute("PRAGMA foreign_keys = ON")
    return {"action": "migrated", "backup": str(backup), "from_version": version, "rows": before}


def _rebuild_users(db: sqlite3.Connection) -> None:
    """
    v2_users з CHECK (role IN ('user','admin')) → з data_officer. Стару таблицю перейменовано, нову створено
    тим самим DDL, що й у свіжій БД (sqlite_master однаковий), рядки й лічильник AUTOINCREMENT перенесено.
    Викликається лише всередині транзакції з foreign_keys=OFF і legacy_alter_table=ON.
    """
    sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='v2_users'").fetchone()[0] or ""
    if "'data_officer'" in sql:
        return
    sequence = db.execute("SELECT seq FROM sqlite_sequence WHERE name = 'v2_users'").fetchone() \
        if "sqlite_sequence" in _tables(db) else None
    db.execute(f"ALTER TABLE v2_users RENAME TO {_SCHEMA1_USERS}")
    db.execute(_create_statement("v2_users"))
    db.execute("INSERT INTO v2_users(id, name, email, password_hash, role, created_at) "
               f"SELECT id, name, email, password_hash, role, created_at FROM {_SCHEMA1_USERS}")
    db.execute(f"DROP TABLE {_SCHEMA1_USERS}")
    if sequence is not None:                         # id видалених акаунтів не перевикористовуються
        updated = db.execute("UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = 'v2_users'",
                             (sequence[0],)).rowcount
        if not updated:
            db.execute("INSERT INTO sqlite_sequence(name, seq) VALUES ('v2_users', ?)", (sequence[0],))


def check_auth_schema() -> None:
    """MIG-1 для release: лише перевірка (read-only), без змін і без створення файлу."""
    path = auth_db_path()
    if not path.exists():
        raise RuntimeError(f"V2_AUTH_DB не знайдено ({path}); створіть її явною міграцією")
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        version = _user_version(db)
        if version != AUTH_SCHEMA_VERSION:
            raise RuntimeError(f"V2_AUTH_DB має версію {version}, очікується {AUTH_SCHEMA_VERSION}; "
                               "виконайте явну міграцію після перевіреної резервної копії")
        problems = schema_problems(db)
    if problems:
        raise RuntimeError(f"Схема V2_AUTH_DB не відповідає версії {AUTH_SCHEMA_VERSION}: " + "; ".join(problems))


def init_auth_db() -> None:
    """development: створення/міграція; release: лише перевірка схеми (міграція — явною командою)."""
    if settings.auto_migrate():
        migrate_auth_db()
    else:
        check_auth_schema()


# ---------------------------------------------------------------------------
# Ліміти спроб (вікно від першої спроби; рахунок і рішення — в одній транзакції)
# ---------------------------------------------------------------------------

def _window_count(db: sqlite3.Connection, scope: str, subject: str, window_minutes: int, now: datetime) -> int:
    row = db.execute("SELECT window_started, attempts FROM v2_rate_limits WHERE scope = ? AND subject = ?",
                     (scope, subject)).fetchone()
    if row is None or datetime.fromisoformat(row["window_started"]) + timedelta(minutes=window_minutes) <= now:
        return 0
    return int(row["attempts"])


def _consume(db: sqlite3.Connection, scope: str, subject: str, limit: int, window_minutes: int,
             now: datetime) -> bool:
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


def consume_rate_limit(scope: str, subject: str, limit: int, window_minutes: int) -> bool:
    """Атомарно зараховує спробу і повертає, чи вона ще в межах ліміту (BEGIN IMMEDIATE)."""
    with _immediate() as db:
        return _consume(db, scope, subject, limit, window_minutes, _utc_now())


def is_rate_limited(scope: str, subject: str, limit: int, window_minutes: int) -> bool:
    """Перевіряє ліміт БЕЗ зарахування спроби (для лічильників лише невдалих спроб)."""
    with _reader() as db:
        return _window_count(db, scope, subject, window_minutes, _utc_now()) >= limit


def clear_rate_limit(scope: str, subject: str) -> None:
    with _immediate() as db:
        db.execute("DELETE FROM v2_rate_limits WHERE scope = ? AND subject = ?", (scope, subject))


def two_factor_locked(user_id: int) -> bool:
    return is_rate_limited(_FAIL_2FA_SCOPE, str(user_id), TWO_FACTOR_FAIL_LIMIT, ACCOUNT_WINDOW_MINUTES)


# ---------------------------------------------------------------------------
# Користувачі й паролі
# ---------------------------------------------------------------------------

def normalize_email(email: str) -> str:
    return email.strip().lower()


def mask_email(email: str) -> str:
    """j***@e***.test — для списків адміністратора без повних адрес."""
    local, _, domain = email.partition("@")
    host, dot, tld = domain.rpartition(".")
    masked_domain = f"{host[:1]}***{dot}{tld}" if host else f"{domain[:1]}***"
    return f"{local[:1]}***@{masked_domain}"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int, dklen: int = 64) -> bytes:
    with _SCRYPT_SLOTS:
        return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=SCRYPT_MAXMEM, dklen=dklen)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    n, r, p = SCRYPT_N, SCRYPT_R, SCRYPT_P
    return f"scrypt${n}${r}${p}${_b64(salt)}${_b64(_scrypt(password, salt, n, r, p))}"


def _scrypt_params(encoded: str) -> tuple[int, int, int] | None:
    try:
        algorithm, n, r, p, _salt, _digest = encoded.split("$", 5)
        return (int(n), int(r), int(p)) if algorithm == "scrypt" else None
    except (ValueError, AttributeError):
        return None


def needs_rehash(encoded: str) -> bool:
    return _scrypt_params(encoded) != (SCRYPT_N, SCRYPT_R, SCRYPT_P)


def verify_password(password: str, encoded: str) -> bool:
    """Параметри scrypt читаються з рядка хешу (старі хеші N=2^14 перевіряються як є)."""
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        expected_bytes = _unb64(expected)
        actual = _scrypt(password, _unb64(salt), int(n), int(r), int(p), dklen=len(expected_bytes))
        return hmac.compare_digest(actual, expected_bytes)
    except (ValueError, TypeError, MemoryError):
        return False


def equalize_password_work(password: str) -> None:
    """A6: фіктивне scrypt з поточними параметрами, коли справжнє не виконується (невідомий/наявний email)."""
    _scrypt(password, secrets.token_bytes(16), SCRYPT_N, SCRYPT_R, SCRYPT_P)


def public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return {"id": int(row["id"]), "name": row["name"], "email": row["email"], "role": row["role"]}


def user_exists(email: str) -> bool:
    with _reader() as db:
        return db.execute("SELECT 1 FROM v2_users WHERE email = ?", (normalize_email(email),)).fetchone() is not None


def find_user_id(email: str) -> int | None:
    with _reader() as db:
        row = db.execute("SELECT id FROM v2_users WHERE email = ?", (normalize_email(email),)).fetchone()
    return int(row[0]) if row else None


def admin_exists() -> bool:
    with _reader() as db:
        return db.execute("SELECT 1 FROM v2_users WHERE role = 'admin' LIMIT 1").fetchone() is not None


def create_user(name: str, email: str, password: str, role: str = "user",
                require_no_admin: bool = False) -> dict[str, Any]:
    """require_no_admin: перевірка «адміністратора ще немає» і створення — в одній транзакції."""
    if role not in ROLES:
        raise ValueError("Непідтримувана роль")
    encoded = hash_password(password)
    now = _utc_now().isoformat()
    try:
        with _immediate() as db:
            if require_no_admin and db.execute("SELECT 1 FROM v2_users WHERE role = 'admin' LIMIT 1").fetchone():
                raise AdminExists("Адміністратор уже існує")
            cursor = db.execute(
                "INSERT INTO v2_users(name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (name.strip(), normalize_email(email), encoded, role, now))
            row = db.execute("SELECT id, name, email, role FROM v2_users WHERE id = ?", (cursor.lastrowid,)).fetchone()
    except sqlite3.IntegrityError as error:
        raise ValueError("Користувач з таким email уже існує") from error
    return public_user(row)


def register_user(name: str, email: str, password: str) -> None:
    """
    Самореєстрація (S9, A6): роль завжди user; scrypt і запис виконуються однаково для нового
    й наявного email (INSERT … ON CONFLICT DO NOTHING), тож ні відповідь, ні час не розкривають акаунт.
    """
    encoded = hash_password(password)
    with _immediate() as db:
        db.execute("INSERT INTO v2_users(name, email, password_hash, role, created_at) VALUES (?, ?, ?, 'user', ?) "
                   "ON CONFLICT DO NOTHING", (name.strip(), normalize_email(email), encoded, _utc_now().isoformat()))


def authenticate(email: str, password: str) -> dict[str, Any] | None:
    """
    A6: для невідомого email виконується фіктивне scrypt з тими самими параметрами.
    A9: хеш зі старими параметрами перевіряється за параметрами з рядка; після успіху — переобчислюється,
    після невдачі — додається фіктивне обчислення з поточними параметрами (час не залежить від віку хешу).
    """
    with _reader() as db:
        row = db.execute("SELECT id, name, email, role, password_hash FROM v2_users WHERE email = ?",
                         (normalize_email(email),)).fetchone()
    if row is None:
        equalize_password_work(password)
        return None
    encoded = row["password_hash"]
    outdated = needs_rehash(encoded)
    if not verify_password(password, encoded):
        if outdated:
            equalize_password_work(password)
        return None
    if outdated:
        upgraded = hash_password(password)
        with _immediate() as db:     # умова password_hash = old: не перезаписує паралельне скидання пароля
            db.execute("UPDATE v2_users SET password_hash = ? WHERE id = ? AND password_hash = ?",
                       (upgraded, row["id"], encoded))
    return public_user(row)


def list_users(limit: int = 500) -> list[dict[str, Any]]:
    with _reader() as db:
        rows = db.execute("SELECT id, name, email, role, created_at FROM v2_users ORDER BY id LIMIT ?",
                          (limit,)).fetchall()
    return [{"id": int(r["id"]), "name": r["name"], "role": r["role"], "email_masked": mask_email(r["email"]),
             "created_at": r["created_at"]} for r in rows]


def find_user_by_email(email: str) -> dict[str, Any] | None:
    with _reader() as db:
        row = db.execute("SELECT id, name, email, role, created_at FROM v2_users WHERE email = ?",
                         (normalize_email(email),)).fetchone()
    return {**public_user(row), "created_at": row["created_at"]} if row else None


# ---------------------------------------------------------------------------
# Сесії
# ---------------------------------------------------------------------------

def _session_expiry(now: datetime, two_factor_verified: bool) -> datetime:
    return now + (timedelta(hours=SESSION_TTL_HOURS) if two_factor_verified
                  else timedelta(minutes=PENDING_SESSION_TTL_MINUTES))


def _insert_session(db: sqlite3.Connection, user_id: int, two_factor_verified: bool,
                    now: datetime) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires = _session_expiry(now, two_factor_verified)
    db.execute("DELETE FROM v2_sessions WHERE expires_at <= ?", (now.isoformat(),))
    db.execute("INSERT INTO v2_sessions(user_id, token_hash, expires_at, created_at, two_factor_verified) "
               "VALUES (?, ?, ?, ?, ?)",
               (user_id, token_hash(token), expires.isoformat(), now.isoformat(), int(two_factor_verified)))
    return token, expires


# Активна сесія: не прострочена; pending — ще й не старша за 15 хв від створення (діє і для pending-сесій,
# виданих до оновлення з 12-годинним строком).
_ACTIVE_SESSION = "s.expires_at > ? AND (s.two_factor_verified = 1 OR s.created_at > ?)"


def _active_args(now: datetime) -> tuple[str, str]:
    return now.isoformat(), (now - timedelta(minutes=PENDING_SESSION_TTL_MINUTES)).isoformat()


def create_session(user_id: int, two_factor_verified: bool = False) -> tuple[str, datetime]:
    with _immediate() as db:
        return _insert_session(db, user_id, two_factor_verified, _utc_now())


def user_for_session(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    with _reader() as db:
        row = db.execute(
            "SELECT u.id, u.name, u.email, u.role, s.two_factor_verified FROM v2_sessions s "
            f"JOIN v2_users u ON u.id = s.user_id WHERE s.token_hash = ? AND {_ACTIVE_SESSION}",
            (token_hash(token), *_active_args(_utc_now()))).fetchone()
    if not row:
        return None
    user = public_user(row)
    user["two_factor_verified"] = bool(row["two_factor_verified"])
    return user


def rotate_session_after_2fa(old_token: str, user_id: int) -> tuple[str, datetime]:
    """
    S7: новий токен замість pending — лише якщо pending-сесія цього користувача ще існує
    (DELETE з rowcount = 1 і INSERT в одній транзакції). Інакше SessionRevoked і нічого не видано.
    """
    now = _utc_now()
    with _immediate() as db:
        deleted = db.execute(
            f"DELETE FROM v2_sessions AS s WHERE s.token_hash = ? AND s.user_id = ? AND s.two_factor_verified = 0 "
            f"AND {_ACTIVE_SESSION}", (token_hash(old_token or ""), user_id, *_active_args(now))).rowcount
        if deleted != 1:
            raise SessionRevoked("Pending-сесії немає: нову сесію не видано")
        return _insert_session(db, user_id, True, now)


def delete_session(token: str | None) -> dict[str, Any] | None:
    """Видаляє одну сесію; повертає {id, role, two_factor_verified} її власника або None."""
    if not token:
        return None
    with _immediate() as db:
        row = db.execute("SELECT s.id, s.user_id, s.two_factor_verified, u.role FROM v2_sessions s "
                         "JOIN v2_users u ON u.id = s.user_id WHERE s.token_hash = ?", (token_hash(token),)).fetchone()
        if row is None:
            return None
        db.execute("DELETE FROM v2_sessions WHERE id = ?", (row["id"],))
    return {"id": int(row["user_id"]), "role": row["role"], "two_factor_verified": bool(row["two_factor_verified"])}


def _revoke_all(db: sqlite3.Connection, user_id: int) -> int:
    """Усі сесії користувача (включно з pending) і відкриті коди 2FA — у поточній транзакції."""
    revoked = db.execute("DELETE FROM v2_sessions WHERE user_id = ?", (user_id,)).rowcount
    db.execute("UPDATE v2_challenges SET consumed = 1 WHERE user_id = ? AND purpose = 'login_2fa' AND consumed = 0",
               (user_id,))
    return revoked


def logout_all(token: str | None) -> dict[str, Any] | None:
    """Вихід з усіх пристроїв: сесія-ініціатор (з 2FA) і всі інші сесії власника — одна транзакція."""
    if not token:
        return None
    now = _utc_now()
    with _immediate() as db:
        row = db.execute(
            "SELECT s.user_id, u.role FROM v2_sessions s JOIN v2_users u ON u.id = s.user_id "
            f"WHERE s.token_hash = ? AND s.two_factor_verified = 1 AND {_ACTIVE_SESSION}",
            (token_hash(token), *_active_args(now))).fetchone()
        if row is None:
            return None
        revoked = _revoke_all(db, int(row["user_id"]))
    return {"id": int(row["user_id"]), "role": row["role"], "revoked": revoked}


# ---------------------------------------------------------------------------
# OTP-коди і пошта
# ---------------------------------------------------------------------------

def otp_hash(user_id: int, purpose: str, code: str) -> str:
    """A8: HMAC-SHA256(V2_SECRET_KEY, "otp:{purpose}:{user_id}:{code}") — без ключа перебір 10^6 кодів марний."""
    message = f"otp:{purpose}:{user_id}:{code}"
    return hmac.new(settings.secret_key().encode(), message.encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class CodeCheck:
    valid: bool
    compared: bool = False       # код справді порівнювався (спробу зарезервовано)


def _check_code(db: sqlite3.Connection, user_id: int, purpose: str, code: str, now: datetime) -> CodeCheck:
    """
    Усередині BEGIN IMMEDIATE: останній відкритий challenge → резерв спроби
    (UPDATE … attempts = attempts + 1 WHERE consumed = 0 AND attempts < 5, rowcount 1) ДО порівняння →
    порівняння HMAC → споживання (UPDATE … consumed = 1 WHERE consumed = 0, rowcount 1).
    Облік невдач на акаунт веде виклик (політики 2FA і скидання пароля різні).
    """
    row = db.execute("SELECT id, code_hash, expires_at FROM v2_challenges "
                     "WHERE user_id = ? AND purpose = ? AND consumed = 0 ORDER BY id DESC LIMIT 1",
                     (user_id, purpose)).fetchone()
    if row is None or datetime.fromisoformat(row["expires_at"]) <= now:
        return CodeCheck(valid=False)
    reserved = db.execute("UPDATE v2_challenges SET attempts = attempts + 1 "
                          "WHERE id = ? AND consumed = 0 AND attempts < ?", (row["id"], OTP_MAX_ATTEMPTS)).rowcount
    if reserved != 1:
        return CodeCheck(valid=False)
    if not hmac.compare_digest(row["code_hash"], otp_hash(user_id, purpose, code)):
        return CodeCheck(valid=False, compared=True)
    consumed = db.execute("UPDATE v2_challenges SET consumed = 1 WHERE id = ? AND consumed = 0", (row["id"],)).rowcount
    return CodeCheck(valid=consumed == 1, compared=True)


def _account_locked(db: sqlite3.Connection, scope: str, subject: str, limit: int, now: datetime) -> bool:
    return _window_count(db, scope, subject, ACCOUNT_WINDOW_MINUTES, now) >= limit


def _register_failure(db: sqlite3.Connection, scope: str, subject: str, limit: int, now: datetime) -> bool:
    """Зараховує невдачу в тій самій транзакції; повертає, чи ліміт акаунта тепер вичерпано."""
    _consume(db, scope, subject, limit, ACCOUNT_WINDOW_MINUTES, now)
    return _account_locked(db, scope, subject, limit, now)


def _two_factor_attempt(db: sqlite3.Connection, user_id: int, code: str, now: datetime) -> tuple[str, bool]:
    """
    A5: 2FA-код акаунта. Невдачею вважається лише справжнє порівняння, що не збіглося (спроби на вичерпаний
    чи прострочений код нічого не перевіряють). Повертає (ok | invalid | locked, locked_now).
    """
    subject = str(user_id)
    if _account_locked(db, _FAIL_2FA_SCOPE, subject, TWO_FACTOR_FAIL_LIMIT, now):
        return "locked", False
    check = _check_code(db, user_id, "login_2fa", code, now)
    if check.valid:
        return "ok", False
    if check.compared and _register_failure(db, _FAIL_2FA_SCOPE, subject, TWO_FACTOR_FAIL_LIMIT, now):
        return "locked", True
    return "invalid", False


def _reset_attempt(db: sqlite3.Connection, user_id: int | None, email: str, code: str,
                   now: datetime) -> tuple[str, bool]:
    """
    A4: підтвердження скидання. Ліміт рахується за нормалізованим email і зараховує КОЖНУ невдачу
    (невідомий акаунт, немає/прострочений/вичерпаний код, неправильний код), тож поведінка однакова для
    наявного й невідомого email і не розкриває існування акаунта.
    """
    if _account_locked(db, _FAIL_RESET_SCOPE, email, RESET_FAIL_LIMIT, now):
        return "locked", False
    if user_id is not None and _check_code(db, user_id, "password_reset", code, now).valid:
        return "ok", False
    if _register_failure(db, _FAIL_RESET_SCOPE, email, RESET_FAIL_LIMIT, now):
        return "locked", True
    return "invalid", False


def issue_challenge(user_id: int, purpose: str, recipient: str) -> datetime:
    """Новий код замінює попередній того самого призначення. Код зберігається лише після надсилання листа."""
    if purpose not in ("login_2fa", "password_reset"):
        raise ValueError("Непідтримуване призначення коду")
    if purpose == "login_2fa" and two_factor_locked(user_id):
        raise TwoFactorLocked("Забагато невдалих кодів підтвердження")
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = _utc_now() + timedelta(minutes=OTP_TTL_MINUTES)
    subject = ("Integrity Dashboard V2: скидання паролю" if purpose == "password_reset"
               else "Integrity Dashboard V2: код підтвердження")
    deliver_mail(recipient, subject, f"Ваш код: {code}. Код дійсний {OTP_TTL_MINUTES} хвилин.")
    with _immediate() as db:
        db.execute("UPDATE v2_challenges SET consumed = 1 WHERE user_id = ? AND purpose = ? AND consumed = 0",
                   (user_id, purpose))
        db.execute("INSERT INTO v2_challenges(user_id, purpose, code_hash, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
                   (user_id, purpose, otp_hash(user_id, purpose, code), expires.isoformat(), _utc_now().isoformat()))
    return expires


def verify_challenge(user_id: int, purpose: str, code: str) -> bool:
    """
    Атомарна перевірка й споживання коду (одна транзакція BEGIN IMMEDIATE): не більше 5 порівнянь на код,
    одне споживання, облік невдач акаунта. Маршрути використовують complete_two_factor і
    reset_password_with_code, де в тій самій транзакції ще й ротується сесія або змінюється пароль.
    """
    now = _utc_now()
    with _immediate() as db:
        if purpose == "login_2fa":
            return _two_factor_attempt(db, user_id, code, now)[0] == "ok"
        email = db.execute("SELECT email FROM v2_users WHERE id = ?", (user_id,)).fetchone()
        if email is None:
            return False
        return _reset_attempt(db, user_id, normalize_email(email[0]), code, now)[0] == "ok"


@dataclass
class TwoFactorResult:
    status: str                       # ok | invalid | locked | no_pending
    locked_now: bool = False
    user: dict[str, Any] = field(default_factory=dict)
    token: str | None = None
    expires: datetime | None = None


def complete_two_factor(session_token: str | None, code: str) -> TwoFactorResult:
    """
    A1/A2: одна транзакція BEGIN IMMEDIATE — pending-сесія існує й не verified → ліміт акаунта → перевірка
    й споживання коду → DELETE pending (rowcount 1) → INSERT verified. Logout, скидання пароля чи зміна
    ролі, що завершилися раніше, лишають verify без pending-сесії — і нова сесія не видається.
    """
    now = _utc_now()
    with _immediate() as db:
        session = db.execute(
            "SELECT s.id, s.user_id, s.two_factor_verified, u.name, u.email, u.role FROM v2_sessions s "
            f"JOIN v2_users u ON u.id = s.user_id WHERE s.token_hash = ? AND {_ACTIVE_SESSION}",
            (token_hash(session_token or ""), *_active_args(now))).fetchone()
        if session is None or session["two_factor_verified"]:
            return TwoFactorResult(status="no_pending")
        user = public_user({**dict(session), "id": session["user_id"]})
        status, locked_now = _two_factor_attempt(db, user["id"], code, now)
        if status != "ok":
            return TwoFactorResult(status=status, locked_now=locked_now, user=user)
        deleted = db.execute("DELETE FROM v2_sessions WHERE id = ? AND two_factor_verified = 0",
                             (session["id"],)).rowcount
        if deleted != 1:
            raise SessionRevoked("Pending-сесії немає: нову сесію не видано")    # відкат разом зі споживанням
        token, expires = _insert_session(db, user["id"], True, now)
        db.execute("DELETE FROM v2_rate_limits WHERE scope = '2fa_issue' AND subject = ?", (str(user["id"]),))
    return TwoFactorResult(status="ok", user=user, token=token, expires=expires)


@dataclass
class ResetResult:
    status: str                       # ok | invalid | locked
    locked_now: bool = False
    user_id: int | None = None
    role: str | None = None
    sessions_revoked: int = 0


def reset_password_with_code(email: str, code: str, new_password: str) -> ResetResult:
    """
    A4: одна транзакція — ліміт 10 невдалих підтверджень за 24 год → перевірка й споживання коду →
    новий пароль → видалення ВСІХ сесій (включно з pending) → гасіння всіх інших відкритих кодів.
    scrypt нового пароля виконується лише для правильного коду.
    """
    email = normalize_email(email)
    now = _utc_now()
    with _immediate() as db:
        user = db.execute("SELECT id, role FROM v2_users WHERE email = ?", (email,)).fetchone()
        user_id = int(user["id"]) if user else None
        status, locked_now = _reset_attempt(db, user_id, email, code, now)
        if status != "ok":
            return ResetResult(status=status, locked_now=locked_now, user_id=user_id,
                               role=user["role"] if user else None)
        db.execute("UPDATE v2_users SET password_hash = ? WHERE id = ?", (hash_password(new_password), user_id))
        revoked = db.execute("DELETE FROM v2_sessions WHERE user_id = ?", (user_id,)).rowcount
        db.execute("UPDATE v2_challenges SET consumed = 1 WHERE user_id = ? AND consumed = 0", (user_id,))
    return ResetResult(status="ok", user_id=user_id, role=user["role"], sessions_revoked=revoked)


def update_password(user_id: int, password: str) -> None:
    """Новий пароль, видалення всіх сесій і гасіння відкритих кодів — одна транзакція."""
    encoded = hash_password(password)
    with _immediate() as db:
        db.execute("UPDATE v2_users SET password_hash = ? WHERE id = ?", (encoded, user_id))
        db.execute("DELETE FROM v2_sessions WHERE user_id = ?", (user_id,))
        db.execute("UPDATE v2_challenges SET consumed = 1 WHERE user_id = ? AND consumed = 0", (user_id,))


def deliver_mail(recipient: str, subject: str, body: str) -> None:
    """
    development + V2_AUTH_DEV_MAIL=1 → локальна скринька v2_dev_mail (OTP відкритим текстом лише тут).
    Налаштований SMTP → лист через STARTTLS (типово, порт 587) або неявний TLS (V2_SMTP_TLS_MODE=implicit,
    порт 465) з тим самим перевіреним контекстом. Інакше в release → MailNotConfigured.
    """
    if settings.dev_mail_enabled():
        with _immediate() as db:
            db.execute(_DEV_MAIL_SCHEMA)
            db.execute("INSERT INTO v2_dev_mail(recipient, subject, body, created_at) VALUES (?, ?, ?, ?)",
                       (recipient, subject, body, _utc_now().isoformat()))
        return
    smtp_host = os.environ.get("V2_SMTP_HOST")
    if not smtp_host:
        raise MailNotConfigured("Поштовий сервіс не налаштовано")
    try:
        mode = settings.smtp_tls_mode()
    except RuntimeError as error:
        raise MailNotConfigured("Некоректний V2_SMTP_TLS_MODE") from error
    sender = os.environ.get("V2_SMTP_FROM", "").strip() or "no-reply@localhost"
    sender_domain = parseaddr(sender)[1].rpartition("@")[2] or "localhost"
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message["Date"] = formatdate(usegmt=True)
    message["Message-ID"] = make_msgid(domain=sender_domain)
    message.set_content(body)
    port = int(os.environ.get("V2_SMTP_PORT", "465" if mode == "implicit" else "587"))
    try:
        if mode == "implicit":
            # TLS з першого байта; контекст перевіряє ланцюжок до довіреного CA і hostname V2_SMTP_HOST
            client = smtplib.SMTP_SSL(smtp_host, port, timeout=10, context=smtp_tls_context())
        else:
            client = smtplib.SMTP(smtp_host, port, timeout=10)
        with client as smtp:
            if mode == "starttls":
                # STARTTLS обов'язковий: без нього (або з помилкою TLS) облікові дані й код не надсилаються.
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
    with _reader() as db:
        if "v2_dev_mail" not in _tables(db):
            return None
        row = db.execute("SELECT recipient, subject, body, created_at FROM v2_dev_mail "
                         + ("WHERE recipient = ? " if recipient else "") + "ORDER BY id DESC LIMIT 1",
                         ((recipient,) if recipient else ())).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Ролі й керування сесіями (адміністратор)
# ---------------------------------------------------------------------------

def server_only_role_error(*roles: str) -> str | None:
    """Код відмови, якщо серед ролей є роль, яку змінює лише власник сервера; інакше None."""
    for role, code in SERVER_ONLY_ROLE_ERRORS.items():
        if role in roles:
            return code
    return None


def _require_admin_actor(db: sqlite3.Connection, actor_id: int, actor_session: str | None, now: datetime) -> None:
    """Повторна перевірка актора В ТІЙ САМІЙ транзакції: роль admin, сесія з 2FA, строк, token_hash."""
    actor = db.execute(
        "SELECT 1 FROM v2_sessions s JOIN v2_users u ON u.id = s.user_id "
        f"WHERE u.id = ? AND u.role = 'admin' AND s.token_hash = ? AND s.two_factor_verified = 1 AND {_ACTIVE_SESSION}",
        (actor_id, token_hash(actor_session or ""), *_active_args(now))).fetchone()
    if actor is None:
        raise RoleChangeError("actor_unauthorized")


def _apply_role_change(db: sqlite3.Connection, actor_id: int, target_id: int, old_role: str, new_role: str,
                       now: datetime) -> dict[str, Any]:
    """Роль (UPDATE … WHERE role = old, rowcount 1) → видалення ВСІХ сесій цілі (включно з pending) → гасіння
    всіх відкритих кодів цілі → запис v2_role_changes. Лише всередині транзакції BEGIN IMMEDIATE."""
    if db.execute("UPDATE v2_users SET role = ? WHERE id = ? AND role = ?",
                  (new_role, target_id, old_role)).rowcount != 1:
        raise RoleChangeError("conflict")
    revoked = db.execute("DELETE FROM v2_sessions WHERE user_id = ?", (target_id,)).rowcount
    db.execute("UPDATE v2_challenges SET consumed = 1 WHERE user_id = ? AND consumed = 0", (target_id,))
    db.execute("INSERT INTO v2_role_changes(actor_user_id, target_user_id, old_role, new_role, changed_at) "
               "VALUES (?, ?, ?, ?, ?)", (actor_id, target_id, old_role, new_role, now.isoformat()))
    return {"user_id": target_id, "old_role": old_role, "new_role": new_role,
            "sessions_revoked": revoked, "changed_at": now.isoformat()}


def change_user_role(actor_id: int, actor_session: str | None, target_id: int,
                     expected_role: str, new_role: str) -> dict[str, Any]:
    """
    A13: одна транзакція BEGIN IMMEDIATE на одному з'єднанні — повторна перевірка актора → поточна роль цілі
    (admin → admin_role_server_only, data_officer → data_officer_role_server_only) → expected_role →
    UPDATE … WHERE id = ? AND role = ? (rowcount 1) → видалення ВСІХ сесій цілі (включно з pending) →
    гасіння всіх відкритих кодів цілі → запис v2_role_changes.

    Ролі admin і data_officer через веб не призначає й не знімає ніхто: expected_role або new_role з такою
    роллю відхиляються ще до транзакції, а така роль цілі — усередині неї (на випадок, якщо роль змінили на
    сервері між читанням переліку і запитом). Їх призначає й знімає лише власник сервера:
    python -m app.v2_role_cli. Отже, у вебі змінити роль фактично неможливо (лишається лише user).
    """
    if expected_role not in ROLES or new_role not in ROLES:
        raise RoleChangeError("invalid_role")
    if actor_id == target_id:
        raise RoleChangeError("self_change")
    code = server_only_role_error(expected_role, new_role)
    if code:
        raise RoleChangeError(code)
    now = _utc_now()
    with _immediate() as db:
        _require_admin_actor(db, actor_id, actor_session, now)
        target = db.execute("SELECT role FROM v2_users WHERE id = ?", (target_id,)).fetchone()
        if target is None:
            raise RoleChangeError("not_found")
        code = server_only_role_error(target["role"])
        if code:
            raise RoleChangeError(code)
        if target["role"] != expected_role or expected_role == new_role:
            raise RoleChangeError("conflict")
        return _apply_role_change(db, actor_id, target_id, expected_role, new_role, now)


def server_role_plan(email: str, new_role: str) -> dict[str, Any]:
    """
    Серверна команда (app.v2_role_cli), лише читання: що зміниться. Ті самі відмови, що й у server_change_role:
    invalid_role, not_found, unchanged, last_admin. Повертає id, замаскований email, ролі, кількість сесій.
    """
    if new_role not in ROLES:
        raise RoleChangeError("invalid_role")
    with _reader() as db:
        return _server_check(db, email, new_role)


def _server_check(db: sqlite3.Connection, email: str, new_role: str) -> dict[str, Any]:
    target = db.execute("SELECT id, email, role FROM v2_users WHERE email = ?", (normalize_email(email),)).fetchone()
    if target is None:
        raise RoleChangeError("not_found")
    if target["role"] == new_role:
        raise RoleChangeError("unchanged")
    admins = db.execute("SELECT COUNT(*) FROM v2_users WHERE role = 'admin'").fetchone()[0]
    if target["role"] == "admin" and admins <= 1:
        raise RoleChangeError("last_admin")           # лишається щонайменше один адміністратор
    sessions = db.execute("SELECT COUNT(*) FROM v2_sessions WHERE user_id = ?", (target["id"],)).fetchone()[0]
    return {"user_id": int(target["id"]), "email_masked": mask_email(target["email"]), "old_role": target["role"],
            "new_role": new_role, "sessions": int(sessions), "admins": int(admins)}


def server_change_role(email: str, new_role: str) -> dict[str, Any]:
    """
    Серверна команда власника сервера: та сама транзакція BEGIN IMMEDIATE, що й веб-зміна (роль, усі сесії цілі,
    відкриті коди, v2_role_changes), але з актором SERVER_ACTOR_ID і без сесії. Перевірки (ціль, та сама роль,
    останній адміністратор) повторюються всередині транзакції.
    """
    if new_role not in ROLES:
        raise RoleChangeError("invalid_role")
    now = _utc_now()
    with _immediate() as db:
        plan = _server_check(db, email, new_role)
        result = _apply_role_change(db, SERVER_ACTOR_ID, plan["user_id"], plan["old_role"], new_role, now)
    return {**result, "email_masked": plan["email_masked"]}


def revoke_user_sessions(actor_id: int, actor_session: str | None, target_id: int) -> int:
    """A14: усі сесії користувача (включно з pending) і відкриті коди 2FA — одна транзакція з перевіркою актора.
    Сесії user і data_officer — можна; сесії іншого адміністратора через веб не завершуються
    (admin_role_server_only); власні — можна."""
    now = _utc_now()
    with _immediate() as db:
        _require_admin_actor(db, actor_id, actor_session, now)
        target = db.execute("SELECT role FROM v2_users WHERE id = ?", (target_id,)).fetchone()
        if target is None:
            raise RoleChangeError("not_found")
        if target["role"] == "admin" and target_id != actor_id:
            raise RoleChangeError("admin_role_server_only")
        return _revoke_all(db, target_id)


def list_role_changes(limit: int = 500) -> list[dict[str, Any]]:
    with _reader() as db:
        rows = db.execute("SELECT id, actor_user_id, target_user_id, old_role, new_role, changed_at "
                          "FROM v2_role_changes ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Персональні спроби (S5: власник лише з сесії)
# ---------------------------------------------------------------------------

_ATTEMPT_COLUMNS = "id, assessment_id, assessment_name, status, answers_json, started_at, completed_at, updated_at"


def create_attempt(user_id: int, attempt_id: str, assessment_name: str, status: str, answers_json: str,
                   started_at: str, completed_at: str | None, assessment_id: str = "legacy") -> None:
    if status not in {"draft", "completed"}:
        raise ValueError("Непідтримуваний стан спроби")
    now = _utc_now().isoformat()
    with _immediate() as db:
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
    with _reader() as db:
        rows = db.execute(f"SELECT {_ATTEMPT_COLUMNS} FROM v2_user_attempts WHERE user_id = ? ORDER BY started_at DESC",
                          (user_id,)).fetchall()
    return [dict(row) for row in rows]


def get_attempt(user_id: int, attempt_id: str) -> dict[str, Any] | None:
    with _reader() as db:
        row = db.execute(f"SELECT {_ATTEMPT_COLUMNS} FROM v2_user_attempts WHERE id = ? AND user_id = ?",
                         (attempt_id, user_id)).fetchone()
    return dict(row) if row else None


def complete_attempt(user_id: int, attempt_id: str, completed_at: str, answers_json: str | None = None) -> dict[str, Any]:
    now = _utc_now().isoformat()
    with _immediate() as db:
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
