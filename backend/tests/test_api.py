"""
Тести рольового доступу й анонімного надсилання анкет.
Запуск з папки backend:  python -m pytest
"""
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.database import SessionLocal, engine
from app.main import app
from app.models import AccessToken, Question, ResponseSet

client = TestClient(app)
OPEN_ID = 3  # у демо-даних відкритий цикл 2026-II
CLOSED_ID = 1

ADMIN = {"X-Role": "admin"}
MANAGER = {"X-Role": "manager"}
RESPONDENT = {"X-Role": "respondent"}


def new_token(assessment_id: int = OPEN_ID) -> str:
    return client.post(f"/api/assessments/{assessment_id}/tokens", params={"count": 1},
                       headers=ADMIN).json()["tokens"][0]


def full_answers(value: int = 4) -> list[dict]:
    db = SessionLocal()
    ids = [q.id for q in db.query(Question).filter(Question.kind == "survey")]
    db.close()
    return [{"question_id": i, "value": value} for i in ids]


def submission(token: str, **overrides) -> dict:
    return {"token": token, "respondent_category": "cadets", "unit": "Факультет 1",
            "answers": full_answers(), **overrides}


def responses_count() -> int:
    db = SessionLocal()
    n = db.query(ResponseSet).count()
    db.close()
    return n


# --- Рольовий доступ --------------------------------------------------------

def test_request_without_role_is_rejected():
    # V2: список циклів публічний (розділ 2.1), тож перевіряємо захищений маршрут
    assert client.get(f"/api/assessments/{OPEN_ID}/participation").status_code == 401


def test_unknown_role_is_rejected():
    assert client.get(f"/api/assessments/{OPEN_ID}/participation",
                      headers={"X-Role": "hacker"}).status_code == 401


def test_public_survey_reads_need_no_role():
    for path in ("/api/assessments", f"/api/assessments/{OPEN_ID}",
                 f"/api/assessments/{OPEN_ID}/questionnaires", "/api/units"):
        assert client.get(path).status_code == 200, path


def test_respondent_cannot_see_participation_statistics():
    assert client.get(f"/api/assessments/{OPEN_ID}/participation", headers=RESPONDENT).status_code == 403


def test_only_admin_issues_tokens():
    assert client.post(f"/api/assessments/{OPEN_ID}/tokens", headers=MANAGER).status_code == 403
    assert client.post(f"/api/assessments/{OPEN_ID}/tokens", headers=ADMIN).status_code == 201


def test_submission_depends_only_on_code_not_on_role():
    """V2: анонімне подання доступне лише за кодом; X-Role нічого не змінює (розділ 2.1)."""
    assert client.post(f"/api/assessments/{OPEN_ID}/submissions",
                       json=submission(new_token()), headers=MANAGER).status_code == 201
    assert client.post(f"/api/assessments/{OPEN_ID}/submissions",
                       json=submission(new_token())).status_code == 201
    assert client.post(f"/api/assessments/{OPEN_ID}/submissions",
                       json=submission("no-such-code"), headers=ADMIN).status_code == 403


def test_everyone_sees_questionnaire_with_weights():
    data = client.get(f"/api/assessments/{OPEN_ID}/questionnaires", headers=RESPONDENT).json()
    assert len(data) == 7
    assert round(sum(c["weight"] for c in data), 6) == 1.0


# --- Анонімне надсилання ----------------------------------------------------

def test_submission_is_saved_and_token_is_spent():
    token = new_token()
    before = responses_count()
    response = client.post(f"/api/assessments/{OPEN_ID}/submissions",
                           json=submission(token), headers=RESPONDENT)
    assert response.status_code == 201
    assert response.json() == {"status": "accepted"}   # без номера анкети
    assert responses_count() == before + 1
    db = SessionLocal()
    assert db.query(AccessToken).filter_by(token=token).one().used is True
    db.close()


def test_token_cannot_be_used_twice():
    token = new_token()
    url = f"/api/assessments/{OPEN_ID}/submissions"
    assert client.post(url, json=submission(token), headers=RESPONDENT).status_code == 201
    before = responses_count()
    assert client.post(url, json=submission(token), headers=RESPONDENT).status_code == 403
    assert responses_count() == before


def test_fake_token_is_rejected():
    response = client.post(f"/api/assessments/{OPEN_ID}/submissions",
                           json=submission("not-a-real-token"), headers=RESPONDENT)
    assert response.status_code == 403


def test_token_from_other_assessment_is_rejected():
    db = SessionLocal()
    foreign = db.query(AccessToken).filter_by(cycle_id=2, used=False).first().token
    db.close()
    response = client.post(f"/api/assessments/{OPEN_ID}/submissions",
                           json=submission(foreign), headers=RESPONDENT)
    assert response.status_code == 403


def test_incomplete_answers_are_rejected_and_token_kept():
    token = new_token()
    response = client.post(f"/api/assessments/{OPEN_ID}/submissions",
                           json=submission(token, answers=full_answers()[:-1]), headers=RESPONDENT)
    assert response.status_code == 422
    db = SessionLocal()
    assert db.query(AccessToken).filter_by(token=token).one().used is False  # можна спробувати ще раз
    db.close()


def test_value_outside_scale_is_rejected():
    response = client.post(f"/api/assessments/{OPEN_ID}/submissions",
                           json=submission(new_token(), answers=full_answers(value=9)), headers=RESPONDENT)
    assert response.status_code == 422


def test_closed_assessment_does_not_accept_answers():
    db = SessionLocal()
    token = db.query(AccessToken).filter_by(cycle_id=CLOSED_ID, used=False).first().token
    db.close()
    response = client.post(f"/api/assessments/{CLOSED_ID}/submissions",
                           json=submission(token), headers=RESPONDENT)
    assert response.status_code == 409


def test_unknown_category_is_rejected():
    response = client.post(f"/api/assessments/{OPEN_ID}/submissions",
                           json=submission(new_token(), respondent_category="general"), headers=RESPONDENT)
    assert response.status_code == 422


def test_no_link_between_tokens_and_responses_in_schema():
    """Структурна гарантія: жодна таблиця відповідей не посилається на токени."""
    for table in ("response_sets", "answers"):
        referred = {fk["referred_table"] for fk in inspect(engine).get_foreign_keys(table)}
        assert "access_tokens" not in referred
