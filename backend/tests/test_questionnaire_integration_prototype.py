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

from app.migrations import SCHEMA_VERSION
from app.models import hash_access_code
from app.request_security import session_csrf_token
from app.v2_auth import (create_session, create_user, delete_session, migrate_auth_db,
                         rotate_session_after_2fa, session_cookie_name)
from prototypes.official_expert import CATALOG
from prototypes.questionnaire_integration import (
    DDL, GUARD_TABLE, MIGRATION_TABLES, PROTOTYPE_SCHEMA_VERSION, ExpertAnswers, InMemoryRateLimiter,
    IntegrationError, IntegrationStore, SyntheticSubmission,
    apply_questionnaire_migration, core_snapshot, create_integration_test_app,
    create_synthetic_schema5_copy, create_synthetic_schema5_source,
    restore_synthetic_backup, suppress_cells, SQLiteRateLimiter,
)


FORM1 = "appendix-v-form-1"
VERSION = "2.0.0"
SYNTHETIC_CODE = "synthetic-assessment-code"


def fixture_questions(form: str = FORM1, version: str = VERSION) -> list[dict]:
    questions = []
    for index, (question_id, option_ids) in enumerate(CATALOG[(form, version)].items(), start=1):
        questions.append({
            "id": question_id,
            "section": f"section-{1 if index <= 5 else 2}",
            "text": f"Synthetic prompt {index}",
            "source_duplicate": form == FORM1 and index in {4, 5},
            "options": [{"id": option_id, "text": f"Synthetic option {option_id}"}
                        for option_id in sorted(option_ids)],
        })
    return questions


def answer_payload() -> list[dict[str, str]]:
    return [{"question_id": question_id, "option_id": sorted(options)[0]}
            for question_id, options in CATALOG[(FORM1, VERSION)].items()]


@pytest.fixture
def migrated_db(tmp_path: Path):
    source = create_synthetic_schema5_source(tmp_path / "seed.schema5-synthetic.sqlite")
    source_digest = __import__("hashlib").sha256(source.read_bytes()).hexdigest()
    target = tmp_path / "integration.prototype.sqlite"
    create_synthetic_schema5_copy(source, target)
    before = core_snapshot(target)
    migration = apply_questionnaire_migration(target, allow_test_migration=True)
    assert migration["action"] == "migrated"
    store = IntegrationStore(target)
    store.seed_template(FORM1, VERSION, 1, fixture_questions())
    store.bind_cycle(1, FORM1, VERSION)
    store.activate_cycle(1)
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
        token_id = con.execute("INSERT INTO access_tokens(cycle_id,token_hash,used) VALUES (1,?,0)",
                               (hash_access_code(code),)).lastrowid
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


def test_schema5_migration_backup_preservation_constraints_and_idempotency(migrated_db):
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
        assert con.execute("PRAGMA user_version").fetchone()[0] == PROTOTYPE_SCHEMA_VERSION
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


def test_prototype_pins_current_integrity_schema_version():
    assert PROTOTYPE_SCHEMA_VERSION == SCHEMA_VERSION == 7


CORE_TABLES_FOR_TEST = (
    "components", "questions", "cycles", "units", "response_sets", "answers",
    "access_tokens", "access_token_policies", "cycle_configs", "objective_indicators",
    "recommendations", "recommendation_actions", "audit_events", "instance_meta",
)


def test_migration_refuses_without_explicit_synthetic_guard(tmp_path: Path):
    source = create_synthetic_schema5_source(tmp_path / "guard.schema5-synthetic.sqlite")
    target = tmp_path / "guarded.prototype.sqlite"
    create_synthetic_schema5_copy(source, target)
    with pytest.raises(ValueError, match="Explicit permission"):
        apply_questionnaire_migration(target)
    with pytest.raises(ValueError, match="synthetic schema-5 copy"):
        apply_questionnaire_migration(tmp_path / "ordinary.prototype.sqlite", allow_test_migration=True)


def test_synthetic_database_helpers_fail_closed_on_protected_or_non_temp_paths(tmp_path, monkeypatch):
    protected = tmp_path / "would-be-integrity.schema5-synthetic.sqlite"
    monkeypatch.setenv("INTEGRITY_DB", str(protected))
    with pytest.raises(ValueError, match="Production/shared"):
        create_synthetic_schema5_source(protected)
    assert not protected.exists()

    monkeypatch.delenv("INTEGRITY_DB")
    protected_auth = tmp_path / "would-be-auth.schema5-synthetic.sqlite"
    monkeypatch.setenv("V2_AUTH_DB", str(protected_auth))
    with pytest.raises(ValueError, match="Production/shared"):
        create_synthetic_schema5_source(protected_auth)
    assert not protected_auth.exists()
    monkeypatch.delenv("V2_AUTH_DB")
    outside_temp = Path(__file__).resolve().parents[2] / "must-not-create.schema5-synthetic.sqlite"
    with pytest.raises(ValueError, match="temp directory"):
        create_synthetic_schema5_source(outside_temp)
    assert not outside_temp.exists()

    bogus_source = tmp_path / "unverified.schema5-synthetic.sqlite"
    with sqlite3.connect(bogus_source) as con:
        con.execute(f"PRAGMA user_version={PROTOTYPE_SCHEMA_VERSION}")
        con.execute("CREATE TABLE made_up(value TEXT)")
    copy_path = tmp_path / "unverified.prototype.sqlite"
    with pytest.raises(ValueError, match="expected schema-5 synthetic"):
        create_synthetic_schema5_copy(bogus_source, copy_path)
    assert not copy_path.exists()


def test_synthetic_source_symbolic_link_is_rejected(tmp_path):
    source = create_synthetic_schema5_source(tmp_path / "safe.schema5-synthetic.sqlite")
    alias = tmp_path / "alias.schema5-synthetic.sqlite"
    try:
        alias.symlink_to(source)
    except OSError as error:
        pytest.skip(f"Windows symlink creation unavailable in this environment: {error}")
    with pytest.raises(ValueError, match="Symbolic-link"):
        create_synthetic_schema5_copy(alias, tmp_path / "alias-copy.prototype.sqlite")
    assert not (tmp_path / "alias-copy.prototype.sqlite").exists()


@pytest.mark.parametrize("fail_at", ["ddl_1", "after_templates", "before_meta"])
def test_migration_failure_injection_rolls_back_and_backup_restores(fail_at, tmp_path: Path):
    source = create_synthetic_schema5_source(tmp_path / f"{fail_at}.schema5-synthetic.sqlite")
    target = tmp_path / f"{fail_at}.prototype.sqlite"
    create_synthetic_schema5_copy(source, target)
    before = core_snapshot(target)
    with pytest.raises(RuntimeError, match="Injected migration failure"):
        apply_questionnaire_migration(target, allow_test_migration=True, fail_at=fail_at)
    assert core_snapshot(target) == before
    with sqlite3.connect(target) as con:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not (MIGRATION_TABLES & tables)
        assert con.execute("PRAGMA user_version").fetchone()[0] == PROTOTYPE_SCHEMA_VERSION
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
        assert con.execute("PRAGMA user_version").fetchone()[0] == PROTOTYPE_SCHEMA_VERSION
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_official_adapter_atomically_uses_existing_access_token_without_linking_answer(integration):
    client, _store, db_path, before, _migration, source, source_digest = integration
    response = client.post("/prototype/integration/cycles/1/official-submissions", json=_official_body())
    assert response.status_code == 201 and response.json() == {"accepted": True}, response.text
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT used FROM access_tokens WHERE token_hash=?", (hash_access_code(SYNTHETIC_CODE),)).fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM official_response_sets").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM official_answers").fetchone()[0] == 12
        assert con.execute("SELECT COUNT(*) FROM response_sets").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM answers").fetchone()[0] == 1
        set_columns = {r[1] for r in con.execute("PRAGMA table_info(official_response_sets)")}
        token_columns = {r[1] for r in con.execute("PRAGMA table_info(access_tokens)")}
        assert not ({"respondent_id", "user_id", "token", "ip", "created_at", "timestamp"} & set_columns)
        assert "response_set_id" not in token_columns
        # Schema 5 stores only the SHA-256 of the one-time code; plaintext is never persisted.
        assert "token_hash" in token_columns and "token" not in token_columns
        assert con.execute("SELECT COUNT(*) FROM access_tokens WHERE token_hash=?", (SYNTHETIC_CODE,)).fetchone()[0] == 0
        assert con.execute("SELECT token_hash FROM access_tokens WHERE token_hash=?",
                           (hash_access_code(SYNTHETIC_CODE),)).fetchone()[0] == hash_access_code(SYNTHETIC_CODE)
        assert con.execute("SELECT COUNT(*) FROM official_answers a JOIN answers n ON 1=1").fetchone()[0] == 12
    assert core_snapshot(db_path)["answers"] == before["answers"]
    assert __import__("hashlib").sha256(source.read_bytes()).hexdigest() == source_digest
    assert client.post("/prototype/integration/cycles/1/official-submissions", json=_official_body()).status_code == 403
    assert not any(getattr(route, "path", "").startswith("/api/assessments")
                   for route in client.app.routes)


def test_official_sets_are_isolated_by_cycle_and_version(integration):
    client, store, db_path, *_ = integration
    with sqlite3.connect(db_path) as con:
        con.execute("INSERT INTO cycles(id,name,start_date,status,min_group_size) "
                    "VALUES (2,'Synthetic second cycle','2026-02-01','draft',5)")
        con.execute("INSERT INTO cycle_configs(cycle_id,description,scope,categories_json,questionnaire_version) "
                    "VALUES (2,'synthetic second','test','[\"staff\"]','demo-v1')")
        token_id = con.execute("INSERT INTO access_tokens(cycle_id,token_hash,used) VALUES (2,?,0)",
                               (hash_access_code("synthetic-cycle-2-code"),)).lastrowid
        con.execute("INSERT INTO access_token_policies(token_id,category,expires_at) "
                    "VALUES (?,?,datetime('now','+1 day'))", (token_id, "staff"))
    store.bind_cycle(2, FORM1, VERSION)
    store.activate_cycle(2)
    wrong_cycle = client.post("/prototype/integration/cycles/2/official-submissions", json=_official_body())
    wrong_version = client.post("/prototype/integration/cycles/2/official-submissions",
                                json=_official_body(code="synthetic-cycle-2-code", version="1.0.0"))
    assert wrong_cycle.status_code == 403  # cycle-1 code is never valid for cycle 2
    assert wrong_version.status_code == 422
    assert client.post("/prototype/integration/cycles/2/official-submissions",
                       json=_official_body(code="synthetic-cycle-2-code")).status_code == 201
    with sqlite3.connect(db_path) as con:
        sets = con.execute("SELECT cycle_id,template_id,version FROM official_response_sets ORDER BY cycle_id").fetchall()
        assert sets == [(2, FORM1, VERSION)]
        assert con.execute("SELECT used FROM access_tokens WHERE token_hash=?", (hash_access_code("synthetic-cycle-2-code"),)).fetchone()[0] == 1



@pytest.mark.parametrize(("cycle_id", "form", "code"), [
    (2, "appendix-v-form-1", "synthetic-form1-v21-code"),
    (3, "appendix-v-form-2", "synthetic-form2-v21-code"),
])
def test_full_2_1_catalog_submission_persists_after_reopening_sqlite(
        migrated_db, cycle_id, form, code):
    db_path, store, before, *_ = migrated_db
    store.seed_template(form, "2.1.0", 1 if form.endswith("1") else 2, fixture_questions(form, "2.1.0"))
    with sqlite3.connect(db_path) as con:
        con.execute("INSERT INTO cycles(id,name,start_date,status,min_group_size) "
                    "VALUES (?,?,'2026-02-01','draft',5)", (cycle_id, f"Synthetic cycle {cycle_id}"))
        con.execute("INSERT INTO cycle_configs(cycle_id,description,scope,categories_json,questionnaire_version) "
                    "VALUES (?,?,?,'[\"staff\"]','demo-v1')", (cycle_id, "synthetic", "test"))
        token_id = con.execute("INSERT INTO access_tokens(cycle_id,token_hash,used) VALUES (?,?,0)",
                               (cycle_id, hash_access_code(code))).lastrowid
        con.execute("INSERT INTO access_token_policies(token_id,category,expires_at) "
                    "VALUES (?,?,datetime('now','+1 day'))", (token_id, "staff"))
    store.bind_cycle(cycle_id, form, "2.1.0")
    store.activate_cycle(cycle_id)
    app, _ = create_integration_test_app(db_path, store)
    client = TestClient(app)
    payload = _official_body(code=code, template=form, version="2.1.0",
                             answers=[{"question_id": q, "option_id": sorted(options)[0]}
                                      for q, options in CATALOG[(form, "2.1.0")].items()])
    response = client.post(f"/prototype/integration/cycles/{cycle_id}/official-submissions", json=payload)
    assert response.status_code == 201, response.text
    # Verify durable state from a fresh SQLite connection, as after process restart.
    with sqlite3.connect(db_path) as reopened:
        assert reopened.execute("PRAGMA user_version").fetchone()[0] == PROTOTYPE_SCHEMA_VERSION
        stored = reopened.execute("SELECT cycle_id,template_id,version,category "
                                  "FROM official_response_sets").fetchall()
        assert stored == [(cycle_id, form, "2.1.0", "staff")]
        count = len(CATALOG[(form, "2.1.0")])
        assert count == (12 if form.endswith("1") else 10)
        assert reopened.execute("SELECT COUNT(*) FROM official_answers").fetchone()[0] == count
        assert reopened.execute("SELECT used FROM access_tokens WHERE token_hash=?",
                                (hash_access_code(code),)).fetchone()[0] == 1
        assert reopened.execute("SELECT COUNT(*) FROM access_tokens WHERE token_hash=?", (code,)).fetchone()[0] == 0
        columns = {r[1] for r in reopened.execute("PRAGMA table_info(official_response_sets)")}
        assert not ({"user_id", "respondent_id", "token", "token_hash", "created_at", "timestamp"} & columns)
    assert client.post(f"/prototype/integration/cycles/{cycle_id}/official-submissions",
                       json=payload).status_code == 403
    assert core_snapshot(db_path)["answers"] == before["answers"]

def test_expert_scope_is_limited_to_assigned_cycle_and_assessment(migrated_db, monkeypatch, tmp_path):
    db_path, store, *_ = migrated_db
    with sqlite3.connect(db_path) as con:
        con.execute("INSERT INTO cycles(id,name,start_date,status,min_group_size) "
                    "VALUES (2,'Synthetic expert cycle','2026-02-01','draft',5)")
        con.execute("INSERT INTO cycle_configs(cycle_id,description,scope,categories_json,questionnaire_version) "
                    "VALUES (2,'synthetic expert','test','[\"staff\"]','demo-v1')")
    store.bind_cycle(2, FORM1, VERSION)
    store.activate_cycle(2)
    admin, expert_a, expert_b, _admin_token, _pending, token_a, token_b = \
        _auth_admin_and_expert(monkeypatch, tmp_path)
    store.grant_expert(str(expert_a["id"]), str(admin["id"]))
    store.grant_expert(str(expert_b["id"]), str(admin["id"]))
    store.assign_expert(str(expert_a["id"]), 1, FORM1, VERSION, str(admin["id"]))
    store.assign_expert(str(expert_b["id"]), 2, FORM1, VERSION, str(admin["id"]))
    with sqlite3.connect(db_path) as con:
        ids = {row[0]: row[1] for row in con.execute(
            "SELECT ea.principal_id,a.assessment_id FROM expert_assignments ea "
            "JOIN expert_assessments a USING(assignment_id)")}
    app, _ = create_integration_test_app(db_path, store)
    client = TestClient(app)
    route = "/prototype/integration/expert/assessments/"
    client.cookies.set(session_cookie_name(), token_a)
    assert client.get(route + ids[str(expert_a["id"])]).status_code == 200
    assert client.get(route + ids[str(expert_b["id"])], headers={"X-Role": "admin"}).status_code == 404
    client.cookies.clear()
    client.cookies.set(session_cookie_name(), token_b)
    assert client.get(route + ids[str(expert_b["id"])]).status_code == 200
    assert client.get(route + ids[str(expert_a["id"])]).status_code == 404


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
        assert con.execute("SELECT used FROM access_tokens WHERE token_hash=?", (hash_access_code(SYNTHETIC_CODE),)).fetchone()[0] == 0
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
        assert con.execute("SELECT used FROM access_tokens WHERE token_hash=?", (hash_access_code("synthetic-after-close"),)).fetchone()[0] == 0
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
        assert con.execute("SELECT used FROM access_tokens WHERE token_hash=?", (hash_access_code("synthetic-late-code"),)).fetchone()[0] == 0


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
        assert con.execute("SELECT used FROM access_tokens WHERE token_hash=?", (hash_access_code(SYNTHETIC_CODE),)).fetchone()[0] == 1
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
        assert con.execute("SELECT used FROM access_tokens WHERE token_hash=?", (hash_access_code("synthetic-failure-code"),)).fetchone()[0] == 0
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


def test_sqlite_rate_limit_poc_is_atomic_across_worker_instances_and_expires(migrated_db):
    db_path, _store, *_ = migrated_db
    limiters = [SQLiteRateLimiter(db_path, global_limit=6, cycle_limit=4, window_seconds=60)
                for _ in range(12)]
    barrier = threading.Barrier(len(limiters))

    def request(limiter):
        barrier.wait()
        return limiter.allow("cycle-1")

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(limiters)) as pool:
        accepted = list(pool.map(request, limiters))
    assert sum(accepted) == 4
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT request_count FROM questionnaire_rate_limit_buckets "
                           "WHERE bucket_key='cycle:cycle-1'").fetchone()[0] == 4
        assert con.execute("SELECT request_count FROM questionnaire_rate_limit_buckets "
                           "WHERE bucket_key='global'").fetchone()[0] == 4
        names = {r[1] for r in con.execute("PRAGMA table_info(questionnaire_rate_limit_buckets)")}
        assert not ({"ip", "user_id", "token", "device_id"} & names)

    global_clock = [2_000_000_000.0]
    global_limiters = [SQLiteRateLimiter(db_path, global_limit=3, cycle_limit=10,
                                         window_seconds=10, clock=lambda: global_clock[0])
                       for _ in range(8)]
    global_barrier = threading.Barrier(len(global_limiters))

    def global_request(args):
        index, limiter = args
        global_barrier.wait()
        return limiter.allow(f"cycle-{index}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(global_limiters)) as pool:
        global_results = list(pool.map(global_request, enumerate(global_limiters)))
    assert sum(global_results) == 3
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT request_count FROM questionnaire_rate_limit_buckets "
                           "WHERE bucket_key='global' AND window_start=2000000000").fetchone()[0] == 3

    clock = [100.0]
    expiring = SQLiteRateLimiter(db_path, global_limit=2, cycle_limit=2,
                                 window_seconds=10, clock=lambda: clock[0])
    assert expiring.allow("ttl-cycle")
    clock[0] = 111.0
    assert expiring.allow("ttl-cycle")
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM questionnaire_rate_limit_buckets "
                           "WHERE bucket_key='cycle:ttl-cycle'").fetchone()[0] == 1


def test_sqlite_rate_limit_storage_failure_fails_closed(integration):
    client, _store, db_path, *_ = integration
    with sqlite3.connect(db_path) as con:
        con.execute("CREATE TRIGGER reject_limit_bucket BEFORE INSERT ON questionnaire_rate_limit_buckets "
                    "BEGIN SELECT RAISE(ABORT,'synthetic limiter unavailable'); END")
    response = client.post("/prototype/integration/cycles/1/official-submissions", json=_official_body())
    assert response.status_code == 503
    assert SYNTHETIC_CODE not in response.text
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT used FROM access_tokens WHERE token_hash=?", (hash_access_code(SYNTHETIC_CODE),)).fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM official_response_sets").fetchone()[0] == 0
        con.execute("DROP TRIGGER reject_limit_bucket")


def test_sqlite_rate_limit_http_response_is_generic_429(integration):
    client, store, db_path, *_ = integration
    store.rate_limiter = SQLiteRateLimiter(db_path, global_limit=10, cycle_limit=2)
    for code in ("synthetic-rate-guess-one", "synthetic-rate-guess-two"):
        response = client.post("/prototype/integration/cycles/1/official-submissions",
                               json=_official_body(code=code))
        assert response.status_code == 403
    limited = client.post("/prototype/integration/cycles/1/official-submissions",
                          json=_official_body(code="synthetic-assessment-code"))
    assert limited.status_code == 429
    assert "synthetic-assessment-code" not in limited.text
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT used FROM access_tokens WHERE token_hash=?", (hash_access_code(SYNTHETIC_CODE),)).fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM official_response_sets").fetchone()[0] == 0


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


@pytest.mark.parametrize("attack", [
    "category-differencing", "cross-cycle-differencing", "overlapping-filter",
    "repeated-query", "intersection-unit-category", "recover-hidden-count-from-total",
])
def test_aggregate_differencing_attack_surface_is_absent(attack, integration):
    client, _store, *_ = integration
    path = f"/prototype/integration/official-aggregates/{attack}"
    response = client.get(path, params={"cycle": "1", "category": "small-synthetic-group",
                                        "unit": "synthetic-unit", "repeat": "2"})
    assert response.status_code == 404
    assert "small-synthetic-group" not in response.text
    assert "count" not in response.text.lower()
    route_paths = {getattr(route, "path", "") for route in client.app.routes}
    assert not any("aggregate" in route or "participation" in route for route in route_paths)


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
    client.cookies.clear()
    client.cookies.set(session_cookie_name(), outsider_token)
    assert client.post(f"/prototype/integration/expert/grants/{expert['id']}",
                       headers={**_auth_headers(outsider_token), "X-Role": "admin"}).status_code == 403
    assert client.delete(f"/prototype/integration/expert/grants/{expert['id']}",
                         headers={**_auth_headers(outsider_token), "X-Role": "admin"}).status_code == 403
    client.cookies.clear()
    client.cookies.set(session_cookie_name(), admin_token)
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
    with sqlite3.connect(db_path) as con:
        con.execute("CREATE TRIGGER reject_expert_audit BEFORE INSERT ON expert_audit_events "
                    "WHEN NEW.action='answers_updated' BEGIN SELECT RAISE(ABORT,'synthetic audit failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        expert_client.put(route + "/answers", json=partial, headers=headers)
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT revision FROM expert_assessments WHERE assessment_id=?",
                           (assessment_id,)).fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM expert_answers WHERE assessment_id=?",
                           (assessment_id,)).fetchone()[0] == 0
        con.execute("DROP TRIGGER reject_expert_audit")
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


def test_concurrent_expert_grant_and_revoke_have_serial_audit_order(migrated_db, monkeypatch, tmp_path):
    db_path, store, *_ = migrated_db
    admin, expert, *_ = _auth_admin_and_expert(monkeypatch, tmp_path)
    store.grant_expert(str(expert["id"]), str(admin["id"]))
    barrier = threading.Barrier(2)

    def grant():
        barrier.wait()
        store.grant_expert(str(expert["id"]), str(admin["id"]))
        return "grant"

    def revoke():
        barrier.wait()
        store.revoke_expert(str(expert["id"]), str(admin["id"]))
        return "revoke"

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(grant), pool.submit(revoke)]
        [future.result(timeout=15) for future in futures]
    with sqlite3.connect(db_path) as con:
        final_action = con.execute("SELECT action FROM expert_audit_events "
                                   "WHERE target_principal_id=? ORDER BY id DESC LIMIT 1",
                                   (str(expert["id"]),)).fetchone()[0]
        enabled = con.execute("SELECT enabled FROM expert_permissions WHERE principal_id=?",
                              (str(expert["id"]),)).fetchone()[0]
        assert enabled == (1 if final_action == "grant" else 0)
        assert [r[0] for r in con.execute("SELECT action FROM expert_audit_events "
                                         "WHERE target_principal_id=? ORDER BY id",
                                         (str(expert["id"],)))] == ["grant", "grant", "revoke"] or \
               [r[0] for r in con.execute("SELECT action FROM expert_audit_events "
                                         "WHERE target_principal_id=? ORDER BY id",
                                         (str(expert["id"],)))] == ["grant", "revoke", "grant"]


def test_user_promoted_to_admin_keeps_old_verified_session_in_current_auth_contract(
        migrated_db, monkeypatch, tmp_path):
    """Document current V2 behavior in temp auth DB; promotion policy needs #5/auth-owner decision."""
    db_path, _store, *_ = migrated_db
    app, store = create_integration_test_app(db_path)
    admin, user, *_ = _auth_admin_and_expert(monkeypatch, tmp_path)
    client = TestClient(app)
    user_token = create_session(user["id"], two_factor_verified=True)[0]
    client.cookies.set(session_cookie_name(), user_token)
    assert client.post(f"/prototype/integration/expert/grants/{admin['id']}",
                       headers=_auth_headers(user_token)).status_code == 403
    with sqlite3.connect(tmp_path / "v2-auth-test.sqlite") as auth:
        auth.execute("UPDATE v2_users SET role='admin' WHERE id=?", (user["id"],))
    # Existing V2 lookup reads current role, while its verified-2FA session stays active.
    promoted = client.post(f"/prototype/integration/expert/grants/{admin['id']}",
                           headers=_auth_headers(user_token))
    assert promoted.status_code == 200


def test_auth_adapter_and_grant_refuse_default_or_missing_auth_db_without_opening_it(
        migrated_db, monkeypatch, tmp_path):
    from app.v2_auth import auth_db_path
    db_path, store, *_ = migrated_db
    app, _store = create_integration_test_app(db_path, store)
    monkeypatch.delenv("V2_AUTH_DB", raising=False)
    default_path = auth_db_path()
    before = (default_path.exists(), default_path.stat().st_size if default_path.exists() else None,
              default_path.stat().st_mtime_ns if default_path.exists() else None)
    client = TestClient(app)
    result = client.get("/prototype/integration/expert/assessments/nope")
    assert result.status_code == 503
    with pytest.raises(ValueError, match="explicit isolated V2_AUTH_DB"):
        store.grant_expert("1", "synthetic-actor")
    after = (default_path.exists(), default_path.stat().st_size if default_path.exists() else None,
             default_path.stat().st_mtime_ns if default_path.exists() else None)
    assert after == before

    outside = Path(__file__).resolve().parents[2] / "must-not-create-auth.sqlite"
    monkeypatch.setenv("V2_AUTH_DB", str(outside))
    with pytest.raises(ValueError, match="temporary test database"):
        store.grant_expert("1", "synthetic-actor")
    assert not outside.exists()


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
    with sqlite3.connect(db_path) as con:
        with pytest.raises(sqlite3.IntegrityError, match="requires draft"):
            con.execute("INSERT INTO cycle_questionnaires VALUES (1,?,?)", (FORM1, VERSION))
    with pytest.raises(IntegrationError) as late_bind:
        store.bind_cycle(1, FORM1, VERSION)
    assert late_bind.value.status == 409
    with pytest.raises(IntegrationError) as mismatch:
        store.submit(1, SyntheticSubmission(**_official_body(version="9.9.9")))
    assert mismatch.value.status in {409, 422}


def test_cycle_bind_and_activation_are_serialized_and_never_open_unbound(migrated_db):
    db_path, store, *_ = migrated_db
    with sqlite3.connect(db_path) as con:
        con.execute("INSERT INTO cycles(id,name,start_date,status,min_group_size) "
                    "VALUES (2,'Synthetic binding race','2026-02-01','draft',5)")
        con.execute("INSERT INTO cycle_configs(cycle_id,description,scope,categories_json,questionnaire_version) "
                    "VALUES (2,'synthetic','test','[\"staff\"]','demo-v1')")
    barrier = threading.Barrier(2)

    def bind():
        barrier.wait()
        try:
            store.bind_cycle(2, FORM1, VERSION)
            return "bound"
        except IntegrationError as error:
            return error.status

    def activate():
        barrier.wait()
        try:
            store.activate_cycle(2)
            return "open"
        except IntegrationError as error:
            return error.status

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(bind), pool.submit(activate)]
        outcomes = [future.result(timeout=15) for future in results]
    with sqlite3.connect(db_path) as con:
        status = con.execute("SELECT status FROM cycles WHERE id=2").fetchone()[0]
        bindings = con.execute("SELECT COUNT(*) FROM cycle_questionnaires WHERE cycle_id=2").fetchone()[0]
    assert outcomes in (["bound", "open"], ["bound", 409]), outcomes
    assert (status, bindings) in {("open", 1), ("draft", 1)}
    if status == "open":
        with sqlite3.connect(db_path) as con, pytest.raises(sqlite3.IntegrityError, match="requires draft"):
            con.execute("INSERT INTO cycle_questionnaires VALUES (2,?,?)", (FORM1, VERSION))
