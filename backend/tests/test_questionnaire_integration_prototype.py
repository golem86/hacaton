"""Synthetic-only integration, schema migration, privacy and security tests."""
from __future__ import annotations

import concurrent.futures
import hashlib
import logging
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.request_security import session_csrf_token
from app.v2_auth import (create_session, create_user, delete_session, migrate_auth_db,
                         rotate_session_after_2fa, session_cookie_name)
from prototypes.official_expert import CATALOG
from prototypes.questionnaire_integration import (
    DDL, GUARD_TABLE, MIGRATION_TABLES, ExpertAnswers, InMemoryRateLimiter,
    IntegrationError, IntegrationStore, SyntheticSubmission,
    apply_questionnaire_migration, core_snapshot, create_integration_test_app,
    create_synthetic_schema3_copy, create_synthetic_schema3_source,
    restore_synthetic_backup, suppress_cells,
)


FORM1 = "appendix-v-form-1"
VERSION = "2.0.0"
SYNTHETIC_CODE = "synthetic-assessment-code"


def fixture_questions() -> list[dict]:
    questions = []
    for index, (question_id, option_ids) in enumerate(CATALOG[(FORM1, VERSION)].items(), start=1):
        questions.append({
            "id": question_id,
            "section": f"section-{1 if index <= 5 else 2}",
            "text": f"Synthetic prompt {index}",
            "source_duplicate": index in {4, 5},
            "options": [{"id": option_id, "text": f"Synthetic option {option_id}"}
                        for option_id in sorted(option_ids)],
        })
    return questions


def answer_payload() -> list[dict[str, str]]:
    return [{"question_id": question_id, "option_id": sorted(options)[0]}
            for question_id, options in CATALOG[(FORM1, VERSION)].items()]


@pytest.fixture
def migrated_db(tmp_path: Path):
    source = create_synthetic_schema3_source(tmp_path / "seed.schema3-synthetic.sqlite")
    source_digest = __import__("hashlib").sha256(source.read_bytes()).hexdigest()
    target = tmp_path / "integration.prototype.sqlite"
    create_synthetic_schema3_copy(source, target)
    before = core_snapshot(target)
    migration = apply_questionnaire_migration(target, allow_test_migration=True)
    assert migration["action"] == "migrated"
    store = IntegrationStore(target)
    store.seed_template(FORM1, VERSION, 1, fixture_questions())
    store.bind_cycle(1, FORM1, VERSION)
    with sqlite3.connect(target) as con:
        con.execute("UPDATE cycles SET status='open' WHERE id=1")
    return target, store, before, migration, source, source_digest


@pytest.fixture
def integration(migrated_db):
    db_path, store, before, migration, source, source_digest = migrated_db
    app, store = create_integration_test_app(db_path, store)
    return TestClient(app), store, db_path, before, migration, source, source_digest


def _official_body(code: str = SYNTHETIC_CODE, *, category="staff", version=VERSION,
                   template=FORM1, answers=None):
    return {"template_id": template, "version": version, "category": category,
            "code": code, "answers": answers if answers is not None else answer_payload()}


def _seed_additional_code(db_path: Path, code: str, *, expires="2030-01-01 00:00:00", category="staff"):
    with sqlite3.connect(db_path) as con:
        token_id = con.execute("INSERT INTO access_tokens(cycle_id,token,used) VALUES (1,?,0)", (code,)).lastrowid
        con.execute("INSERT INTO access_token_policies(token_id,category,expires_at) VALUES (?,?,?)",
                    (token_id, category, expires))


def _auth_admin_and_expert(monkeypatch, tmp_path: Path):
    auth_path = tmp_path / "v2-auth-test.sqlite"
    monkeypatch.setenv("V2_AUTH_DB", str(auth_path))
    monkeypatch.setenv("V2_AUTH_SECURE_COOKIE", "0")
    migrate_auth_db()
    admin = create_user("Synthetic Admin", "admin.synthetic@example.test", "Test-password-01!", role="admin")
    expert = create_user("Synthetic Expert", "expert.synthetic@example.test", "Test-password-02!", role="user")
    outsider = create_user("Synthetic Outsider", "outsider.synthetic@example.test", "Test-password-03!", role="user")
    admin_token, _ = create_session(admin["id"], two_factor_verified=True)
    expert_pending, _ = create_session(expert["id"], two_factor_verified=False)
    expert_old, _ = create_session(expert["id"], two_factor_verified=False)
    expert_token, _ = rotate_session_after_2fa(expert_old, expert["id"])
    outsider_token, _ = create_session(outsider["id"], two_factor_verified=True)
    return admin, expert, outsider, admin_token, expert_pending, expert_token, outsider_token


def _auth_headers(token: str, *, csrf=True, origin="http://testserver") -> dict[str, str]:
    result = {"Origin": origin}
    if csrf:
        result["X-CSRF-Token"] = session_csrf_token(token)
    return result


def test_schema3_migration_backup_preservation_constraints_and_idempotency(migrated_db):
    db_path, _store, before, migration, source, source_digest = migrated_db
    assert migration["core_tables_preserved"] == len(before) == len(CORE_TABLES_FOR_TEST)
    assert Path(migration["backup"]).exists()
    assert core_snapshot(Path(migration["backup"])) == before
    current = core_snapshot(db_path)
    assert {key: value for key, value in current.items() if key != "cycles"} == {
        key: value for key, value in before.items() if key != "cycles"
    }
    assert current["cycles"][0] == before["cycles"][0]
    assert __import__("hashlib").sha256(source.read_bytes()).hexdigest() == source_digest
    with sqlite3.connect(db_path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 3
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        assert MIGRATION_TABLES <= {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "assessments" not in tables
        cycle_fks = list(con.execute("PRAGMA foreign_key_list(cycle_questionnaires)"))
        assert any(row[2] == "cycles" and row[3] == "cycle_id" and row[4] == "id" for row in cycle_fks)
        assert con.execute("SELECT COUNT(*) FROM cycles").fetchone()[0] == 1
        assert con.execute("SELECT value FROM answers").fetchone()[0] == 4
        assert con.execute("SELECT used FROM access_tokens").fetchone()[0] == 0
        assert con.execute("SELECT action FROM audit_events").fetchone()[0] == "synthetic.seed"
        template_cols = {row[1] for row in con.execute("PRAGMA table_info(questionnaire_templates)")}
        assert not ({"score", "weight"} & template_cols)
        assert con.execute("SELECT version FROM questionnaire_prototype_meta").fetchone()[0] == 1
    assert apply_questionnaire_migration(db_path, allow_test_migration=True)["action"] == "already_applied"


CORE_TABLES_FOR_TEST = (
    "components", "questions", "cycles", "units", "response_sets", "answers",
    "access_tokens", "access_token_policies", "cycle_configs", "objective_indicators",
    "recommendations", "audit_events",
)


def test_migration_refuses_without_explicit_synthetic_guard(tmp_path: Path):
    source = create_synthetic_schema3_source(tmp_path / "guard.schema3-synthetic.sqlite")
    target = tmp_path / "guarded.prototype.sqlite"
    create_synthetic_schema3_copy(source, target)
    with pytest.raises(ValueError, match="Explicit permission"):
        apply_questionnaire_migration(target)
    with pytest.raises(ValueError, match="synthetic schema-3 copy"):
        apply_questionnaire_migration(tmp_path / "ordinary.prototype.sqlite", allow_test_migration=True)


@pytest.mark.parametrize("fail_at", ["ddl_1", "after_templates", "before_meta"])
def test_migration_failure_injection_rolls_back_and_backup_restores(fail_at, tmp_path: Path):
    source = create_synthetic_schema3_source(tmp_path / f"{fail_at}.schema3-synthetic.sqlite")
    target = tmp_path / f"{fail_at}.prototype.sqlite"
    create_synthetic_schema3_copy(source, target)
    before = core_snapshot(target)
    with pytest.raises(RuntimeError, match="Injected migration failure"):
        apply_questionnaire_migration(target, allow_test_migration=True, fail_at=fail_at)
    assert core_snapshot(target) == before
    with sqlite3.connect(target) as con:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not (MIGRATION_TABLES & tables)
        assert con.execute("PRAGMA user_version").fetchone()[0] == 3
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    backups = list(tmp_path.glob("*.verified-backup-*.sqlite"))
    assert len(backups) == 1
    restore_synthetic_backup(target, backups[0], allow_test_restore=True)
    assert core_snapshot(target) == before


def test_restore_removes_prototype_tables_and_preserves_synthetic_legacy_rows(migrated_db):
    db_path, _store, before, migration, _source, _digest = migrated_db
    restore_synthetic_backup(db_path, Path(migration["backup"]), allow_test_restore=True)
    assert core_snapshot(db_path) == before
    with sqlite3.connect(db_path) as con:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not (MIGRATION_TABLES & tables)
        assert con.execute("PRAGMA user_version").fetchone()[0] == 3
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_official_adapter_atomically_uses_existing_access_token_without_linking_answer(integration):
    client, _store, db_path, before, _migration, source, source_digest = integration
    response = client.post("/prototype/integration/cycles/1/official-submissions", json=_official_body())
    assert response.status_code == 201 and response.json() == {"accepted": True}, response.text
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT used FROM access_tokens WHERE token=?", (SYNTHETIC_CODE,)).fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM official_response_sets").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM official_answers").fetchone()[0] == 12
        assert con.execute("SELECT COUNT(*) FROM response_sets").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM answers").fetchone()[0] == 1
        set_columns = {r[1] for r in con.execute("PRAGMA table_info(official_response_sets)")}
        token_columns = {r[1] for r in con.execute("PRAGMA table_info(access_tokens)")}
        assert not ({"respondent_id", "user_id", "token", "ip", "created_at", "timestamp"} & set_columns)
        assert "response_set_id" not in token_columns
        assert con.execute("SELECT COUNT(*) FROM official_answers a JOIN answers n ON 1=1").fetchone()[0] == 12
    assert core_snapshot(db_path)["answers"] == before["answers"]
    assert __import__("hashlib").sha256(source.read_bytes()).hexdigest() == source_digest
    assert client.post("/prototype/integration/cycles/1/official-submissions", json=_official_body()).status_code == 403
    assert not any(getattr(route, "path", "").startswith("/api/assessments")
                   for route in client.app.routes)


@pytest.mark.parametrize("body,expected", [
    (_official_body(version="1.0.0"), 422),
    (_official_body(template="appendix-v-form-2"), 422),
    (_official_body(category="mgmt"), 403),
    (_official_body(answers=answer_payload()[:-1]), 422),
    (_official_body(answers=answer_payload() + answer_payload()[:1]), 422),
    (_official_body(answers=[{**answer_payload()[0], "option_id": "foreign-option"}] + answer_payload()[1:]), 422),
])
def test_adapter_rejects_wrong_cycle_category_version_or_answers(integration, body, expected):
    client, _store, db_path, _before, _migration, _source, _digest = integration
    response = client.post("/prototype/integration/cycles/1/official-submissions", json=body)
    assert response.status_code == expected
    assert SYNTHETIC_CODE not in response.text
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT used FROM access_tokens WHERE token=?", (SYNTHETIC_CODE,)).fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM official_response_sets").fetchone()[0] == 0


def test_expiry_closed_cycle_cookie_and_authorization_are_rejected(integration):
    client, store, db_path, _before, _migration, _source, _digest = integration
    _seed_additional_code(db_path, "synthetic-expired-code", expires="2000-01-01 00:00:00")
    expired = client.post("/prototype/integration/cycles/1/official-submissions",
                          json=_official_body(code="synthetic-expired-code"))
    assert expired.status_code == 403 and "synthetic-expired-code" not in expired.text
    assert client.post("/prototype/integration/cycles/1/official-submissions", json=_official_body(),
                       headers={"Authorization": "Bearer synthetic-auth"}).status_code == 400
    client.cookies.set("synthetic-cookie", "synthetic-cookie-secret")
    assert client.post("/prototype/integration/cycles/1/official-submissions", json=_official_body()).status_code == 400
    client.cookies.clear()
    store.close_cycle(1)
    _seed_additional_code(db_path, "synthetic-after-close")
    closed = client.post("/prototype/integration/cycles/1/official-submissions",
                         json=_official_body(code="synthetic-after-close"))
    assert closed.status_code == 409
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT used FROM access_tokens WHERE token='synthetic-after-close'").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM official_response_sets").fetchone()[0] == 0


def test_competing_submit_and_close_are_serialized(integration):
    _client, store, db_path, _before, _migration, _source, _digest = integration
    _seed_additional_code(db_path, "synthetic-race-a")
    _seed_additional_code(db_path, "synthetic-race-b")
    body_a = SyntheticSubmission(**_official_body(code="synthetic-race-a"))
    body_b = SyntheticSubmission(**_official_body(code="synthetic-race-b"))
    barrier = threading.Barrier(2)

    def submit():
        barrier.wait()
        try:
            store.submit(1, body_a)
            return "accepted"
        except IntegrationError as error:
            return error.status

    def close():
        barrier.wait()
        store.close_cycle(1)
        return "closed"

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(submit)
        second = pool.submit(close)
        outcomes = [first.result(timeout=15), second.result(timeout=15)]
    assert "closed" in outcomes
    assert "accepted" in outcomes or 409 in outcomes
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT status FROM cycles WHERE id=1").fetchone()[0] == "closed"
        accepted = con.execute("SELECT COUNT(*) FROM official_response_sets").fetchone()[0]
        assert accepted <= 1
    _seed_additional_code(db_path, "synthetic-late-code")
    with pytest.raises(IntegrationError) as late:
        store.submit(1, SyntheticSubmission(**_official_body(code="synthetic-late-code")))
    assert late.value.status == 409
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT used FROM access_tokens WHERE token='synthetic-late-code'").fetchone()[0] == 0


def test_same_code_race_and_mid_submit_failure_are_atomic(integration):
    _client, store, db_path, *_ = integration
    barrier = threading.Barrier(2)

    def submit_same_code():
        barrier.wait()
        try:
            store.submit(1, SyntheticSubmission(**_official_body()))
            return "accepted"
        except IntegrationError as error:
            return error.status

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(submit_same_code) for _ in range(2)]
        outcomes = [result.result(timeout=15) for result in results]
    assert outcomes.count("accepted") == 1
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT used FROM access_tokens WHERE token=?", (SYNTHETIC_CODE,)).fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM official_response_sets").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM official_answers").fetchone()[0] == 12

    # A database failure after response-set insertion must roll back the set and token state.
    _seed_additional_code(db_path, "synthetic-failure-code")
    with sqlite3.connect(db_path) as con:
        con.execute("CREATE TRIGGER reject_official_answer BEFORE INSERT ON official_answers "
                    "BEGIN SELECT RAISE(ABORT,'synthetic injected answer failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.submit(1, SyntheticSubmission(**_official_body(code="synthetic-failure-code")))
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT used FROM access_tokens WHERE token='synthetic-failure-code'").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM official_response_sets").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM official_answers").fetchone()[0] == 12
        con.execute("DROP TRIGGER reject_official_answer")


def test_global_and_per_cycle_rate_limits_without_ip_keys():
    now = [0.0]
    limiter = InMemoryRateLimiter(global_limit=3, cycle_limit=2, window_seconds=30, clock=lambda: now[0])
    assert limiter.allow("cycle-a")
    assert limiter.allow("cycle-a")
    assert not limiter.allow("cycle-a")  # per-cycle cap
    assert limiter.allow("cycle-b")
    assert not limiter.allow("cycle-c")  # global cap
    now[0] = 31.0
    assert limiter.allow("cycle-a")
    assert "cycle-b" not in limiter.cycle_events
    assert all("ip" not in str(key).lower() for key in limiter.cycle_events)


def test_throttled_http_attempts_do_not_write_answers_or_log_request_secrets(integration, caplog):
    client, store, db_path, _before, _migration, _source, _digest = integration
    store.rate_limiter = InMemoryRateLimiter(global_limit=20, cycle_limit=2)
    caplog.set_level(logging.WARNING, logger="questionnaire.prototype")
    _seed_additional_code(db_path, "synthetic-throttle-a")
    _seed_additional_code(db_path, "synthetic-throttle-b")
    for code in ("synthetic-guess-1", "synthetic-guess-2"):
        assert client.post("/prototype/integration/cycles/1/official-submissions",
                           json=_official_body(code=code)).status_code == 403
    throttled = client.post("/prototype/integration/cycles/1/official-submissions",
                            json=_official_body(code="synthetic-throttle-a"))
    assert throttled.status_code == 429
    assert "synthetic-throttle-a" not in throttled.text
    log_text = caplog.text
    for secret in ("synthetic-guess-1", "synthetic-guess-2", "synthetic-throttle-a",
                   answer_payload()[0]["option_id"], "X-CSRF-Token", "Authorization", "synthetic-cookie-secret"):
        assert secret not in log_text
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM official_response_sets").fetchone()[0] == 0
        columns = {r[1] for r in con.execute("PRAGMA table_info(official_response_sets)")}
        assert not ({"ip", "user_agent", "cookie", "authorization", "csrf", "person_id"} & columns)


def test_template_and_answer_constraints_are_enforced(migrated_db):
    db_path, store, *_ = migrated_db
    with sqlite3.connect(db_path) as con:
        con.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("UPDATE questionnaire_templates SET content_sha256=? WHERE template_id=?",
                        ("0" * 64, FORM1))
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO questionnaire_questions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (FORM1, VERSION, "foreign", "section", 99, 53, 99, "single_choice", 1, 0, "text"))
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO cycle_questionnaires VALUES (?,?,?)", (999, FORM1, VERSION))
    assert store is not None


def test_suppression_primary_complementary_intersections_and_no_raw_api(integration):
    client, _store, _db_path, *_ = integration
    output = suppress_cells([("tiny-category", 2), ("medium-category", 8), ("large-category", 10)], k=5)
    hidden = [group for group in output["groups"] if group["suppressed"]]
    assert len(hidden) == 2  # primary + complementary
    assert all(group["count"] is None and group["label"] == "недостатньо відповідей" for group in hidden)
    assert not any("tiny-category" in str(group) or "medium-category" in str(group) for group in output["groups"])
    small_total = suppress_cells([("unit-a/category-a", 1), ("unit-b/category-b", 2)], k=5)
    assert small_total["total"] is None and all(g["count"] is None for g in small_total["groups"])
    route_paths = {getattr(route, "path", "") for route in client.app.routes}
    assert not any("dashboard" in p or "raw" in p or "responses" in p for p in route_paths)
    assert all("official" not in p or "submissions" in p for p in route_paths if p.startswith("/prototype"))


def test_purge_is_transactional_cascades_official_rows_and_is_test_only(integration):
    client, store, db_path, *_ = integration
    assert client.post("/prototype/integration/cycles/1/official-submissions", json=_official_body()).status_code == 201
    with sqlite3.connect(db_path) as con:
        assert con.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
    store.close_cycle(1)
    with pytest.raises(ValueError, match="Explicit test-only"):
        store.purge_closed_cycle(1)
    with pytest.raises(RuntimeError, match="Injected purge failure"):
        store.purge_closed_cycle(1, allow_test_purge=True, fail_after_sets=True)
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM official_response_sets").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM official_answers").fetchone()[0] == 12
    result = store.purge_closed_cycle(1, allow_test_purge=True)
    assert result == {"response_sets_purged": 1, "access_tokens_purged": 1}
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM official_response_sets").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM official_answers").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM access_tokens WHERE cycle_id=1").fetchone()[0] == 0
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    from prototypes.questionnaire_integration import create_verified_backup
    backup = create_verified_backup(db_path, allow_test_migration=True)
    with sqlite3.connect(backup) as con:
        assert con.execute("SELECT COUNT(*) FROM official_response_sets").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM official_answers").fetchone()[0] == 0


def test_real_v2_sessions_admin_csrf_explicit_expert_grant_and_assignment(migrated_db, monkeypatch, tmp_path):
    db_path, store, *_ = migrated_db
    app, store = create_integration_test_app(db_path, store)
    admin, expert, outsider, admin_token, pending_token, expert_token, outsider_token = \
        _auth_admin_and_expert(monkeypatch, tmp_path)
    client = TestClient(app)
    route = "/prototype/integration/expert/assessments"
    client.cookies.set(session_cookie_name(), admin_token)
    no_admin_access = client.get(route + "/does-not-exist", headers={"X-Role": "expert"})
    assert no_admin_access.status_code == 404  # admin is not implicitly an expert
    assert client.post(f"/prototype/integration/expert/grants/{admin['id']}",
                       headers=_auth_headers(admin_token)).status_code == 403  # no self grant
    client.cookies.clear()
    client.cookies.set(session_cookie_name(), admin_token)
    no_csrf = client.post(f"/prototype/integration/expert/grants/{expert['id']}", headers={"Origin": "http://testserver"})
    assert no_csrf.status_code == 403
    bad_origin = client.post(f"/prototype/integration/expert/grants/{expert['id']}",
                             headers=_auth_headers(admin_token, origin="https://evil.example"))
    assert bad_origin.status_code == 403
    assert client.post(f"/prototype/integration/expert/grants/{expert['id']}",
                       headers={"X-Role": "admin"}).status_code == 403
    granted = client.post(f"/prototype/integration/expert/grants/{expert['id']}",
                          headers=_auth_headers(admin_token))
    assert granted.status_code == 200
    assignment = client.post(f"/prototype/integration/expert/assignments/1/{FORM1}/{VERSION}",
                             params={"principal_id": str(expert["id"])}, headers=_auth_headers(admin_token))
    assert assignment.status_code == 200
    with sqlite3.connect(db_path) as con:
        assessment_id = con.execute("SELECT assessment_id FROM expert_assessments").fetchone()[0]
    client.cookies.clear()
    client.cookies.set(session_cookie_name(), pending_token)
    assert client.get(route + f"/{assessment_id}").status_code == 403
    client.cookies.clear()
    client.cookies.set(session_cookie_name(), outsider_token)
    assert client.get(route + f"/{assessment_id}").status_code == 404
    client.cookies.clear()
    client.cookies.set(session_cookie_name(), expert_token)
    assert client.get(route + f"/{assessment_id}", headers={"X-Role": "admin"}).status_code == 200
    with sqlite3.connect(tmp_path / "v2-auth-test.sqlite") as auth:
        auth.execute("UPDATE v2_sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE token_hash=(SELECT token_hash FROM v2_sessions WHERE user_id=? LIMIT 1)",
                     (outsider["id"],))
    client.cookies.set(session_cookie_name(), "synthetic-invalid-session")
    assert client.get(route + f"/{assessment_id}").status_code == 401
    client.cookies.set(session_cookie_name(), outsider_token)
    with sqlite3.connect(tmp_path / "v2-auth-test.sqlite") as auth:
        token_hash = hashlib.sha256(outsider_token.encode()).hexdigest()
        auth.execute("UPDATE v2_sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE token_hash=?",
                     (token_hash,))
    assert client.get(route + f"/{assessment_id}").status_code == 401


def test_expert_revision_finalize_audit_and_revocation_block_next_request(migrated_db, monkeypatch, tmp_path):
    db_path, store, *_ = migrated_db
    app, store = create_integration_test_app(db_path, store)
    admin, expert, _outsider, admin_token, _pending, expert_token, _out_token = \
        _auth_admin_and_expert(monkeypatch, tmp_path)
    admin_client = TestClient(app)
    admin_client.cookies.set(session_cookie_name(), admin_token)
    assert admin_client.post(f"/prototype/integration/expert/grants/{expert['id']}",
                             headers=_auth_headers(admin_token)).status_code == 200
    assigned = admin_client.post(f"/prototype/integration/expert/assignments/1/{FORM1}/{VERSION}",
                                 params={"principal_id": str(expert["id"])}, headers=_auth_headers(admin_token))
    with sqlite3.connect(db_path) as con:
        assessment_id = con.execute("SELECT assessment_id FROM expert_assessments").fetchone()[0]
    expert_client = TestClient(app)
    expert_client.cookies.set(session_cookie_name(), expert_token)
    route = f"/prototype/integration/expert/assessments/{assessment_id}"
    no_csrf = expert_client.put(route + "/answers", json={"expected_revision": 0, "answers": answer_payload()[:1]})
    assert no_csrf.status_code == 403
    stale_origin = expert_client.put(route + "/answers", json={"expected_revision": 0, "answers": answer_payload()[:1]},
                                     headers=_auth_headers(expert_token, origin="https://evil.example"))
    assert stale_origin.status_code == 403
    headers = _auth_headers(expert_token)
    partial = {"expected_revision": 0, "answers": answer_payload()[:1]}
    assert expert_client.put(route + "/answers", json=partial, headers=headers).json() == {"revision": 1}
    assert expert_client.put(route + "/answers", json=partial, headers=headers).status_code == 409
    assert expert_client.post(route + "/finalize", headers=headers).status_code == 422
    complete = {"expected_revision": 1, "answers": answer_payload()}
    assert expert_client.put(route + "/answers", json=complete, headers=headers).json() == {"revision": 2}
    assert expert_client.post(route + "/finalize", headers=headers).json() == {"status": "finalized"}
    assert expert_client.post(route + "/finalize", headers=headers).status_code == 409
    assert expert_client.put(route + "/answers", json={"expected_revision": 2, "answers": answer_payload()}, headers=headers).status_code == 409
    with sqlite3.connect(db_path) as con:
        audit = con.execute("SELECT action,created_at FROM expert_audit_events ORDER BY id").fetchall()
        assert [row[0] for row in audit] == ["grant", "assign", "answers_updated", "answers_updated", "finalized"]
        assert all(row[1] > 0 for row in audit)
        assert con.execute("SELECT COUNT(*) FROM official_answers").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM expert_answers").fetchone()[0] == 12
    revoked = admin_client.delete(f"/prototype/integration/expert/grants/{expert['id']}",
                                  headers=_auth_headers(admin_token))
    assert revoked.status_code == 200
    assert expert_client.get(route).status_code == 404  # same still-valid V2 session, grant is rechecked
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT status FROM expert_assignments").fetchone()[0] == "revoked"
        assert con.execute("SELECT action FROM expert_audit_events ORDER BY id DESC LIMIT 1").fetchone()[0] == "revoke"
    assert assigned.status_code == 200


def test_admin_needs_explicit_grant_and_revoked_v2_session_is_rejected(migrated_db, monkeypatch, tmp_path):
    db_path, store, *_ = migrated_db
    app, store = create_integration_test_app(db_path, store)
    admin, expert, _outsider, admin_token, _pending, expert_token, _out = \
        _auth_admin_and_expert(monkeypatch, tmp_path)
    client = TestClient(app)
    client.cookies.set(session_cookie_name(), admin_token)
    with pytest.raises(IntegrationError):
        store.assign_expert(str(admin["id"]), 1, FORM1, VERSION, "synthetic-authority")
    assert client.post(f"/prototype/integration/expert/grants/{admin['id']}",
                       headers=_auth_headers(admin_token)).status_code == 403
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM expert_permissions WHERE principal_id=?",
                           (str(admin["id"]),)).fetchone()[0] == 0
    client.cookies.clear()
    client.cookies.set(session_cookie_name(), expert_token)
    delete_session(expert_token)
    assert client.get("/prototype/integration/expert/assessments/nope").status_code == 401
    assert expert["id"]


def test_published_template_binding_and_version_isolation(migrated_db):
    db_path, store, *_ = migrated_db
    with sqlite3.connect(db_path) as con:
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("UPDATE cycle_questionnaires SET version='9.9.9' WHERE cycle_id=1")
        with pytest.raises(sqlite3.IntegrityError):
            question_id, option_id = con.execute(
                "SELECT question_id,option_id FROM questionnaire_options WHERE template_id=? AND version=? LIMIT 1",
                (FORM1, VERSION)).fetchone()
            con.execute("DELETE FROM questionnaire_options WHERE template_id=? AND version=? AND question_id=? AND option_id=?",
                        (FORM1, VERSION, question_id, option_id))
    with pytest.raises(IntegrationError) as mismatch:
        store.submit(1, SyntheticSubmission(**_official_body(version="9.9.9")))
    assert mismatch.value.status in {409, 422}
