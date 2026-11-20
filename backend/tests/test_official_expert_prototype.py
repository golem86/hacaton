"""Contract/security tests for the isolated, unmounted questionnaire prototype."""

from __future__ import annotations

import concurrent.futures
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from prototypes.official_expert import (
    CATALOG,
    ExpertUpdate,
    OfficialSubmission,
    PrototypeError,
    create_prototype_app,
)


FORM1 = "appendix-v-form-1"
FORM2 = "appendix-v-form-2"
VERSION = "2.0.0"


def answers(template_id: str = FORM1) -> list[dict[str, str]]:
    return [{"question_id": question_id, "option_id": sorted(options)[0]}
            for question_id, options in CATALOG[(template_id, VERSION)].items()]


def submission(token: str, *, cycle_id: str = "cycle-1", template_id: str = FORM1,
               category: str = "staff") -> dict:
    return {"cycle_id": cycle_id, "template_id": template_id, "version": VERSION,
            "category": category, "token": token, "answers": answers(template_id)}


@pytest.fixture
def prototype(tmp_path: Path):
    db_path = tmp_path / "official-expert.prototype.sqlite"
    app, store = create_prototype_app(db_path, b"synthetic-test-secret-only-2026")
    store.seed_cycle("cycle-1", FORM1)
    store.seed_code("cycle-1", "staff", "synthetic-code-001")
    return TestClient(app), store, db_path


def test_fixture_ids_match_frontend_v2_structure_and_production_has_no_route():
    source = (Path(__file__).parents[2] / "frontend/src/official/catalog-v2.ts").read_text(encoding="utf-8")
    assert source.count("section: 1, number:") == 8
    assert source.count("section: 2, number:") == 4
    assert source.count("section: 3, number:") == 8
    assert source.count("section: 4, number:") == 2
    assert [len(CATALOG[(form, VERSION)]) for form in (FORM1, FORM2)] == [12, 10]
    assert [len(CATALOG[(form, VERSION)][f"av-f{index}-accountability-3"])
            for index, form in enumerate((FORM1, FORM2), 1)] == [6, 6]
    from app.main import app as production_app
    assert not any(getattr(route, "path", "").startswith("/prototype/") for route in production_app.routes)


def test_prototype_refuses_a_non_prototype_database_path(tmp_path: Path):
    db_path = tmp_path / "integrity.db"
    with pytest.raises(ValueError, match="dedicated"):
        create_prototype_app(db_path, b"synthetic-test-secret-only-2026")
    assert not db_path.exists()


def test_official_submission_is_atomic_one_time_and_anonymous(prototype):
    client, _store, db_path = prototype
    payload = submission("synthetic-code-001")
    response = client.post("/prototype/official/submissions", json=payload)
    assert response.status_code == 201 and response.json() == {"accepted": True}
    assert client.post("/prototype/official/submissions", json=payload).status_code == 403
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM official_response_sets").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM official_answers").fetchone()[0] == 12
        assert db.execute("SELECT used FROM prototype_codes").fetchone()[0] == 1
        response_columns = {row[1] for row in db.execute("PRAGMA table_info(official_response_sets)")}
        assert response_columns == {"id", "cycle_id", "template_id", "version", "category"}
        code_columns = {row[1] for row in db.execute("PRAGMA table_info(prototype_codes)")}
        assert "response_set_id" not in code_columns
        assert "user_id" not in response_columns and "token" not in response_columns
    assert "synthetic-code-001" not in db_path.read_bytes().decode("latin1", errors="ignore")


@pytest.mark.parametrize("mutation", [
    lambda p: {**p, "version": "1.0.0"},
    lambda p: {**p, "template_id": FORM2},
    lambda p: {**p, "category": "mgmt"},
    lambda p: {**p, "answers": p["answers"][:-1]},
    lambda p: {**p, "answers": p["answers"] + p["answers"][:1]},
    lambda p: {**p, "answers": [{**p["answers"][0], "question_id": "unknown"}] + p["answers"][1:]},
    lambda p: {**p, "answers": [{**p["answers"][0], "option_id": "other-form-option"}] + p["answers"][1:]},
    lambda p: {**p, "user_id": "synthetic-user"},
    lambda p: {**p, "answers": [{**p["answers"][0], "free_text": "do not store"}] + p["answers"][1:]},
    lambda p: {**p, "token": "x" * 129},
    lambda p: {**p, "answers": [{**p["answers"][0], "question_id": "x" * 65}] + p["answers"][1:]},
])
def test_invalid_official_requests_reject_without_consuming_code(prototype, mutation):
    client, _store, db_path = prototype
    bad = mutation(submission("synthetic-code-001"))
    response = client.post("/prototype/official/submissions", json=bad)
    assert response.status_code in (403, 422)
    assert "synthetic-code-001" not in response.text
    assert "do not store" not in response.text
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM official_response_sets").fetchone()[0] == 0
        assert db.execute("SELECT used FROM prototype_codes").fetchone()[0] == 0


def test_expired_code_and_closed_cycle_reject(prototype):
    client, store, _db_path = prototype
    store.seed_code("cycle-1", "staff", "expired-code-001", expires_at=int(time.time()) - 1)
    assert client.post("/prototype/official/submissions", json=submission("expired-code-001")).status_code == 403
    store.close_cycle("cycle-1")
    assert client.post("/prototype/official/submissions", json=submission("synthetic-code-001")).status_code == 409


def test_anonymous_route_rejects_authenticated_browser_context(prototype):
    client, store, db_path = prototype
    session_id, _csrf = store.seed_session("someone", two_factor_verified=True)
    client.cookies.set("prototype_session", session_id)
    response = client.post("/prototype/official/submissions", json=submission("synthetic-code-001"))
    assert response.status_code == 400
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM official_response_sets").fetchone()[0] == 0


def test_competing_submissions_use_code_once(prototype):
    _client, store, db_path = prototype
    payload = OfficialSubmission(**submission("synthetic-code-001"))
    barrier = threading.Barrier(2)

    def submit_once():
        barrier.wait()
        try:
            store.submit(payload)
            return 201
        except PrototypeError as error:
            return error.status

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _i: submit_once(), range(2)))
    assert sorted(outcomes) == [201, 403]
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM official_response_sets").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM official_answers").fetchone()[0] == 12


def test_close_serializes_with_submit_and_prevents_late_acceptance(prototype):
    _client, store, db_path = prototype
    store.seed_code("cycle-1", "staff", "synthetic-code-002")
    first = OfficialSubmission(**submission("synthetic-code-001"))
    second = OfficialSubmission(**submission("synthetic-code-002"))
    barrier = threading.Barrier(2)

    def submit_race():
        barrier.wait()
        try:
            store.submit(first)
            return 201
        except PrototypeError as error:
            return error.status

    def close_race():
        barrier.wait()
        store.close_cycle("cycle-1")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        submit_future = pool.submit(submit_race)
        close_future = pool.submit(close_race)
        close_future.result()
        outcome = submit_future.result()
    assert outcome in (201, 409)
    with pytest.raises(PrototypeError) as error:
        store.submit(second)
    assert error.value.status == 409
    with sqlite3.connect(db_path) as db:
        before = db.execute("SELECT COUNT(*) FROM official_response_sets").fetchone()[0]
    assert before == (1 if outcome == 201 else 0)


def expert_client(prototype, principal: str, *, verified: bool = True) -> tuple[TestClient, str]:
    client, store, _db_path = prototype
    session_id, csrf = store.seed_session(principal, two_factor_verified=verified)
    client.cookies.set("prototype_session", session_id)
    client.headers.update({"Origin": "http://testserver"})
    return client, csrf


def test_expert_server_permissions_assignment_2fa_csrf_and_spoofing(prototype):
    client, store, _db_path = prototype
    store.seed_expert("expert-1")
    store.seed_expert("expert-2")
    store.seed_assessment("review-1", "cycle-1", FORM1, "expert-1")
    route = "/prototype/expert/assessments/review-1"
    assert client.get(route, headers={"X-Role": "expert"}).status_code == 401
    client, csrf = expert_client(prototype, "expert-1", verified=False)
    assert client.get(route).status_code == 403
    client, csrf = expert_client(prototype, "expert-1")
    assert client.get(route).status_code == 200
    update = {"template_id": FORM1, "version": VERSION, "expected_revision": 0, "answers": answers()[:1]}
    assert client.put(route + "/answers", json=update).status_code == 403
    assert client.put(route + "/answers", json=update, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.put(route + "/answers", json=update,
                      headers={"X-CSRF-Token": csrf, "Origin": "https://evil.example"}).status_code == 403
    assert client.put(route + "/answers", json=update, headers={"X-CSRF-Token": csrf}).status_code == 200
    client, csrf = expert_client(prototype, "expert-2")
    assert client.get(route, headers={"X-Role": "admin"}).status_code == 404
    assert client.put(route + "/answers", json=update, headers={"X-CSRF-Token": csrf}).status_code == 404
    client, csrf = expert_client(prototype, "unassigned-admin")
    assert client.get(route, headers={"X-Role": "expert"}).status_code == 404


def test_expert_expiry_and_revocation_are_server_controlled(prototype):
    client, store, _db_path = prototype
    store.seed_expert("expert-1")
    store.seed_assessment("review-1", "cycle-1", FORM1, "expert-1")
    expired, _csrf = store.seed_session("expert-1", two_factor_verified=True,
                                        expires_at=int(time.time()) - 1)
    client.cookies.set("prototype_session", expired)
    assert client.get("/prototype/expert/assessments/review-1").status_code == 401
    client, _csrf = expert_client(prototype, "expert-1")
    assert client.get("/prototype/expert/assessments/review-1").status_code == 200
    store.seed_expert("expert-1", enabled=False)
    assert client.get("/prototype/expert/assessments/review-1").status_code == 404


def test_expert_draft_revision_finalization_and_audit_isolation(prototype):
    client, store, db_path = prototype
    store.seed_expert("expert-1")
    store.seed_assessment("review-1", "cycle-1", FORM1, "expert-1")
    client, csrf = expert_client(prototype, "expert-1")
    route = "/prototype/expert/assessments/review-1"
    headers = {"X-CSRF-Token": csrf}
    partial = {"template_id": FORM1, "version": VERSION, "expected_revision": 0, "answers": answers()[:1]}
    assert client.put(route + "/answers", json=partial, headers=headers).json() == {"revision": 1}
    assert client.post(route + "/finalize", headers=headers).status_code == 422
    assert client.put(route + "/answers", json=partial, headers=headers).status_code == 409
    complete = {**partial, "expected_revision": 1, "answers": answers()}
    assert client.put(route + "/answers", json=complete, headers=headers).json() == {"revision": 2}
    assert client.post(route + "/finalize", headers=headers).json() == {"status": "finalized"}
    assert client.get(route).json()["status"] == "finalized"
    assert client.post(route + "/finalize", headers=headers).status_code == 409
    assert client.put(route + "/answers", json={**complete, "expected_revision": 3}, headers=headers).status_code == 409
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM expert_answers").fetchone()[0] == 12
        assert db.execute("SELECT COUNT(*) FROM official_answers").fetchone()[0] == 0
        audit_columns = {row[1] for row in db.execute("PRAGMA table_info(expert_audit_events)")}
        assert audit_columns == {"id", "assessment_id", "actor_id", "action", "created_at"}
        assert [row[0] for row in db.execute("SELECT action FROM expert_audit_events")] == [
            "answers_updated", "answers_updated", "finalized"]
        assert all(row[0] > 0 for row in db.execute("SELECT created_at FROM expert_audit_events"))


def test_expert_rejects_wrong_template_duplicate_and_foreign_option(prototype):
    client, store, db_path = prototype
    store.seed_expert("expert-1")
    store.seed_assessment("review-1", "cycle-1", FORM1, "expert-1")
    client, csrf = expert_client(prototype, "expert-1")
    route = "/prototype/expert/assessments/review-1/answers"
    base = {"template_id": FORM1, "version": VERSION, "expected_revision": 0, "answers": answers()[:1]}
    mutations = [
        {**base, "version": "1.0.0"},
        {**base, "template_id": FORM2},
        {**base, "answers": base["answers"] * 2},
        {**base, "answers": [{**base["answers"][0], "option_id": "foreign"}]},
    ]
    for body in mutations:
        assert client.put(route, json=body, headers={"X-CSRF-Token": csrf}).status_code == 422
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM expert_answers").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM expert_audit_events").fetchone()[0] == 0


def test_competing_expert_updates_accept_only_one_revision(prototype):
    _client, store, db_path = prototype
    store.seed_expert("expert-1")
    store.seed_assessment("review-1", "cycle-1", FORM1, "expert-1")
    payload = ExpertUpdate(template_id=FORM1, version=VERSION, expected_revision=0,
                           answers=answers()[:1])
    barrier = threading.Barrier(2)

    def update_once():
        barrier.wait()
        try:
            return store.update_expert("review-1", "expert-1", payload)
        except PrototypeError as error:
            return error.status

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _i: update_once(), range(2)))
    assert sorted(outcomes) == [1, 409]
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT revision FROM expert_assessments").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM expert_answers").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM expert_audit_events").fetchone()[0] == 1
