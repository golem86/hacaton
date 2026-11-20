"""
Тести журналу дій (Audit Trail).
Запуск з папки backend:  python -m pytest
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import audit
from app.database import SessionLocal
from app.main import app
from app.models import AccessToken, AuditEvent, Cycle, Question, hash_access_code

client = TestClient(app)
ADMIN = {"X-Role": "admin"}
DATA_OFFICER = {"X-Role": "data_officer"}   # коди видає лише data_officer (V2_HARDENING_CONTRACT, розділ 1)
AUDITOR = {"X-Role": "auditor"}


def new_open_cycle() -> int:
    db = SessionLocal()
    cycle = Cycle(name="Аудит-тест", start_date=date(2026, 12, 1), status="open", min_group_size=5)
    db.add(cycle)
    db.commit()
    cycle_id = cycle.id
    db.close()
    return cycle_id


def events(assessment_id: int, headers=ADMIN) -> list[dict]:
    return client.get("/api/audit-events", params={"assessment_id": assessment_id}, headers=headers).json()


def audit_rows_text() -> str:
    """Увесь вміст таблиці журналу одним рядком — щоб шукати витоки."""
    db = SessionLocal()
    rows = db.query(AuditEvent).all()
    db.close()
    return " ".join(f"{r.actor_role} {r.action} {r.assessment_id} {r.details}" for r in rows)


# --- Що записується ---------------------------------------------------------

def test_issuing_tokens_is_logged_with_count_only():
    cycle_id = new_open_cycle()
    tokens = client.post(f"/api/assessments/{cycle_id}/tokens", params={"count": 3},
                         headers=DATA_OFFICER).json()["tokens"]
    [event] = events(cycle_id)
    assert event["action"] == "tokens.issue"
    assert event["actor_role"] == "data_officer"
    assert event["actor_user_id"] is None          # демо-заголовок X-Role — без користувача V2
    assert event["assessment_id"] == cycle_id
    assert event["details"] == {"count": 3}
    assert event["created_at"].endswith("Z")
    text = audit_rows_text()
    assert not any(t in text for t in tokens), "коди доступу не повинні потрапляти в журнал"


def test_closing_assessment_is_logged():
    cycle_id = new_open_cycle()
    client.post(f"/api/assessments/{cycle_id}/close", headers=ADMIN)
    assert [e["action"] for e in events(cycle_id)] == ["assessment.close"]


def test_events_are_newest_first():
    cycle_id = new_open_cycle()
    client.post(f"/api/assessments/{cycle_id}/tokens", params={"count": 1}, headers=DATA_OFFICER)
    client.post(f"/api/assessments/{cycle_id}/close", headers=ADMIN)
    assert [e["action"] for e in events(cycle_id)] == ["assessment.close", "tokens.issue"]


# --- Що НЕ записується ------------------------------------------------------

def test_failed_operations_are_not_logged():
    cycle_id = new_open_cycle()
    client.post(f"/api/assessments/{cycle_id}/close", headers={"X-Role": "manager"})   # 403
    client.post(f"/api/assessments/{cycle_id}/tokens", headers={"X-Role": "respondent"})  # 403
    client.post(f"/api/assessments/{cycle_id}/tokens", headers=ADMIN)                   # 403 (лише data_officer)
    client.post(f"/api/assessments/{cycle_id}/close", headers=ADMIN)                    # 200
    client.post(f"/api/assessments/{cycle_id}/close", headers=ADMIN)                    # 409
    client.post(f"/api/assessments/{cycle_id}/tokens", headers=DATA_OFFICER)            # 409 (закрито)
    assert [e["action"] for e in events(cycle_id)] == ["assessment.close"]


def test_survey_submission_is_not_logged():
    """Подання анкет не журналюється: час подання міг би розкрити автора."""
    cycle_id = new_open_cycle()
    token = client.post(f"/api/assessments/{cycle_id}/tokens", params={"count": 1},
                        headers=DATA_OFFICER).json()["tokens"][0]
    db = SessionLocal()
    answers = [{"question_id": q.id, "value": 3} for q in db.query(Question).filter_by(kind="survey")]
    db.close()
    before = len(events(cycle_id))
    response = client.post(f"/api/assessments/{cycle_id}/submissions", headers={"X-Role": "respondent"},
                           json={"token": token, "respondent_category": "cadets",
                                 "unit": "Факультет 1", "answers": answers})
    assert response.status_code == 201
    assert len(events(cycle_id)) == before
    assert "cadets" not in audit_rows_text() and "Факультет" not in audit_rows_text()


@pytest.mark.parametrize("details", [
    {"token": "abc"}, {"tokens": ["abc"]}, {"answers": [1]}, {"unit": "Факультет 1"},
    {"respondent_category": "cadets"},
    {"note": "будь-яке недозволене поле"},          # невідомий ключ
    {"count": "abc123"},                            # код, «захований» у дозволеному полі
    {"count": {"token": "abc"}},                    # вкладений об'єкт
    {"count": ["abc"]},                             # список
    {"count": True},                                # bool — не число
])
def test_record_accepts_only_allowlisted_scalar_fields(details):
    db = SessionLocal()
    with pytest.raises(ValueError):
        audit.record(db, "admin", "tokens.issue", None, **details)
    db.rollback()
    db.close()


def test_record_refuses_unknown_action():
    db = SessionLocal()
    with pytest.raises(ValueError):
        audit.record(db, "admin", "survey.submit", None)
    db.rollback()
    db.close()


def test_record_accepts_allowed_fields():
    db = SessionLocal()
    audit.record(db, "admin", "tokens.issue", None, count=5)
    audit.record(db, "admin", "assessment.close", None)
    db.rollback()
    db.close()


def test_action_and_log_are_atomic():
    """Якщо дія не збереглася — не зберігся й запис журналу."""
    cycle_id = new_open_cycle()
    db = SessionLocal()
    db.add(AccessToken(cycle_id=cycle_id, token_hash=hash_access_code("atomic-test"), used=False))
    audit.record(db, "admin", "tokens.issue", cycle_id, count=1)
    db.rollback()
    db.close()
    assert events(cycle_id) == []


# --- Доступ до журналу ------------------------------------------------------

def test_audit_log_access_by_role():
    assert client.get("/api/audit-events", headers=ADMIN).status_code == 200
    # V2: роль auditor не вводиться до рішення №5 — журнал лише для admin (S12)
    for role in ("auditor", "manager", "respondent", "anticorruption", "expert"):
        assert client.get("/api/audit-events", headers={"X-Role": role}).status_code == 403
    assert client.get("/api/audit-events").status_code == 401


def test_audit_log_limit_is_validated():
    assert client.get("/api/audit-events", params={"limit": 0}, headers=ADMIN).status_code == 422
    assert client.get("/api/audit-events", params={"limit": 501}, headers=ADMIN).status_code == 422
    assert len(client.get("/api/audit-events", params={"limit": 1}, headers=ADMIN).json()) <= 1
