"""Prototype-only official/expert API backed by a caller-supplied disposable DB.

No production router imports this module. The small ID catalog is a test fixture,
not an approved backend questionnaire contract or a scoring methodology.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from contextlib import contextmanager
from collections.abc import Iterator
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field


SECTION_KEYS = {1: "culture", 2: "system", 3: "accountability", 4: "maturity"}
FORM_SECTIONS = {1: (5, 2, 4, 1), 2: (3, 2, 4, 1)}


def fixture_catalog() -> dict[tuple[str, str], dict[str, frozenset[str]]]:
    """Mirror immutable full-catalog IDs (2.0.0 and 2.1.0 share them); verify against frontend in tests."""
    result = {}
    for form, counts in FORM_SECTIONS.items():
        questions = {}
        for section, count in enumerate(counts, 1):
            for number in range(1, count + 1):
                question_id = f"av-f{form}-{SECTION_KEYS[section]}-{number}"
                option_count = 6 if section == 3 and number == 3 else 5
                questions[question_id] = frozenset(
                    f"{question_id}-{letter}" for letter in "abcdef"[:option_count]
                )
        for version in ("2.0.0", "2.1.0"):
            result[(f"appendix-v-form-{form}", version)] = questions
    return result


CATALOG = fixture_catalog()


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str = Field(min_length=1, max_length=64)
    option_id: str = Field(min_length=1, max_length=64)


class OfficialSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cycle_id: str = Field(min_length=1, max_length=64)
    template_id: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=32)
    category: str = Field(min_length=1, max_length=32)
    token: str = Field(min_length=8, max_length=128)
    answers: list[Answer] = Field(min_length=1, max_length=64)


class ExpertUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_id: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=32)
    expected_revision: int = Field(ge=0)
    answers: list[Answer] = Field(max_length=64)


@dataclass(frozen=True)
class TestSession:
    principal_id: str
    two_factor_verified: bool
    csrf_token: str
    expires_at: int


class PrototypeError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail


def validate_answers(template_id: str, version: str, answers: list[Answer], *, complete: bool) -> None:
    questions = CATALOG.get((template_id, version))
    if questions is None:
        raise PrototypeError(422, "Unknown template version")
    seen = set()
    for answer in answers:
        if answer.question_id in seen:
            raise PrototypeError(422, "Duplicate question")
        seen.add(answer.question_id)
        if answer.option_id not in questions.get(answer.question_id, ()):
            raise PrototypeError(422, "Invalid question or option")
    if complete and seen != questions.keys():
        raise PrototypeError(422, "Required answers missing")


class PrototypeStore:
    def __init__(self, db_path: Path, secret: bytes):
        if not Path(db_path).name.endswith(".prototype.sqlite"):
            raise ValueError("Prototype requires a dedicated .prototype.sqlite database")
        if not secret or len(secret) < 16:
            raise ValueError("A test-only HMAC secret of at least 16 bytes is required")
        self.db_path = Path(db_path)
        self.secret = secret
        self.sessions: dict[str, TestSession] = {}
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        # Test-app schema lives only at the explicit path supplied by a test fixture.
        with self._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS prototype_cycles (
                    id TEXT PRIMARY KEY, template_id TEXT NOT NULL, version TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('open','closed'))
                );
                CREATE TABLE IF NOT EXISTS prototype_codes (
                    digest TEXT PRIMARY KEY, cycle_id TEXT NOT NULL, category TEXT NOT NULL,
                    expires_at INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0 CHECK (used IN (0,1))
                );
                CREATE TABLE IF NOT EXISTS official_response_sets (
                    id TEXT PRIMARY KEY, cycle_id TEXT NOT NULL, template_id TEXT NOT NULL,
                    version TEXT NOT NULL, category TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS official_answers (
                    response_set_id TEXT NOT NULL REFERENCES official_response_sets(id) ON DELETE CASCADE,
                    question_id TEXT NOT NULL, option_id TEXT NOT NULL,
                    PRIMARY KEY (response_set_id, question_id)
                );
                CREATE TABLE IF NOT EXISTS expert_permissions (
                    principal_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL CHECK (enabled IN (0,1))
                );
                CREATE TABLE IF NOT EXISTS expert_assessments (
                    id TEXT PRIMARY KEY, cycle_id TEXT NOT NULL, template_id TEXT NOT NULL,
                    version TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ('draft','finalized')),
                    revision INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS expert_assignments (
                    assessment_id TEXT NOT NULL REFERENCES expert_assessments(id) ON DELETE CASCADE,
                    principal_id TEXT NOT NULL, PRIMARY KEY (assessment_id, principal_id)
                );
                CREATE TABLE IF NOT EXISTS expert_answers (
                    assessment_id TEXT NOT NULL REFERENCES expert_assessments(id) ON DELETE CASCADE,
                    question_id TEXT NOT NULL, option_id TEXT NOT NULL,
                    PRIMARY KEY (assessment_id, question_id)
                );
                CREATE TABLE IF NOT EXISTS expert_audit_events (
                    id INTEGER PRIMARY KEY, assessment_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL, action TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
            """)

    def _digest(self, token: str) -> str:
        return hmac.new(self.secret, token.encode("utf-8"), hashlib.sha256).hexdigest()

    # Explicit server/test fixtures. No public endpoint grants a role or assignment.
    def seed_cycle(self, cycle_id: str, template_id: str, version: str = "2.0.0") -> None:
        if (template_id, version) not in CATALOG:
            raise ValueError("Unknown fixture template")
        with self._connection() as db:
            db.execute("INSERT INTO prototype_cycles VALUES (?,?,?,'open')", (cycle_id, template_id, version))

    def seed_code(self, cycle_id: str, category: str, token: str, *, expires_at: int | None = None) -> None:
        with self._connection() as db:
            db.execute("INSERT INTO prototype_codes VALUES (?,?,?,?,0)",
                       (self._digest(token), cycle_id, category, expires_at or int(time.time()) + 3600))

    def seed_expert(self, principal_id: str, *, enabled: bool = True) -> None:
        with self._connection() as db:
            db.execute("""INSERT INTO expert_permissions VALUES (?,?)
                ON CONFLICT(principal_id) DO UPDATE SET enabled=excluded.enabled""",
                       (principal_id, int(enabled)))

    def seed_assessment(self, assessment_id: str, cycle_id: str, template_id: str,
                        principal_id: str, version: str = "2.0.0") -> None:
        if (template_id, version) not in CATALOG:
            raise ValueError("Unknown fixture template")
        with self._connection() as db:
            db.execute("INSERT INTO expert_assessments VALUES (?,?,?,?,'draft',0)",
                       (assessment_id, cycle_id, template_id, version))
            db.execute("INSERT INTO expert_assignments VALUES (?,?)", (assessment_id, principal_id))

    def seed_session(self, principal_id: str, *, two_factor_verified: bool,
                     expires_at: int | None = None) -> tuple[str, str]:
        session_id, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.sessions[session_id] = TestSession(principal_id, two_factor_verified, csrf,
                                                expires_at if expires_at is not None else int(time.time()) + 3600)
        return session_id, csrf

    def close_cycle(self, cycle_id: str) -> None:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE prototype_cycles SET status='closed' WHERE id=?", (cycle_id,))
            db.commit()

    def submit(self, payload: OfficialSubmission) -> None:
        validate_answers(payload.template_id, payload.version, payload.answers, complete=True)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                cycle = db.execute("SELECT * FROM prototype_cycles WHERE id=?", (payload.cycle_id,)).fetchone()
                if not cycle or cycle["status"] != "open":
                    raise PrototypeError(409, "Cycle unavailable")
                if (cycle["template_id"], cycle["version"]) != (payload.template_id, payload.version):
                    raise PrototypeError(422, "Template does not match cycle")
                code = db.execute("SELECT * FROM prototype_codes WHERE digest=?", (self._digest(payload.token),)).fetchone()
                if (not code or code["used"] or code["cycle_id"] != payload.cycle_id
                        or code["category"] != payload.category or code["expires_at"] <= int(time.time())):
                    raise PrototypeError(403, "Code unavailable")
                response_id = secrets.token_hex(16)
                db.execute("INSERT INTO official_response_sets VALUES (?,?,?,?,?)",
                           (response_id, payload.cycle_id, payload.template_id, payload.version, payload.category))
                db.executemany("INSERT INTO official_answers VALUES (?,?,?)",
                               [(response_id, a.question_id, a.option_id) for a in payload.answers])
                db.execute("UPDATE prototype_codes SET used=1 WHERE digest=? AND used=0", (self._digest(payload.token),))
                db.commit()
            except Exception:
                db.rollback()
                raise

    def _assigned(self, db: sqlite3.Connection, assessment_id: str, principal_id: str) -> sqlite3.Row:
        row = db.execute("""SELECT a.* FROM expert_assessments a
            JOIN expert_assignments x ON x.assessment_id=a.id
            JOIN expert_permissions p ON p.principal_id=x.principal_id
            WHERE a.id=? AND x.principal_id=? AND p.enabled=1""", (assessment_id, principal_id)).fetchone()
        if row is None:
            raise PrototypeError(404, "Assessment unavailable")
        return row

    def get_expert(self, assessment_id: str, principal_id: str) -> dict:
        with self._connection() as db:
            row = self._assigned(db, assessment_id, principal_id)
            answers = db.execute("SELECT question_id,option_id FROM expert_answers WHERE assessment_id=? ORDER BY question_id",
                                 (assessment_id,)).fetchall()
            return {"id": row["id"], "cycle_id": row["cycle_id"], "template_id": row["template_id"],
                    "version": row["version"], "status": row["status"], "revision": row["revision"],
                    "answers": [dict(answer) for answer in answers]}

    def update_expert(self, assessment_id: str, principal_id: str, payload: ExpertUpdate) -> int:
        validate_answers(payload.template_id, payload.version, payload.answers, complete=False)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = self._assigned(db, assessment_id, principal_id)
                if row["status"] != "draft":
                    raise PrototypeError(409, "Assessment finalized")
                if (row["template_id"], row["version"]) != (payload.template_id, payload.version):
                    raise PrototypeError(422, "Template does not match assessment")
                if row["revision"] != payload.expected_revision:
                    raise PrototypeError(409, "Revision conflict")
                db.execute("DELETE FROM expert_answers WHERE assessment_id=?", (assessment_id,))
                db.executemany("INSERT INTO expert_answers VALUES (?,?,?)",
                               [(assessment_id, a.question_id, a.option_id) for a in payload.answers])
                db.execute("UPDATE expert_assessments SET revision=revision+1 WHERE id=?", (assessment_id,))
                db.execute("INSERT INTO expert_audit_events(assessment_id,actor_id,action,created_at) VALUES (?,?,?,?)",
                           (assessment_id, principal_id, "answers_updated", int(time.time())))
                db.commit()
                return row["revision"] + 1
            except Exception:
                db.rollback()
                raise

    def finalize_expert(self, assessment_id: str, principal_id: str) -> None:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = self._assigned(db, assessment_id, principal_id)
                if row["status"] != "draft":
                    raise PrototypeError(409, "Assessment finalized")
                answers = [Answer(**dict(answer)) for answer in db.execute(
                    "SELECT question_id,option_id FROM expert_answers WHERE assessment_id=?", (assessment_id,))]
                validate_answers(row["template_id"], row["version"], answers, complete=True)
                db.execute("UPDATE expert_assessments SET status='finalized',revision=revision+1 WHERE id=?", (assessment_id,))
                db.execute("INSERT INTO expert_audit_events(assessment_id,actor_id,action,created_at) VALUES (?,?,?,?)",
                           (assessment_id, principal_id, "finalized", int(time.time())))
                db.commit()
            except Exception:
                db.rollback()
                raise


def create_prototype_app(db_path: Path, secret: bytes,
                         allowed_origin: str = "http://testserver") -> tuple[FastAPI, PrototypeStore]:
    """Create an unmounted test-only FastAPI app and its fixture-controlled store."""
    store = PrototypeStore(db_path, secret)
    app = FastAPI(title="Official and Expert Prototype ONLY", docs_url=None, redoc_url=None)

    @app.exception_handler(PrototypeError)
    async def prototype_error(_request: Request, error: PrototypeError):
        return JSONResponse(status_code=error.status, content={"detail": error.detail})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _error: RequestValidationError):
        # Never echo the token or response body through framework error details.
        return JSONResponse(status_code=422, content={"detail": "Invalid request"})

    def expert_session(request: Request, *, mutation: bool) -> TestSession:
        session = store.sessions.get(request.cookies.get("prototype_session", ""))
        if session is None or session.expires_at <= int(time.time()):
            raise PrototypeError(401, "Session required")
        if not session.two_factor_verified:
            raise PrototypeError(403, "2FA required")
        if mutation:
            origin = request.headers.get("Origin")
            referer = request.headers.get("Referer")
            if origin is None and referer:
                parsed = urlsplit(referer)
                origin = f"{parsed.scheme}://{parsed.netloc}"
            if origin != allowed_origin:
                raise PrototypeError(403, "Origin required")
        if mutation and not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), session.csrf_token):
            raise PrototypeError(403, "CSRF required")
        return session

    def check_assessment_id(assessment_id: str) -> None:
        if not 1 <= len(assessment_id) <= 64:
            raise PrototypeError(422, "Invalid assessment ID")

    @app.post("/prototype/official/submissions", status_code=201)
    def submit(payload: OfficialSubmission, request: Request):
        if request.headers.get("Cookie") or request.headers.get("Authorization"):
            raise PrototypeError(400, "Anonymous request required")
        store.submit(payload)
        return {"accepted": True}

    @app.get("/prototype/expert/assessments/{assessment_id}")
    def read_expert(assessment_id: str, request: Request):
        check_assessment_id(assessment_id)
        session = expert_session(request, mutation=False)
        return store.get_expert(assessment_id, session.principal_id)

    @app.put("/prototype/expert/assessments/{assessment_id}/answers")
    def put_expert(assessment_id: str, payload: ExpertUpdate, request: Request):
        check_assessment_id(assessment_id)
        session = expert_session(request, mutation=True)
        return {"revision": store.update_expert(assessment_id, session.principal_id, payload)}

    @app.post("/prototype/expert/assessments/{assessment_id}/finalize")
    def finalize_expert(assessment_id: str, request: Request):
        check_assessment_id(assessment_id)
        session = expert_session(request, mutation=True)
        store.finalize_expert(assessment_id, session.principal_id)
        return {"status": "finalized"}

    return app, store
