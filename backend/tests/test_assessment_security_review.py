"""P0: приховування участі, close/submit та оновлення синтетичної SQLite-БД."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from app.database import SessionLocal, engine
from app.main import app
from app.migrations import check_schema, migrate
from app.models import AccessToken, AuditEvent, Cycle, Question, ResponseSet, hash_access_code
from app.routes import assessments as assessments_routes

client = TestClient(app)
ADMIN = {"X-Role": "admin"}
DATA_OFFICER = {"X-Role": "data_officer"}


def new_cycle():
    response = client.post("/api/assessments", headers=ADMIN, json={
        "name": "Синтетичний P0", "start_date": date.today().isoformat(),
        "categories": ["cadets"], "min_group_size": 5, "questionnaire_version": "demo-v1"})
    assert response.status_code == 201
    cycle_id = response.json()["id"]
    assert client.post(f"/api/assessments/{cycle_id}/activate", headers=ADMIN).status_code == 200
    return cycle_id


def issue(cycle_id, count=1):
    response = client.post(f"/api/assessments/{cycle_id}/tokens", headers=DATA_OFFICER,
                           params={"count": count, "category": "cadets"})
    assert response.status_code == 201
    return response.json()["tokens"]


def submission(token):
    with SessionLocal() as db:
        answers = [{"question_id": q.id, "value": 3} for q in db.query(Question).filter_by(kind="survey")]
    return {"token": token, "respondent_category": "cadets", "unit": "Факультет 1",
            "questionnaire_version": "demo-v1", "answers": answers}


def test_small_participation_cannot_be_reconstructed_from_token_counts():
    cycle_id = new_cycle()
    path = f"/api/assessments/{cycle_id}"
    codes = issue(cycle_id, 6)
    for code in codes[:2]:
        assert client.post(path + "/submissions", json=submission(code)).status_code == 201
    for by_unit in (False, True):
        stats = client.get(path + "/participation", params={"by_unit": by_unit}, headers=ADMIN).json()
        assert stats["tokens_issued"] == 6
        assert stats["tokens_unused"] is None
        assert stats["responses_total"] is None
        assert stats["participation_percent"] is None
        assert stats["groups"] is None and stats["suppressed"] is True and stats["counts_exact"] is False
    assert client.post(path + "/close", headers=ADMIN).status_code == 200
    closed = client.get(path + "/participation", headers=ADMIN).json()
    assert closed["tokens_unused"] is None and closed["responses_total"] is None
    assert closed["groups"] is None and closed["suppressed"] is True and closed["counts_exact"] is True
    assert client.get(path + "/participation?by_unit=true", headers=ADMIN).json()["groups"] is None


def test_close_and_submit_race_preserves_transaction_and_blocks_later_submissions():
    cycle_id = new_cycle()
    path = f"/api/assessments/{cycle_id}"
    first, later = issue(cycle_id, 2)
    gate = Barrier(2)

    def submit_now():
        gate.wait()
        return client.post(path + "/submissions", json=submission(first)).status_code

    def close_now():
        gate.wait()
        return client.post(path + "/close", headers=ADMIN).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        submitted = pool.submit(submit_now)
        closed = pool.submit(close_now)
        submit_status, close_status = submitted.result(), closed.result()
    assert close_status == 200
    assert submit_status in (201, 403, 409)
    assert client.post(path + "/submissions", json=submission(later)).status_code == 409
    with SessionLocal() as db:
        saved = db.query(ResponseSet).filter_by(cycle_id=cycle_id).count()
        used = db.query(AccessToken).filter_by(cycle_id=cycle_id, used=True).count()
        assert saved == used == (1 if submit_status == 201 else 0)
        assert db.query(AccessToken).filter_by(token_hash=hash_access_code(later)).one().used is False


def test_close_between_status_read_and_token_write_issues_nothing(monkeypatch):
    """Закриття після першого читання статусу, але до запису кодів: 409, жодного коду й аудиту видачі."""
    cycle_id = new_cycle()
    original = assessments_routes.get_assessment
    closed = []

    def read_then_close(assessment_id, db):
        cycle = original(assessment_id, db)       # issue_tokens бачить status == "open"
        if not closed:
            with SessionLocal() as other:          # паралельний admin закриває цикл і фіксує зміну
                other.get(Cycle, assessment_id).status = "closed"
                other.commit()
            closed.append(True)
        return cycle

    with SessionLocal() as db:
        issued_before = db.query(AuditEvent).filter_by(assessment_id=cycle_id, action="tokens.issue").count()
    monkeypatch.setattr(assessments_routes, "get_assessment", read_then_close)
    response = client.post(f"/api/assessments/{cycle_id}/tokens", headers=DATA_OFFICER,
                           params={"count": 3, "category": "cadets"})
    monkeypatch.undo()
    assert closed and response.status_code == 409
    assert "tokens" not in response.json()
    with SessionLocal() as db:
        assert db.get(Cycle, cycle_id).status == "closed"
        assert db.query(AccessToken).filter_by(cycle_id=cycle_id).count() == 0
        assert db.query(AuditEvent).filter_by(assessment_id=cycle_id,
                                              action="tokens.issue").count() == issued_before == 0

def _snapshot(path):
    with sqlite3.connect(path) as con:
        return (con.execute("SELECT COUNT(*) FROM response_sets").fetchone()[0],
                con.execute("SELECT COUNT(*), SUM(value) FROM answers").fetchone(),
                con.execute("SELECT COUNT(*) FROM cycles").fetchone()[0])


def test_schema_2_to_current_keeps_synthetic_results_and_is_idempotent(tmp_path):
    source = engine.url.database
    target = tmp_path / "synthetic-v2.db"
    with sqlite3.connect(source) as original, sqlite3.connect(target) as copy:
        original.backup(copy)
    with sqlite3.connect(target) as con:
        con.execute("DROP TABLE access_token_policies")
        con.execute("DROP TABLE cycle_configs")
        con.execute("PRAGMA user_version = 2")
    before = _snapshot(target)
    copied_engine = create_engine(f"sqlite:///{target}")
    report = migrate(copied_engine)
    assert report["action"] == "migrated" and report["backup"]
    backup = report["backup"]
    assert _snapshot(backup) == before
    with sqlite3.connect(backup) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 2
    assert _snapshot(target) == before
    assert {"cycle_configs", "access_token_policies"} <= set(inspect(copied_engine).get_table_names())
    check_schema(copied_engine)
    again = migrate(copied_engine)
    assert again == {"action": "up_to_date", "backup": None}
    assert _snapshot(target) == before
    copied_engine.dispose()
