"""Новий адміністративний цикл без персональних або реальних даних."""
from datetime import date
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import SessionLocal
from app.main import app
from app.models import AccessToken, AuditEvent, Question, ResponseSet

client = TestClient(app)
ADMIN = {"X-Role": "admin"}


def payload():
    return {"name": "Синтетичний цикл", "description": "Тест", "scope": "Демо",
            "start_date": date.today().isoformat(), "categories": ["cadets"],
            "min_group_size": 5, "questionnaire_version": "demo-v1"}


def answers():
    with SessionLocal() as db:
        return [{"question_id": q.id, "value": 3} for q in db.query(Question).filter_by(kind="survey")]


def test_admin_cycle_flow_and_privacy():
    assert client.post("/api/assessments", json=payload()).status_code == 401
    bad = payload() | {"min_group_size": 1}
    assert client.post("/api/assessments", json=bad, headers=ADMIN).status_code == 422
    bad = payload() | {"categories": ["cadets", "cadets"]}
    assert client.post("/api/assessments", json=bad, headers=ADMIN).status_code == 422

    created = client.post("/api/assessments", json=payload(), headers=ADMIN)
    assert created.status_code == 201
    cycle_id = created.json()["id"]
    assert created.json()["status"] == "draft"
    assert created.json()["min_group_size"] == 5
    path = f"/api/assessments/{cycle_id}"
    assert client.post(path + "/tokens", headers=ADMIN).status_code == 409
    assert client.post(path + "/activate", headers=ADMIN).status_code == 200
    assert client.post(path + "/activate", headers=ADMIN).status_code == 409
    assert client.post(path + "/tokens?category=mgmt", headers=ADMIN).status_code == 422
    issued = client.post(path + "/tokens?count=1&category=cadets", headers=ADMIN)
    assert issued.status_code == 201
    code = issued.json()["tokens"][0]
    body = {"token": code, "respondent_category": "cadets", "unit": "Факультет 1",
            "questionnaire_version": "demo-v1", "answers": answers()}
    assert client.post(path + "/submissions", json=body | {"questionnaire_version": "wrong"}).status_code == 409
    assert client.post(path + "/submissions", json=body | {"respondent_category": "mgmt"}).status_code == 403
    response = client.post(path + "/submissions", json=body)
    assert response.status_code == 201 and response.json() == {"status": "accepted"}
    assert client.post(path + "/submissions", json=body).status_code == 403
    stats = client.get(path + "/participation", headers=ADMIN).json()
    assert stats["tokens_issued"] == 1 and stats["tokens_unused"] is None
    assert stats["responses_total"] is None and stats["participation_percent"] is None
    assert client.post(path + "/close", headers=ADMIN).status_code == 200
    assert client.post(path + "/close", headers=ADMIN).status_code == 409
    assert client.post(path + "/submissions", json=body).status_code == 409
    with SessionLocal() as db:
        assert db.query(ResponseSet).filter_by(cycle_id=cycle_id).count() == 1
        assert db.query(AccessToken).filter_by(cycle_id=cycle_id, used=True).count() == 1
        actions = {row.action for row in db.query(AuditEvent).filter_by(assessment_id=cycle_id)}
        assert actions == {"assessment.create", "assessment.activate", "tokens.issue", "assessment.close"}


def test_expired_code_does_not_create_response():
    created = client.post("/api/assessments", json=payload(), headers=ADMIN).json()
    cycle_id = created["id"]
    path = f"/api/assessments/{cycle_id}"
    client.post(path + "/activate", headers=ADMIN)
    code = client.post(path + "/tokens?count=1&category=cadets", headers=ADMIN).json()["tokens"][0]
    with SessionLocal() as db:
        row = db.query(AccessToken).filter_by(token=code).one()
        db.execute(text("UPDATE access_token_policies SET expires_at='2000-01-01 00:00:00' WHERE token_id=:id"), {"id": row.id})
        db.commit()
    body = {"token": code, "respondent_category": "cadets", "unit": "Факультет 1",
            "questionnaire_version": "demo-v1", "answers": answers()}
    assert client.post(path + "/submissions", json=body).status_code == 403
    with SessionLocal() as db:
        assert db.query(ResponseSet).filter_by(cycle_id=cycle_id).count() == 0


def test_concurrent_code_redemption_accepts_only_once():
    created = client.post("/api/assessments", json=payload(), headers=ADMIN).json()
    cycle_id = created["id"]
    path = f"/api/assessments/{cycle_id}"
    client.post(path + "/activate", headers=ADMIN)
    code = client.post(path + "/tokens?count=1&category=cadets", headers=ADMIN).json()["tokens"][0]
    body = {"token": code, "respondent_category": "cadets", "unit": "Факультет 1",
            "questionnaire_version": "demo-v1", "answers": answers()}
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: client.post(path + "/submissions", json=body).status_code, range(2)))
    assert sorted(statuses) == [201, 403]
    with SessionLocal() as db:
        assert db.query(ResponseSet).filter_by(cycle_id=cycle_id).count() == 1
