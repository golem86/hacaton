"""
Тести контракту шкали анкети (backend ↔ frontend №1).
Запуск з папки backend:  python -m pytest tests/test_scale.py
"""
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app import seed
from app.database import SessionLocal, get_db
from app.main import app
from app.models import AccessToken, Question, hash_access_code
from app.questionnaire_contract import (MAX_SCALE_VALUES, SAFE_INTEGER, Questionnaire,
                                        scale_error, validate_scale)

client = TestClient(app)
ADMIN, RESPONDENT, MANAGER = {"X-Role": "admin"}, {"X-Role": "respondent"}, {"X-Role": "manager"}
DATA_OFFICER = {"X-Role": "data_officer"}   # коди видає лише data_officer (V2_HARDENING_CONTRACT, розділ 1)


# --- Правило шкали: граничні значення ---------------------------------------

@pytest.mark.parametrize("scale", [
    (1, 5),                                  # стандартна
    (3, 3),                                  # 1 значення — нижня межа
    (1, 2),                                  # 2 значення
    (1, 10),                                 # 10 значень — верхня межа
    (0, 9), (-4, 5),                         # 10 значень з іншими межами
    (SAFE_INTEGER - 9, SAFE_INTEGER),        # 10 значень біля межі безпечного цілого
    (-SAFE_INTEGER, -SAFE_INTEGER + 9),
])
def test_valid_scales(scale):
    assert scale_error(*scale) is None


@pytest.mark.parametrize("scale", [
    (1, 11),                                 # 11 значень
    (0, 10),                                 # 11 значень
    (1, 1000),
    (5, 4),                                  # min > max
    (1.0, 5), (1, 5.0), (1, 4.5),            # не цілі
    ("1", 5), (None, 5),
    (True, 5), (1, True),                    # bool — не число
    (SAFE_INTEGER - 2, SAFE_INTEGER + 1),    # поза безпечним цілим
    (-SAFE_INTEGER - 1, -SAFE_INTEGER + 3),
])
def test_invalid_scales(scale):
    assert scale_error(*scale) is not None
    with pytest.raises(ValueError):
        validate_scale(*scale)


def test_max_scale_values_is_ten():
    assert MAX_SCALE_VALUES == 10


# --- Захист на рівні БД (модель Question) ------------------------------------

@pytest.mark.parametrize("scale", [(1, 11), (5, 4)])
def test_question_with_invalid_scale_cannot_be_saved(scale):
    db = SessionLocal()
    db.add(Question(component_id=1, text="Некоректне", scale_min=scale[0], scale_max=scale[1]))
    with pytest.raises(ValueError):
        db.commit()
    db.rollback()
    db.close()


def test_question_scale_cannot_be_updated_to_invalid():
    db = SessionLocal()
    question = db.query(Question).first()
    question.scale_max = question.scale_min + 10   # 11 значень
    with pytest.raises(ValueError):
        db.commit()
    db.rollback()
    db.close()


def test_question_with_default_scale_is_saved():
    db = SessionLocal()
    question = Question(component_id=1, text="Типова шкала")
    db.add(question)
    db.flush()
    assert (question.scale_min, question.scale_max) == (1, 5)
    db.rollback()
    db.close()


# --- GET /questionnaires: сумісність з наявними даними -----------------------

def test_existing_questionnaire_satisfies_contract():
    data = client.get("/api/assessments/3/questionnaires", headers=RESPONDENT).json()
    Questionnaire.model_validate(data)                       # не кидає помилку
    scales = {tuple(q["scale"]) for c in data for q in c["questions"]}
    assert scales == {(1, 5)}                                # стандартна шкала збережена
    ids = [q["id"] for c in data for q in c["questions"]]
    assert len(ids) == len(set(ids))


def test_questionnaire_rejects_duplicate_question_ids_across_components():
    data = [{"code": "C1", "name": "А", "weight": 0.5, "questions": [{"id": 1, "text": "x", "scale": [1, 5]}]},
            {"code": "C2", "name": "Б", "weight": 0.5, "questions": [{"id": 1, "text": "y", "scale": [1, 5]}]}]
    with pytest.raises(ValidationError, match="повторюється"):
        Questionnaire.model_validate(data)


def test_questionnaire_rejects_invalid_scale_and_ids():
    base = {"code": "C1", "name": "А", "weight": 1.0}
    for question in ({"id": 1, "text": "x", "scale": [1, 11]},
                     {"id": 0, "text": "x", "scale": [1, 5]},
                     {"id": True, "text": "x", "scale": [1, 5]},
                     {"id": 1, "text": "x", "scale": [1, 5, 7]}):
        with pytest.raises(ValidationError):
            Questionnaire.model_validate([{**base, "questions": [question]}])


# --- Окрема тимчасова БД для сценаріїв зі «зламаними» даними -----------------

@pytest.fixture
def temp_client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'scale.db'}")
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(seed, "engine", engine)
    monkeypatch.setattr(seed, "SessionLocal", Session)
    seed.run(reset=False)

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app), engine
    app.dependency_overrides.clear()


def test_get_questionnaire_never_returns_invalid_scale(temp_client):
    """Якщо хтось обійшов модель і записав шкалу на 11 значень прямо в БД — фронтенд її не отримає."""
    c, engine = temp_client
    with engine.begin() as conn:
        conn.execute(text("UPDATE questions SET scale_max = 11 WHERE id = 1"))
    response = c.get("/api/assessments/3/questionnaires", headers=RESPONDENT)
    assert response.status_code == 500
    assert "контракт шкали" in response.json()["detail"]


def test_single_value_scale_does_not_break_results(temp_client):
    """Шкала з 1 значенням не дає ділення на нуль: питання просто не входить у бал."""
    c, engine = temp_client
    before = {x["code"]: x["score"] for x in c.get("/api/assessments/1/results", headers=MANAGER).json()["components"]}
    with engine.begin() as conn:
        # питання 1 (компонент C1) стає шкалою [3, 3]; його відповіді — 3
        conn.execute(text("UPDATE questions SET scale_min = 3, scale_max = 3 WHERE id = 1"))
        conn.execute(text("UPDATE answers SET value = 3 WHERE question_id = 1"))
    response = c.get("/api/assessments/1/results", headers=MANAGER)
    assert response.status_code == 200
    after = {x["code"]: x["score"] for x in response.json()["components"]}
    assert after["C1"] is not None and 0 <= after["C1"] <= 100    # рахується за питанням 2
    assert {k: v for k, v in after.items() if k != "C1"} == {k: v for k, v in before.items() if k != "C1"}
    q = c.get("/api/assessments/3/questionnaires", headers=RESPONDENT)
    assert q.status_code == 200                                    # 1 значення — допустима шкала

    with engine.begin() as conn:                                   # обидва питання C1 — по 1 значенню
        conn.execute(text("UPDATE questions SET scale_min = 3, scale_max = 3 WHERE id = 2"))
        conn.execute(text("UPDATE answers SET value = 3 WHERE question_id = 2"))
    c1 = next(x for x in c.get("/api/assessments/1/results", headers=MANAGER).json()["components"] if x["code"] == "C1")
    assert c1["score"] is None                                     # бал не визначений, але без помилки


# --- POST /submissions: некоректні вхідні анкети → 422 -----------------------

def new_token() -> str:
    return client.post("/api/assessments/3/tokens", params={"count": 1}, headers=DATA_OFFICER).json()["tokens"][0]


def answers(value=3):
    data = client.get("/api/assessments/3/questionnaires", headers=RESPONDENT).json()
    return [{"question_id": q["id"], "value": value} for c in data for q in c["questions"]]


def body(token, **over):
    return {"token": token, "respondent_category": "cadets", "unit": "Факультет 1",
            "answers": answers(), **over}


@pytest.mark.parametrize("name, mutate", [
    ("value як рядок", lambda a: [{**a[0], "value": "4"}] + a[1:]),
    ("value дробове", lambda a: [{**a[0], "value": 4.5}] + a[1:]),
    ("value як 4.0", lambda a: [{**a[0], "value": 4.0}] + a[1:]),
    ("value bool", lambda a: [{**a[0], "value": True}] + a[1:]),
    ("value поза безпечним цілим", lambda a: [{**a[0], "value": SAFE_INTEGER + 1}] + a[1:]),
    ("question_id нуль", lambda a: [{**a[0], "question_id": 0}] + a[1:]),
    ("question_id рядок", lambda a: [{**a[0], "question_id": "1"}] + a[1:]),
    ("дубль question_id", lambda a: a + [a[0]]),
    ("порожні відповіді", lambda a: []),
    ("відповіді не список", lambda a: {"1": 3}),
    ("значення поза шкалою 1–5", lambda a: [{**a[0], "value": 6}] + a[1:]),
    ("значення 0", lambda a: [{**a[0], "value": 0}] + a[1:]),
])
def test_invalid_submission_returns_422_and_keeps_token(name, mutate):
    token = new_token()
    response = client.post("/api/assessments/3/submissions", headers=RESPONDENT,
                           json=body(token, answers=mutate(answers())))
    assert response.status_code == 422, name
    db = SessionLocal()
    assert db.query(AccessToken).filter_by(token_hash=hash_access_code(token)).one().used is False, name
    db.close()


@pytest.mark.parametrize("value", [1, 5])
def test_scale_boundaries_are_accepted(value):
    response = client.post("/api/assessments/3/submissions", headers=RESPONDENT,
                           json=body(new_token(), answers=answers(value)))
    assert response.status_code == 201
