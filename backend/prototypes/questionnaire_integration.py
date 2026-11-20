"""Isolated official-questionnaire integration prototype (never mounted in app.main).

All database operations require an explicit .prototype.sqlite guard created from a
synthetic copy of the actual schema-3 tables. No production migration is exposed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import shutil
import sqlite3
import threading
import time
import os
import tempfile
from collections import defaultdict, deque
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.request_security import require_session_csrf
from app.roles import session_user
from app.v2_auth import auth_db_path

from .official_expert import CATALOG, Answer, PrototypeError, validate_answers


GUARD_TABLE = "__questionnaire_prototype_guard"
GUARD_VALUE = "synthetic-schema3-copy-only-v1"
MIGRATION_VERSION = 1
MIGRATION_TABLES = {
    "questionnaire_templates", "questionnaire_questions", "questionnaire_options",
    "cycle_questionnaires", "official_response_sets", "official_answers",
    "expert_permissions", "expert_assignments", "expert_assessments",
    "expert_answers", "expert_audit_events", "questionnaire_rate_limit_buckets",
    "questionnaire_prototype_meta",
}
CORE_TABLES = (
    "components", "questions", "cycles", "units", "response_sets", "answers",
    "access_tokens", "access_token_policies", "cycle_configs",
    "objective_indicators", "recommendations", "audit_events",
)

DDL = (
    """CREATE TABLE questionnaire_templates (
      template_id TEXT NOT NULL CHECK(length(template_id) BETWEEN 1 AND 64),
      version TEXT NOT NULL CHECK(length(version) BETWEEN 1 AND 32),
      form_number INTEGER NOT NULL CHECK(form_number IN (1,2)),
      audience_code TEXT NOT NULL CHECK(length(audience_code) BETWEEN 1 AND 32),
      source_uri TEXT NOT NULL CHECK(length(source_uri) <= 512),
      source_appendix TEXT NOT NULL CHECK(source_appendix = 'В'),
      status TEXT NOT NULL CHECK(status IN ('draft','published')),
      content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64),
      created_at INTEGER NOT NULL,
      PRIMARY KEY(template_id, version)
    )""",
    """CREATE TABLE questionnaire_questions (
      template_id TEXT NOT NULL, version TEXT NOT NULL,
      question_id TEXT NOT NULL CHECK(length(question_id) BETWEEN 1 AND 64),
      section_id TEXT NOT NULL CHECK(length(section_id) BETWEEN 1 AND 64),
      question_number INTEGER NOT NULL CHECK(question_number > 0),
      printed_page INTEGER NOT NULL CHECK(printed_page BETWEEN 53 AND 66),
      display_order INTEGER NOT NULL CHECK(display_order > 0),
      kind TEXT NOT NULL CHECK(kind = 'single_choice'),
      required INTEGER NOT NULL CHECK(required IN (0,1)),
      source_duplicate INTEGER NOT NULL DEFAULT 0 CHECK(source_duplicate IN (0,1)),
      prompt TEXT NOT NULL CHECK(length(prompt) BETWEEN 1 AND 4000),
      PRIMARY KEY(template_id, version, question_id),
      UNIQUE(template_id, version, display_order),
      FOREIGN KEY(template_id, version) REFERENCES questionnaire_templates(template_id,version)
    )""",
    """CREATE TABLE questionnaire_options (
      template_id TEXT NOT NULL, version TEXT NOT NULL, question_id TEXT NOT NULL,
      option_id TEXT NOT NULL CHECK(length(option_id) BETWEEN 1 AND 64),
      display_order INTEGER NOT NULL CHECK(display_order > 0),
      label TEXT NOT NULL CHECK(length(label) BETWEEN 1 AND 5000),
      PRIMARY KEY(template_id, version, question_id, option_id),
      UNIQUE(template_id, version, question_id, display_order),
      FOREIGN KEY(template_id, version, question_id)
        REFERENCES questionnaire_questions(template_id,version,question_id)
    )""",
    """CREATE TABLE cycle_questionnaires (
      cycle_id INTEGER NOT NULL REFERENCES cycles(id),
      template_id TEXT NOT NULL, version TEXT NOT NULL,
      PRIMARY KEY(cycle_id), UNIQUE(cycle_id,template_id,version),
      FOREIGN KEY(template_id,version) REFERENCES questionnaire_templates(template_id,version)
    )""",
    """CREATE TABLE official_response_sets (
      response_set_id TEXT PRIMARY KEY CHECK(length(response_set_id) = 32),
      cycle_id INTEGER NOT NULL, template_id TEXT NOT NULL, version TEXT NOT NULL,
      category TEXT NOT NULL CHECK(length(category) BETWEEN 1 AND 30),
      UNIQUE(response_set_id,template_id,version),
      FOREIGN KEY(cycle_id,template_id,version)
        REFERENCES cycle_questionnaires(cycle_id,template_id,version)
    )""",
    """CREATE TABLE official_answers (
      response_set_id TEXT NOT NULL, template_id TEXT NOT NULL, version TEXT NOT NULL,
      question_id TEXT NOT NULL, option_id TEXT NOT NULL,
      PRIMARY KEY(response_set_id,question_id),
      FOREIGN KEY(response_set_id,template_id,version)
        REFERENCES official_response_sets(response_set_id,template_id,version) ON DELETE CASCADE,
      FOREIGN KEY(template_id,version,question_id,option_id)
        REFERENCES questionnaire_options(template_id,version,question_id,option_id)
    )""",
    """CREATE TABLE expert_permissions (
      principal_id TEXT PRIMARY KEY,
      enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
      granted_at INTEGER NOT NULL, granted_by TEXT NOT NULL,
      revoked_at INTEGER, revoked_by TEXT,
      CHECK((enabled=1 AND revoked_at IS NULL AND revoked_by IS NULL) OR
            (enabled=0 AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL))
    )""",
    """CREATE TABLE expert_assignments (
      assignment_id TEXT PRIMARY KEY CHECK(length(assignment_id)=32),
      principal_id TEXT NOT NULL REFERENCES expert_permissions(principal_id),
      cycle_id INTEGER NOT NULL, template_id TEXT NOT NULL, version TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('active','revoked')),
      created_at INTEGER NOT NULL, created_by TEXT NOT NULL,
      revoked_at INTEGER, revoked_by TEXT,
      UNIQUE(assignment_id,principal_id),
      FOREIGN KEY(cycle_id,template_id,version)
        REFERENCES cycle_questionnaires(cycle_id,template_id,version),
      CHECK((status='active' AND revoked_at IS NULL AND revoked_by IS NULL) OR
            (status='revoked' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL))
    )""",
    """CREATE TABLE expert_assessments (
      assessment_id TEXT PRIMARY KEY CHECK(length(assessment_id)=32),
      assignment_id TEXT NOT NULL UNIQUE, principal_id TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('draft','finalized')),
      revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
      FOREIGN KEY(assignment_id,principal_id)
        REFERENCES expert_assignments(assignment_id,principal_id)
    )""",
    """CREATE TABLE expert_answers (
      assessment_id TEXT NOT NULL REFERENCES expert_assessments(assessment_id) ON DELETE CASCADE,
      template_id TEXT NOT NULL, version TEXT NOT NULL,
      question_id TEXT NOT NULL, option_id TEXT NOT NULL,
      PRIMARY KEY(assessment_id,question_id),
      FOREIGN KEY(template_id,version,question_id,option_id)
        REFERENCES questionnaire_options(template_id,version,question_id,option_id)
    )""",
    """CREATE TABLE expert_audit_events (
      id INTEGER PRIMARY KEY, action TEXT NOT NULL CHECK(action IN
        ('grant','revoke','assign','assignment_revoke','answers_updated','finalized')),
      actor_id TEXT NOT NULL, target_principal_id TEXT,
      assignment_id TEXT, assessment_id TEXT, created_at INTEGER NOT NULL,
      FOREIGN KEY(assignment_id) REFERENCES expert_assignments(assignment_id),
      FOREIGN KEY(assessment_id) REFERENCES expert_assessments(assessment_id)
    )""",
    """CREATE TABLE questionnaire_rate_limit_buckets (
      bucket_key TEXT NOT NULL, window_start INTEGER NOT NULL,
      request_count INTEGER NOT NULL CHECK(request_count >= 0), expires_at INTEGER NOT NULL,
      PRIMARY KEY(bucket_key,window_start)
    )""",
    "CREATE INDEX questionnaire_rate_limit_expiry_idx ON questionnaire_rate_limit_buckets(expires_at)",
    """CREATE TABLE questionnaire_prototype_meta (
      version INTEGER PRIMARY KEY CHECK(version=1),
      applied_at INTEGER NOT NULL, migration_name TEXT NOT NULL
    )""",
    """CREATE TRIGGER immutable_published_template_update BEFORE UPDATE ON questionnaire_templates
      WHEN OLD.status='published' BEGIN SELECT RAISE(ABORT,'published template immutable'); END""",
    """CREATE TRIGGER immutable_published_template_delete BEFORE DELETE ON questionnaire_templates
      WHEN OLD.status='published' BEGIN SELECT RAISE(ABORT,'published template immutable'); END""",
    """CREATE TRIGGER immutable_published_question_insert BEFORE INSERT ON questionnaire_questions
      WHEN (SELECT status FROM questionnaire_templates WHERE template_id=NEW.template_id AND version=NEW.version)='published'
      BEGIN SELECT RAISE(ABORT,'published template immutable'); END""",
    """CREATE TRIGGER immutable_published_question_update BEFORE UPDATE ON questionnaire_questions
      WHEN (SELECT status FROM questionnaire_templates WHERE template_id=OLD.template_id AND version=OLD.version)='published'
      BEGIN SELECT RAISE(ABORT,'published template immutable'); END""",
    """CREATE TRIGGER immutable_published_question_delete BEFORE DELETE ON questionnaire_questions
      WHEN (SELECT status FROM questionnaire_templates WHERE template_id=OLD.template_id AND version=OLD.version)='published'
      BEGIN SELECT RAISE(ABORT,'published template immutable'); END""",
    """CREATE TRIGGER immutable_published_option_insert BEFORE INSERT ON questionnaire_options
      WHEN (SELECT status FROM questionnaire_templates WHERE template_id=NEW.template_id AND version=NEW.version)='published'
      BEGIN SELECT RAISE(ABORT,'published template immutable'); END""",
    """CREATE TRIGGER immutable_published_option_update BEFORE UPDATE ON questionnaire_options
      WHEN (SELECT status FROM questionnaire_templates WHERE template_id=OLD.template_id AND version=OLD.version)='published'
      BEGIN SELECT RAISE(ABORT,'published template immutable'); END""",
    """CREATE TRIGGER immutable_published_option_delete BEFORE DELETE ON questionnaire_options
      WHEN (SELECT status FROM questionnaire_templates WHERE template_id=OLD.template_id AND version=OLD.version)='published'
      BEGIN SELECT RAISE(ABORT,'published template immutable'); END""",
    """CREATE TRIGGER binding_frozen_after_activation BEFORE UPDATE ON cycle_questionnaires
      WHEN (SELECT status FROM cycles WHERE id=OLD.cycle_id)!='draft'
      BEGIN SELECT RAISE(ABORT,'cycle questionnaire binding frozen'); END""",
    """CREATE TRIGGER binding_insert_requires_draft BEFORE INSERT ON cycle_questionnaires
      WHEN COALESCE((SELECT status FROM cycles WHERE id=NEW.cycle_id),'')!='draft'
      BEGIN SELECT RAISE(ABORT,'cycle questionnaire binding requires draft'); END""",
    """CREATE TRIGGER binding_delete_frozen_after_activation BEFORE DELETE ON cycle_questionnaires
      WHEN (SELECT status FROM cycles WHERE id=OLD.cycle_id)!='draft'
      BEGIN SELECT RAISE(ABORT,'cycle questionnaire binding frozen'); END""",
)


class IntegrationError(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail


class SyntheticSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_id: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=32)
    category: str = Field(min_length=1, max_length=30)
    code: str = Field(min_length=1, max_length=128)
    answers: list[Answer] = Field(min_length=1, max_length=64)


class ExpertAnswers(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    answers: list[Answer] = Field(max_length=64)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


@contextmanager
def _db(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = _connect(db_path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _same_path(left: str | None, right: Path) -> bool:
    if not left or left == ":memory:":
        return False


def _resolved(path: Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path)))).resolve()


def _is_under_test_temp(path: Path) -> bool:
    try:
        _resolved(path).relative_to(_resolved(Path(tempfile.gettempdir())))
        return True
    except ValueError:
        return False


def _protected_database_paths(*, include_configured_auth: bool = True) -> set[Path]:
    from app.database import DB_PATH
    from app.v2_auth import auth_db_path
    backend_dir = Path(__file__).resolve().parents[1]
    paths = {Path(DB_PATH), Path(os.environ.get("INTEGRITY_DB", DB_PATH)),
             backend_dir / "integrity.db", backend_dir / "v2_auth.db"}
    if include_configured_auth and os.environ.get("V2_AUTH_DB"):
        paths.add(Path(os.environ["V2_AUTH_DB"]))
    elif not os.environ.get("V2_AUTH_DB"):
        paths.add(Path(auth_db_path()))
    return {_resolved(path) for path in paths}


def _require_test_temp_path(path: Path, *, must_not_exist: bool = False) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise ValueError("Symbolic-link database paths are forbidden in the prototype")
    resolved = _resolved(candidate)
    if not _is_under_test_temp(resolved):
        raise ValueError("Prototype databases must be inside the operating-system temp directory")
    if resolved in _protected_database_paths():
        raise ValueError("Production/shared database paths are forbidden")
    if must_not_exist and resolved.exists():
        raise ValueError("Prototype database destination must be a new file")
    return resolved


def _require_isolated_auth_db() -> Path:
    configured = os.environ.get("V2_AUTH_DB")
    if not configured:
        raise ValueError("An explicit isolated V2_AUTH_DB is required for the prototype")
    path = Path(configured).expanduser()
    if path.is_symlink():
        raise ValueError("Symbolic-link auth database paths are forbidden in the prototype")
    resolved = _resolved(path)
    if not resolved.is_file() or not _is_under_test_temp(resolved) or \
            resolved in _protected_database_paths(include_configured_auth=False):
        raise ValueError("V2_AUTH_DB must be an existing isolated temporary test database")
    return resolved
    try:
        return Path(left).resolve() == right.resolve()
    except OSError:
        return False


def _guard(conn: sqlite3.Connection, db_path: Path, *, explicit: bool) -> None:
    db_path = _require_test_temp_path(db_path)
    if explicit is not True or not db_path.name.endswith(".prototype.sqlite"):
        raise ValueError("Explicit permission and .prototype.sqlite path are required")
    if _same_path(__import__("os").environ.get("INTEGRITY_DB"), db_path) or \
            _same_path(__import__("os").environ.get("V2_AUTH_DB"), db_path):
        raise ValueError("Production/shared database paths are forbidden")
    if GUARD_TABLE not in {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}:
        raise ValueError("Database is not a marked synthetic schema-3 copy")
    marker = conn.execute(f"SELECT marker FROM {GUARD_TABLE} LIMIT 1").fetchone()
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if not marker or marker[0] != GUARD_VALUE or version != 3:
        raise ValueError("Synthetic guard/schema version verification failed")
    core_tables = {"cycles", "cycle_configs", "response_sets", "answers", "access_tokens",
                   "access_token_policies", "audit_events"}
    present = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not core_tables <= present:
        raise ValueError("Synthetic schema-3 core tables are incomplete")
    synthetic_cycle = conn.execute("SELECT id FROM cycles WHERE name='Synthetic schema3 cycle'").fetchone()
    synthetic_audit = conn.execute("SELECT 1 FROM audit_events WHERE action='synthetic.seed'").fetchone()
    if not synthetic_cycle or not synthetic_audit:
        raise ValueError("Synthetic schema-3 sentinel rows are missing")


def create_synthetic_schema3_source(source_path: Path) -> Path:
    """Create an actual schema-3-shaped SQLite DB with deterministic synthetic rows."""
    if not source_path.name.endswith(".schema3-synthetic.sqlite"):
        raise ValueError("Synthetic source filename must end in .schema3-synthetic.sqlite")
    source_path = _require_test_temp_path(source_path, must_not_exist=True)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import Base
    from app.models import (AccessToken, AccessTokenPolicy, Answer as NumericAnswer, AuditEvent,
                            Component, Cycle, CycleConfig, Question, ResponseSet, Unit)
    from datetime import date, datetime, timedelta, timezone

    source_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{source_path.as_posix()}")
    Base.metadata.create_all(engine)
    with engine.begin() as con:
        con.exec_driver_sql("PRAGMA user_version=3")
    with Session(engine) as db:
        cycle = Cycle(name="Synthetic schema3 cycle", start_date=date(2026, 1, 1),
                      status="draft", min_group_size=5)
        component = Component(code="SYN", name="Synthetic", weight=1.0)
        unit = Unit(name="Synthetic Unit")
        db.add_all([cycle, component, unit])
        db.flush()
        question = Question(component_id=component.id, text="Synthetic numeric question",
                            scale_min=1, scale_max=5, kind="survey")
        db.add(question)
        db.flush()
        db.add(CycleConfig(cycle_id=cycle.id, description="synthetic", scope="test",
                           categories_json='["staff"]', questionnaire_version="demo-v1"))
        response = ResponseSet(cycle_id=cycle.id, respondent_category="staff", unit=unit.name)
        db.add(response)
        db.flush()
        db.add(NumericAnswer(response_set_id=response.id, question_id=question.id, value=4))
        token = AccessToken(cycle_id=cycle.id, token="synthetic-assessment-code", used=False)
        db.add(token)
        db.flush()
        db.add(AccessTokenPolicy(token_id=token.id, category="staff",
                                 expires_at=datetime.now(timezone.utc) + timedelta(days=2)))
        db.add(AuditEvent(created_at=datetime.now(timezone.utc), actor_role="admin", action="synthetic.seed",
                          assessment_id=cycle.id, details='{"synthetic":true}'))
        db.commit()
    engine.dispose()
    with closing(sqlite3.connect(source_path)) as con:
        con.execute("PRAGMA foreign_keys=ON")
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not con.execute("PRAGMA foreign_key_check").fetchall()
        assert con.execute("PRAGMA user_version").fetchone()[0] == 3
    return source_path


def create_synthetic_schema3_copy(source_path: Path, copy_path: Path) -> dict:
    """Copy a synthetic schema-3 source and mark it as the only migration target."""
    if not source_path.name.endswith(".schema3-synthetic.sqlite") or \
            not copy_path.name.endswith(".prototype.sqlite"):
        raise ValueError("Use a synthetic schema3 source and .prototype.sqlite destination")
    source_path = _require_test_temp_path(source_path)
    copy_path = _require_test_temp_path(copy_path, must_not_exist=True)
    if source_path == copy_path:
        raise ValueError("Migration copy must be a new separate file")
    with closing(sqlite3.connect(f"file:{quote(source_path.as_posix(), safe=':/')}?mode=ro", uri=True)) as check:
        tables = {row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"cycles", "cycle_configs", "response_sets", "answers", "access_tokens",
                    "access_token_policies", "audit_events"}
        if check.execute("PRAGMA user_version").fetchone()[0] != 3 or not required <= tables:
            raise ValueError("Source is not the expected schema-3 synthetic database")
        if not check.execute("SELECT 1 FROM cycles WHERE name='Synthetic schema3 cycle'").fetchone() or \
                not check.execute("SELECT 1 FROM audit_events WHERE action='synthetic.seed'").fetchone() or \
                not check.execute("SELECT 1 FROM access_tokens WHERE token='synthetic-assessment-code'").fetchone():
            raise ValueError("Source lacks required synthetic sentinel rows")
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or \
                check.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Source failed SQLite integrity verification")
    copy_path.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source_path)
    dst = sqlite3.connect(copy_path)
    try:
        src.backup(dst)
        dst.execute(f"CREATE TABLE {GUARD_TABLE}(marker TEXT NOT NULL)")
        dst.execute(f"INSERT INTO {GUARD_TABLE}(marker) VALUES (?)", (GUARD_VALUE,))
        dst.commit()
    finally:
        src.close()
        dst.close()
    return {"source_sha256": file_sha256(source_path), "copy_sha256": file_sha256(copy_path)}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def core_snapshot(db_path: Path) -> dict[str, tuple[int, str]]:
    with _db(db_path) as con:
        result = {}
        for table in CORE_TABLES:
            rows = [list(row) for row in con.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
            encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), default=str).encode()
            result[table] = (len(rows), hashlib.sha256(encoded).hexdigest())
        return result


def create_verified_backup(db_path: Path, *, allow_test_migration: bool = False) -> Path:
    with _db(db_path) as con:
        _guard(con, db_path, explicit=allow_test_migration)
        target = db_path.with_name(f"{db_path.stem}.verified-backup-{time.time_ns()}{db_path.suffix}")
        dst = sqlite3.connect(target)
        try:
            con.backup(dst)
            dst.commit()
        finally:
            dst.close()
    with closing(sqlite3.connect(target)) as check:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            target.unlink(missing_ok=True)
            raise RuntimeError("Backup integrity check failed")
        if check.execute("PRAGMA user_version").fetchone()[0] != 3:
            target.unlink(missing_ok=True)
            raise RuntimeError("Backup is not schema 3")
    return target


def apply_questionnaire_migration(db_path: Path, *, allow_test_migration: bool = False,
                                  fail_at: str | None = None) -> dict:
    """Apply migration 1 after schema 3; never changes PRAGMA user_version."""
    with _db(db_path) as con:
        _guard(con, db_path, explicit=allow_test_migration)
        existing = {row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        migration_tables = existing & MIGRATION_TABLES
        if migration_tables:
            meta = con.execute("SELECT version FROM questionnaire_prototype_meta").fetchone() \
                if "questionnaire_prototype_meta" in migration_tables else None
            if migration_tables == MIGRATION_TABLES and meta and meta[0] == MIGRATION_VERSION:
                return {"action": "already_applied", "backup": None, "version": 3}
            raise RuntimeError("Partial or unknown questionnaire migration found; refusing to continue")

    backup = create_verified_backup(db_path, allow_test_migration=allow_test_migration)
    before = core_snapshot(db_path)
    with _db(db_path) as con:
        _guard(con, db_path, explicit=allow_test_migration)
        con.execute("BEGIN IMMEDIATE")
        try:
            for idx, statement in enumerate(DDL, start=1):
                con.execute(statement)
                if fail_at == f"ddl_{idx}":
                    raise RuntimeError("Injected migration failure")
                if fail_at == "after_templates" and idx == 4:
                    raise RuntimeError("Injected migration failure")
            if fail_at == "before_meta":
                raise RuntimeError("Injected migration failure")
            con.execute("INSERT INTO questionnaire_prototype_meta(version,applied_at,migration_name) VALUES (?,?,?)",
                        (MIGRATION_VERSION, int(time.time()), "official-questionnaire-after-schema3"))
            if con.execute("PRAGMA user_version").fetchone()[0] != 3:
                raise RuntimeError("Prototype must preserve schema-3 user_version")
            if con.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Foreign key check failed")
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("SQLite integrity check failed")
            con.commit()
        except Exception:
            con.rollback()
            raise
    if core_snapshot(db_path) != before:
        restore_synthetic_backup(db_path, backup, allow_test_restore=True)
        raise RuntimeError("Migration changed schema-3 core data; restored the verified backup")
    return {"action": "migrated", "backup": str(backup), "version": 3,
            "prototype_migration": MIGRATION_VERSION, "core_tables_preserved": len(before)}


def restore_synthetic_backup(db_path: Path, backup_path: Path, *, allow_test_restore: bool = False) -> None:
    with _db(db_path) as con:
        _guard(con, db_path, explicit=allow_test_restore)
    if not backup_path.name.endswith(".prototype.sqlite") and ".verified-backup-" not in backup_path.name:
        raise ValueError("Restore requires a verified synthetic backup")
    src = sqlite3.connect(backup_path)
    dst = sqlite3.connect(db_path)
    try:
        if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or \
                src.execute("PRAGMA user_version").fetchone()[0] != 3:
            raise ValueError("Backup failed schema/integrity verification")
        guard = src.execute(f"SELECT marker FROM {GUARD_TABLE} LIMIT 1").fetchone()
        if not guard or guard[0] != GUARD_VALUE:
            raise ValueError("Backup is not a guarded synthetic database")
        src.backup(dst)
        dst.commit()
    finally:
        src.close()
        dst.close()


class InMemoryRateLimiter:
    """Process-local anonymous throttling; intentionally not distributed/production ready."""
    def __init__(self, *, global_limit: int, cycle_limit: int, window_seconds: int = 60,
                 clock=time.monotonic):
        self.global_limit, self.cycle_limit = global_limit, cycle_limit
        self.window_seconds, self.clock = window_seconds, clock
        self.global_events: deque[float] = deque()
        self.cycle_events: dict[str, deque[float]] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, cycle_key: str) -> bool:
        now = self.clock()
        with self.lock:
            while self.global_events and now - self.global_events[0] >= self.window_seconds:
                self.global_events.popleft()
            for key, events in list(self.cycle_events.items()):
                while events and now - events[0] >= self.window_seconds:
                    events.popleft()
                if not events:
                    self.cycle_events.pop(key, None)
            events = self.cycle_events.get(cycle_key)
            if events is None:
                events = deque()
            if len(self.global_events) >= self.global_limit or len(events) >= self.cycle_limit:
                return False
            self.global_events.append(now)
            events.append(now)
            self.cycle_events[cycle_key] = events
            return True


class SQLiteRateLimiter:
    """Test-only shared-file limiter; demonstrates multi-worker atomic counters without IP keys."""
    def __init__(self, db_path: Path, *, global_limit: int, cycle_limit: int,
                 window_seconds: int = 60, clock=time.time):
        if min(global_limit, cycle_limit, window_seconds) < 1:
            raise ValueError("Rate-limit values must be positive")
        self.db_path = Path(db_path)
        self.global_limit, self.cycle_limit = global_limit, cycle_limit
        self.window_seconds, self.clock = window_seconds, clock

    def allow(self, cycle_key: str) -> bool:
        now = int(self.clock())
        start = now - (now % self.window_seconds)
        expires = start + self.window_seconds
        keys = ("global", f"cycle:{cycle_key}")
        with _db(self.db_path) as con:
            _guard(con, self.db_path, explicit=True)
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute("DELETE FROM questionnaire_rate_limit_buckets WHERE expires_at<=?", (now,))
                counts = {}
                for key in keys:
                    row = con.execute("SELECT request_count FROM questionnaire_rate_limit_buckets "
                                      "WHERE bucket_key=? AND window_start=?", (key, start)).fetchone()
                    counts[key] = row[0] if row else 0
                if counts[keys[0]] >= self.global_limit or counts[keys[1]] >= self.cycle_limit:
                    con.commit()
                    return False
                for key in keys:
                    con.execute("""INSERT INTO questionnaire_rate_limit_buckets
                      (bucket_key,window_start,request_count,expires_at) VALUES (?,?,1,?)
                      ON CONFLICT(bucket_key,window_start) DO UPDATE SET
                      request_count=request_count+1,expires_at=excluded.expires_at""",
                                (key, start, expires))
                con.commit()
                return True
            except Exception:
                con.rollback()
                raise


class IntegrationStore:
    def __init__(self, db_path: Path, *, rate_limiter: InMemoryRateLimiter | SQLiteRateLimiter | None = None):
        self.db_path = Path(db_path)
        self.rate_limiter = rate_limiter or SQLiteRateLimiter(db_path, global_limit=100, cycle_limit=20)
        self.logger = logging.getLogger("questionnaire.prototype")

    def _require_guard(self, con: sqlite3.Connection) -> None:
        _guard(con, self.db_path, explicit=True)

    def seed_template(self, template_id: str, version: str, form: int, questions: list[dict]) -> None:
        """Only fixture/setup code calls this; published content becomes immutable."""
        if (template_id, version) not in CATALOG:
            raise ValueError("Only prototype fixture catalog versions are allowed")
        with _db(self.db_path) as con:
            self._require_guard(con)
            con.execute("BEGIN IMMEDIATE")
            try:
                content = json.dumps(questions, ensure_ascii=False, sort_keys=True).encode()
                digest = hashlib.sha256(content).hexdigest()
                con.execute("INSERT INTO questionnaire_templates VALUES (?,?,?,?,?,?,?,?,?)",
                            (template_id, version, form, "working_group" if form == 1 else "ambiguous",
                             "https://nuou.org.ua/assets/documents/recommendations_transform_dobrochesnist.pdf",
                             "В", "draft", digest, int(time.time())))
                for display_order, question in enumerate(questions, start=1):
                    con.execute("INSERT INTO questionnaire_questions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                (template_id, version, question["id"], question.get("section", "section"),
                                 display_order, 53 if form == 1 else 60, display_order, "single_choice", 1,
                                 int(question.get("source_duplicate", False)), question["text"]))
                    for option_order, option in enumerate(question["options"], start=1):
                        con.execute("INSERT INTO questionnaire_options VALUES (?,?,?,?,?,?)",
                                    (template_id, version, question["id"], option["id"], option_order,
                                     option["text"]))
                con.execute("UPDATE questionnaire_templates SET status='published' WHERE template_id=? AND version=?",
                            (template_id, version))
                con.commit()
            except Exception:
                con.rollback()
                raise

    def bind_cycle(self, cycle_id: int, template_id: str, version: str) -> None:
        with _db(self.db_path) as con:
            self._require_guard(con)
            con.execute("BEGIN IMMEDIATE")
            try:
                cycle = con.execute("SELECT status FROM cycles WHERE id=?", (cycle_id,)).fetchone()
                if not cycle or cycle[0] != "draft":
                    raise IntegrationError(409, "Questionnaire binding requires a draft cycle")
                con.execute("INSERT INTO cycle_questionnaires VALUES (?,?,?)", (cycle_id, template_id, version))
                con.commit()
            except Exception:
                con.rollback()
                raise

    def activate_cycle(self, cycle_id: int) -> None:
        """Test-only serialized activation; requires an immutable binding first."""
        with _db(self.db_path) as con:
            self._require_guard(con)
            con.execute("BEGIN IMMEDIATE")
            try:
                cycle = con.execute("SELECT status FROM cycles WHERE id=?", (cycle_id,)).fetchone()
                binding = con.execute("SELECT 1 FROM cycle_questionnaires WHERE cycle_id=?", (cycle_id,)).fetchone()
                if not cycle or cycle[0] != "draft" or not binding:
                    raise IntegrationError(409, "Cycle activation requires a draft cycle and questionnaire binding")
                changed = con.execute("UPDATE cycles SET status='open' WHERE id=? AND status='draft'",
                                      (cycle_id,)).rowcount
                if changed != 1:
                    raise IntegrationError(409, "Cycle is not draft")
                con.commit()
            except Exception:
                con.rollback()
                raise

    def close_cycle(self, cycle_id: int) -> None:
        with _db(self.db_path) as con:
            self._require_guard(con)
            con.execute("BEGIN IMMEDIATE")
            try:
                changed = con.execute("UPDATE cycles SET status='closed' WHERE id=? AND status='open'",
                                      (cycle_id,)).rowcount
                if not changed:
                    raise IntegrationError(409, "Cycle is not open")
                con.commit()
            except Exception:
                con.rollback()
                raise

    def submit(self, cycle_id: int, body: SyntheticSubmission) -> None:
        try:
            allowed = self.rate_limiter.allow(str(cycle_id))
        except sqlite3.Error as error:
            raise IntegrationError(503, "Submission temporarily unavailable") from error
        if not allowed:
            self.logger.warning("official_submission_throttled")
            raise IntegrationError(429, "Забагато спроб. Спробуйте пізніше")
        try:
            validate_answers(body.template_id, body.version, body.answers, complete=True)
        except PrototypeError as error:
            raise IntegrationError(422, "Некоректні відповіді") from error
        with _db(self.db_path) as con:
            self._require_guard(con)
            con.execute("BEGIN IMMEDIATE")
            try:
                cycle = con.execute("SELECT status FROM cycles WHERE id=?", (cycle_id,)).fetchone()
                binding = con.execute("SELECT template_id,version FROM cycle_questionnaires WHERE cycle_id=?",
                                      (cycle_id,)).fetchone()
                if not cycle or cycle[0] != "open":
                    raise IntegrationError(409, "Оцінювання закрите або недоступне")
                if not binding or tuple(binding) != (body.template_id, body.version):
                    raise IntegrationError(409, "Версія анкети не відповідає циклу")
                config = con.execute("SELECT categories_json FROM cycle_configs WHERE cycle_id=?", (cycle_id,)).fetchone()
                allowed_categories = json.loads(config[0]) if config else ["mgmt", "npp", "cadets", "staff"]
                if body.category not in allowed_categories:
                    raise IntegrationError(403, "Категорія недоступна для циклу")
                token = con.execute("""SELECT t.id,p.category,p.expires_at FROM access_tokens t
                    JOIN access_token_policies p ON p.token_id=t.id
                    WHERE t.token=? AND t.cycle_id=? AND t.used=0 AND p.expires_at > datetime('now')""",
                                    (body.code, cycle_id)).fetchone()
                if not token or token[1] != body.category:
                    raise IntegrationError(403, "Недійсний або вже використаний код")
                set_id = secrets.token_hex(16)
                con.execute("INSERT INTO official_response_sets VALUES (?,?,?,?,?)",
                            (set_id, cycle_id, body.template_id, body.version, body.category))
                con.executemany("INSERT INTO official_answers VALUES (?,?,?,?,?)", [
                    (set_id, body.template_id, body.version, answer.question_id, answer.option_id)
                    for answer in body.answers])
                updated = con.execute("UPDATE access_tokens SET used=1 WHERE id=? AND used=0", (token[0],)).rowcount
                if updated != 1:
                    raise IntegrationError(403, "Недійсний або вже використаний код")
                con.commit()
            except Exception:
                con.rollback()
                self.logger.warning("official_submission_rejected")
                raise

    def grant_expert(self, principal_id: str, actor_id: str) -> None:
        auth_path = _require_isolated_auth_db()
        auth_uri = f"file:{quote(auth_path.as_posix(), safe=':/')}?mode=ro"
        with closing(sqlite3.connect(auth_uri, uri=True)) as auth_db:
            existing_user = auth_db.execute("SELECT 1 FROM v2_users WHERE id=?", (int(principal_id),)).fetchone()
        if not existing_user:
            raise IntegrationError(404, "V2 principal unavailable")
        now = int(time.time())
        with _db(self.db_path) as con:
            self._require_guard(con)
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute("""INSERT INTO expert_permissions(principal_id,enabled,granted_at,granted_by,revoked_at,revoked_by)
                    VALUES (?,1,?,?,NULL,NULL) ON CONFLICT(principal_id) DO UPDATE SET
                    enabled=1,granted_at=excluded.granted_at,granted_by=excluded.granted_by,
                    revoked_at=NULL,revoked_by=NULL""", (principal_id, now, actor_id))
                con.execute("INSERT INTO expert_audit_events(action,actor_id,target_principal_id,created_at) VALUES ('grant',?,?,?)",
                            (actor_id, principal_id, now))
                con.commit()
            except Exception:
                con.rollback()
                raise

    def revoke_expert(self, principal_id: str, actor_id: str) -> None:
        now = int(time.time())
        with _db(self.db_path) as con:
            self._require_guard(con)
            con.execute("BEGIN IMMEDIATE")
            try:
                result = con.execute("UPDATE expert_permissions SET enabled=0,revoked_at=?,revoked_by=? WHERE principal_id=? AND enabled=1",
                                     (now, actor_id, principal_id)).rowcount
                if not result:
                    raise IntegrationError(404, "Expert permission unavailable")
                con.execute("UPDATE expert_assignments SET status='revoked',revoked_at=?,revoked_by=? WHERE principal_id=? AND status='active'",
                            (now, actor_id, principal_id))
                con.execute("INSERT INTO expert_audit_events(action,actor_id,target_principal_id,created_at) VALUES ('revoke',?,?,?)",
                            (actor_id, principal_id, now))
                con.commit()
            except Exception:
                con.rollback()
                raise

    def revoke_assignment(self, assignment_id: str, actor_id: str) -> None:
        now = int(time.time())
        with _db(self.db_path) as con:
            self._require_guard(con)
            con.execute("BEGIN IMMEDIATE")
            try:
                changed = con.execute("UPDATE expert_assignments SET status='revoked',revoked_at=?,revoked_by=? WHERE assignment_id=? AND status='active'",
                                      (now, actor_id, assignment_id)).rowcount
                if not changed:
                    raise IntegrationError(404, "Assignment unavailable")
                con.execute("INSERT INTO expert_audit_events(action,actor_id,assignment_id,created_at) VALUES ('assignment_revoke',?,?,?)",
                            (actor_id, assignment_id, now))
                con.commit()
            except Exception:
                con.rollback()
                raise

    def assign_expert(self, principal_id: str, cycle_id: int, template_id: str, version: str,
                      actor_id: str) -> str:
        assignment_id = secrets.token_hex(16)
        with _db(self.db_path) as con:
            self._require_guard(con)
            con.execute("BEGIN IMMEDIATE")
            try:
                grant = con.execute("SELECT enabled FROM expert_permissions WHERE principal_id=?",
                                     (principal_id,)).fetchone()
                if not grant or grant[0] != 1:
                    raise IntegrationError(403, "Expert permission required")
                con.execute("INSERT INTO expert_assignments VALUES (?,?,?,?,?,'active',?,?,NULL,NULL)",
                            (assignment_id, principal_id, cycle_id, template_id, version,
                             int(time.time()), actor_id))
                con.execute("INSERT INTO expert_assessments(assessment_id,assignment_id,principal_id,status,revision) VALUES (?,?,?,'draft',0)",
                            (secrets.token_hex(16), assignment_id, principal_id))
                con.execute("INSERT INTO expert_audit_events(action,actor_id,target_principal_id,assignment_id,created_at) VALUES ('assign',?,?,?,?)",
                            (actor_id, principal_id, assignment_id, int(time.time())))
                con.commit()
                return assignment_id
            except Exception:
                con.rollback()
                raise

    def _assigned(self, con: sqlite3.Connection, assessment_id: str, principal_id: str) -> sqlite3.Row:
        row = con.execute("""SELECT ea.*, a.assessment_id, a.status AS assessment_status, a.revision
          FROM expert_assessments a JOIN expert_assignments ea ON ea.assignment_id=a.assignment_id
          JOIN expert_permissions p ON p.principal_id=ea.principal_id
          WHERE a.assessment_id=? AND ea.principal_id=? AND ea.status='active' AND p.enabled=1""",
                          (assessment_id, principal_id)).fetchone()
        if not row:
            raise IntegrationError(404, "Assessment unavailable")
        return row

    def expert_get(self, assessment_id: str, principal_id: str) -> dict:
        with _db(self.db_path) as con:
            self._require_guard(con)
            row = self._assigned(con, assessment_id, principal_id)
            answers = [dict(x) for x in con.execute("SELECT question_id,option_id FROM expert_answers WHERE assessment_id=? ORDER BY question_id",
                                                    (assessment_id,))]
            return {"assessment_id": assessment_id, "cycle_id": row["cycle_id"],
                    "template_id": row["template_id"], "version": row["version"],
                    "status": row["assessment_status"], "revision": row["revision"], "answers": answers}

    def expert_update(self, assessment_id: str, principal_id: str, payload: ExpertAnswers) -> int:
        row = self.expert_get(assessment_id, principal_id)
        try:
            validate_answers(row["template_id"], row["version"], payload.answers, complete=False)
        except PrototypeError as error:
            raise IntegrationError(422, "Некоректні експертні відповіді") from error
        if row["status"] != "draft":
            raise IntegrationError(409, "Assessment finalized")
        with _db(self.db_path) as con:
            self._require_guard(con)
            con.execute("BEGIN IMMEDIATE")
            try:
                current = self._assigned(con, assessment_id, principal_id)
                if current["revision"] != payload.expected_revision:
                    raise IntegrationError(409, "Revision conflict")
                if current["assessment_status"] != "draft":
                    raise IntegrationError(409, "Assessment finalized")
                con.execute("DELETE FROM expert_answers WHERE assessment_id=?", (assessment_id,))
                con.executemany("INSERT INTO expert_answers VALUES (?,?,?,?,?)", [
                    (assessment_id, current["template_id"], current["version"], a.question_id, a.option_id)
                    for a in payload.answers])
                new_revision = current["revision"] + 1
                con.execute("UPDATE expert_assessments SET revision=? WHERE assessment_id=? AND revision=?",
                            (new_revision, assessment_id, current["revision"]))
                con.execute("INSERT INTO expert_audit_events(action,actor_id,assignment_id,assessment_id,created_at) VALUES ('answers_updated',?,?,?,?)",
                            (principal_id, current["assignment_id"], assessment_id, int(time.time())))
                con.commit()
                return new_revision
            except Exception:
                con.rollback()
                raise

    def expert_finalize(self, assessment_id: str, principal_id: str) -> None:
        with _db(self.db_path) as con:
            self._require_guard(con)
            con.execute("BEGIN IMMEDIATE")
            try:
                row = self._assigned(con, assessment_id, principal_id)
                if row["assessment_status"] != "draft":
                    raise IntegrationError(409, "Assessment finalized")
                answers = [Answer(**dict(x)) for x in con.execute(
                    "SELECT question_id,option_id FROM expert_answers WHERE assessment_id=?", (assessment_id,))]
                try:
                    validate_answers(row["template_id"], row["version"], answers, complete=True)
                except PrototypeError as error:
                    raise IntegrationError(422, "Required answers missing") from error
                con.execute("UPDATE expert_assessments SET status='finalized',revision=revision+1 WHERE assessment_id=? AND status='draft'",
                            (assessment_id,))
                con.execute("INSERT INTO expert_audit_events(action,actor_id,assignment_id,assessment_id,created_at) VALUES ('finalized',?,?,?,?)",
                            (principal_id, row["assignment_id"], assessment_id, int(time.time())))
                con.commit()
            except Exception:
                con.rollback()
                raise

    def purge_closed_cycle(self, cycle_id: int, *, allow_test_purge: bool = False,
                           fail_after_sets: bool = False) -> dict:
        with _db(self.db_path) as con:
            self._require_guard(con)
            if not allow_test_purge:
                raise ValueError("Explicit test-only purge permission is required")
            con.execute("BEGIN IMMEDIATE")
            try:
                cycle = con.execute("SELECT status FROM cycles WHERE id=?", (cycle_id,)).fetchone()
                if not cycle or cycle[0] != "closed":
                    raise IntegrationError(409, "Only closed synthetic cycles can be purged")
                count = con.execute("SELECT COUNT(*) FROM official_response_sets WHERE cycle_id=?", (cycle_id,)).fetchone()[0]
                con.execute("DELETE FROM official_response_sets WHERE cycle_id=?", (cycle_id,))
                if fail_after_sets:
                    raise RuntimeError("Injected purge failure")
                token_ids = [r[0] for r in con.execute("SELECT id FROM access_tokens WHERE cycle_id=?", (cycle_id,))]
                if token_ids:
                    marks = ",".join("?" for _ in token_ids)
                    con.execute(f"DELETE FROM access_token_policies WHERE token_id IN ({marks})", token_ids)
                con.execute("DELETE FROM access_tokens WHERE cycle_id=?", (cycle_id,))
                con.commit()
                return {"response_sets_purged": count, "access_tokens_purged": len(token_ids)}
            except Exception:
                con.rollback()
                raise


def suppress_cells(cells: list[tuple[str, int]], k: int) -> dict:
    """Synthetic primary + complementary suppression; no endpoint exposes raw cells."""
    if k < 2:
        raise ValueError("Synthetic k must be at least 2")
    hidden = {i for i, (_, count) in enumerate(cells) if count < k}
    if len(hidden) == 1 and len(cells) > 1:
        visible = [(count, i) for i, (_, count) in enumerate(cells) if i not in hidden]
        if visible:
            hidden.add(min(visible)[1])
    total = sum(count for _, count in cells)
    total_hidden = total < k or len(hidden) == len(cells)
    result = []
    for i, (label, count) in enumerate(cells):
        if i in hidden:
            result.append({"label": "недостатньо відповідей", "count": None, "suppressed": True})
        else:
            result.append({"label": label, "count": count, "suppressed": False})
    return {"total": None if total_hidden else total, "groups": result}


class DisclosureQueryConflict(Exception):
    """The synthetic release family has already disclosed a different query."""


class SyntheticDisclosureLedger:
    """Conservative test-only guard against repeated/overlapping query differencing.

    This is deliberately not a production aggregate API or a substitute for a
    data-owner-approved suppression policy. Within one release family, the
    first normalized query is cached; identical requests receive that exact
    cached result, while a different filter or cycle is rejected.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[str, object]] = {}

    def evaluate(self, release_family: str, query: dict, produce):
        if not release_family or not isinstance(query, dict):
            raise ValueError("A synthetic release family and query are required")
        encoded = json.dumps(query, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        with self._lock:
            existing = self._entries.get(release_family)
            if existing:
                if existing[0] != fingerprint:
                    raise DisclosureQueryConflict("Query unavailable for this release family")
                return json.loads(json.dumps(existing[1], ensure_ascii=False))
            frozen_result = json.loads(json.dumps(produce(), ensure_ascii=False))
            self._entries[release_family] = (fingerprint, frozen_result)
            return json.loads(json.dumps(frozen_result, ensure_ascii=False))


class V2ExpertSessionAdapter:
    """Resolve the real V2 cookie/session and completed 2FA, never X-Role."""
    def __call__(self, request: Request) -> dict:
        try:
            _require_isolated_auth_db()
        except ValueError as error:
            raise HTTPException(503, "Isolated test authentication unavailable") from error
        user = session_user(request)
        if user is None:
            raise HTTPException(401, "V2 session required")
        if not user.get("two_factor_verified"):
            raise HTTPException(403, "V2 2FA required")
        return user

    def require_admin(self, request: Request) -> dict:
        user = self(request)
        if user.get("role") != "admin":
            raise HTTPException(403, "Admin required")
        require_session_csrf(request)
        return user


def create_integration_test_app(db_path: Path, store: IntegrationStore | None = None) -> tuple[FastAPI, IntegrationStore]:
    """Separate test app factory. Do not include its routes from production main."""
    store = store or IntegrationStore(db_path)
    app = FastAPI(title="Questionnaire integration prototype only", docs_url=None, redoc_url=None)
    session_adapter = V2ExpertSessionAdapter()

    @app.exception_handler(IntegrationError)
    async def integration_error(_request: Request, error: IntegrationError):
        return JSONResponse(status_code=error.status, content={"detail": error.detail})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _error: RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": "Invalid request"})

    @app.post("/prototype/integration/cycles/{cycle_id}/official-submissions", status_code=201)
    def official_submission(cycle_id: int, body: SyntheticSubmission, request: Request):
        if request.headers.get("Cookie") or request.headers.get("Authorization"):
            raise IntegrationError(400, "Anonymous request required")
        try:
            store.submit(cycle_id, body)
        except IntegrationError:
            raise
        except Exception as error:
            raise IntegrationError(422, "Submission unavailable") from error
        return {"accepted": True}

    def admin(request: Request) -> dict:
        return session_adapter.require_admin(request)

    @app.post("/prototype/integration/expert/grants/{principal_id}")
    def grant(principal_id: str, request: Request):
        actor = admin(request)
        if str(actor["id"]) == principal_id:
            raise HTTPException(403, "Self-grant is not allowed")
        store.grant_expert(principal_id, str(actor["id"]))
        return {"granted": True}

    @app.delete("/prototype/integration/expert/grants/{principal_id}")
    def revoke(principal_id: str, request: Request):
        actor = admin(request)
        store.revoke_expert(principal_id, str(actor["id"]))
        return {"revoked": True}

    @app.delete("/prototype/integration/expert/assignments/{assignment_id}")
    def revoke_assignment(assignment_id: str, request: Request):
        actor = admin(request)
        store.revoke_assignment(assignment_id, str(actor["id"]))
        return {"revoked": True}

    @app.post("/prototype/integration/expert/assignments/{cycle_id}/{template_id}/{version}")
    def assign(cycle_id: int, template_id: str, version: str, principal_id: str, request: Request):
        actor = admin(request)
        assignment_id = store.assign_expert(principal_id, cycle_id, template_id, version, str(actor["id"]))
        return {"assignment_id": assignment_id}

    def expert_context(assessment_id: str, request: Request) -> dict:
        user = session_adapter(request)
        return store.expert_get(assessment_id, str(user["id"]))

    @app.get("/prototype/integration/expert/assessments/{assessment_id}")
    def expert_read(assessment_id: str, request: Request):
        return expert_context(assessment_id, request)

    @app.put("/prototype/integration/expert/assessments/{assessment_id}/answers")
    def expert_update(assessment_id: str, body: ExpertAnswers, request: Request):
        user = session_adapter(request)
        require_session_csrf(request)
        revision = store.expert_update(assessment_id, str(user["id"]), body)
        return {"revision": revision}

    @app.post("/prototype/integration/expert/assessments/{assessment_id}/finalize")
    def expert_finalize(assessment_id: str, request: Request):
        user = session_adapter(request)
        require_session_csrf(request)
        store.expert_finalize(assessment_id, str(user["id"]))
        return {"status": "finalized"}

    return app, store
