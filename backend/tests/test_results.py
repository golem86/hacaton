"""
Тести цілісності бази, довідника підрозділів, закриття циклу й агрегованих результатів.
Запуск з папки backend:  python -m pytest
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.main import app
from app.models import Answer, Cycle, ResponseSet

client = TestClient(app)
ADMIN = {"X-Role": "admin"}
MANAGER = {"X-Role": "manager"}
RESPONDENT = {"X-Role": "respondent"}
CLOSED_ID = 1


# --- Цілісність SQLite ------------------------------------------------------

def test_database_rejects_orphan_answer():
    """Зовнішні ключі увімкнені: відповідь на неіснуючу анкету/питання база відхиляє."""
    db = SessionLocal()
    db.add(Answer(response_set_id=999_999, question_id=999_999, value=3))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.close()


def test_database_rejects_duplicate_answer():
    """На одне питання в одній анкеті — лише одна відповідь (обмеження в самій базі)."""
    db = SessionLocal()
    existing = db.query(Answer).first()
    db.add(Answer(response_set_id=existing.response_set_id, question_id=existing.question_id, value=1))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.close()


def test_database_rejects_unit_outside_directory():
    db = SessionLocal()
    db.add(ResponseSet(cycle_id=CLOSED_ID, respondent_category="cadets", unit="Іваненко, кімн. 214"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.close()


# --- Довідник підрозділів ---------------------------------------------------

def test_units_directory():
    units = client.get("/api/units", headers=RESPONDENT).json()
    assert units == sorted(["Факультет 1", "Факультет 2", "Кафедра загальних дисциплін"])


def test_submission_with_free_text_unit_is_rejected():
    token = client.post("/api/assessments/3/tokens", params={"count": 1}, headers=ADMIN).json()["tokens"][0]
    questionnaire = client.get("/api/assessments/3/questionnaires", headers=RESPONDENT).json()
    answers = [{"question_id": q["id"], "value": 3} for c in questionnaire for q in c["questions"]]
    response = client.post("/api/assessments/3/submissions", headers=RESPONDENT,
                           json={"token": token, "respondent_category": "cadets",
                                 "unit": "Іваненко І.І., кімн. 214", "answers": answers})
    assert response.status_code == 422


# --- Закриття циклу ---------------------------------------------------------

def new_open_cycle() -> int:
    db = SessionLocal()
    cycle = Cycle(name="Тестовий", start_date=date(2026, 12, 1), status="open", min_group_size=5)
    db.add(cycle)
    db.commit()
    cycle_id = cycle.id
    db.close()
    return cycle_id


def test_only_admin_closes_assessment():
    cycle_id = new_open_cycle()
    assert client.post(f"/api/assessments/{cycle_id}/close", headers=MANAGER).status_code == 403
    response = client.post(f"/api/assessments/{cycle_id}/close", headers=ADMIN)
    assert response.status_code == 200
    assert response.json()["status"] == "closed"
    assert client.post(f"/api/assessments/{cycle_id}/close", headers=ADMIN).status_code == 409


def test_closed_assessment_rejects_new_tokens():
    cycle_id = new_open_cycle()
    client.post(f"/api/assessments/{cycle_id}/close", headers=ADMIN)
    assert client.post(f"/api/assessments/{cycle_id}/tokens", headers=ADMIN).status_code == 409


# --- Агреговані результати --------------------------------------------------

def test_results_only_for_closed_assessment():
    assert client.get("/api/assessments/3/results", headers=MANAGER).status_code == 409


def test_results_access_by_role():
    assert client.get(f"/api/assessments/{CLOSED_ID}/results", headers=RESPONDENT).status_code == 403
    assert client.get(f"/api/assessments/{CLOSED_ID}/results").status_code == 401
    assert client.get("/api/assessments/999/results", headers=MANAGER).status_code == 404


def test_results_structure_and_scale():
    data = client.get(f"/api/assessments/{CLOSED_ID}/results", headers=MANAGER).json()
    assert data["assessment"]["status"] == "closed"
    assert data["responses_total"] == 268
    assert len(data["components"]) == 7
    assert round(sum(c["weight"] for c in data["components"]), 6) == 1.0
    for comp in data["components"]:
        assert 0 <= comp["score"] <= 100
        assert len(comp["objective_indicators"]) == 1
        for cell in comp["by_category"]:
            assert cell["hidden"] or 0 <= cell["score"] <= 100


def test_results_hide_small_categories_in_every_component():
    """staff (4) прихована первинно, mgmt (6) — вторинно; у ВСІХ компонентах бал = None."""
    data = client.get(f"/api/assessments/{CLOSED_ID}/results", headers=MANAGER).json()
    hidden = {c["category"] for c in data["categories"] if c["hidden"]}
    assert hidden == {"mgmt", "staff"}
    for comp in data["components"]:
        for cell in comp["by_category"]:
            if cell["category"] in hidden:
                assert cell == {"category": cell["category"], "score": None, "hidden": True}


def test_results_hidden_set_is_never_smaller_than_k():
    """
    РЕГРЕСІЯ: із загального бала і видимих балів можна вирахувати лише середнє
    ВСІХ прихованих разом — тому їх сумарно має бути ≥ k.
    """
    data = client.get(f"/api/assessments/{CLOSED_ID}/results", headers=MANAGER).json()
    db = SessionLocal()
    true_sizes = {}
    for rs in db.query(ResponseSet).filter_by(cycle_id=CLOSED_ID):
        true_sizes[rs.respondent_category] = true_sizes.get(rs.respondent_category, 0) + 1
    db.close()
    hidden_total = sum(true_sizes[c["category"]] for c in data["categories"] if c["hidden"])
    assert hidden_total == 0 or hidden_total >= data["min_group_size"]


def test_secondary_suppression_prevents_count_reconstruction_across_api_slices():
    """A total minus visible groups must not reveal the size of a primary-small group."""
    results = client.get(f"/api/assessments/{CLOSED_ID}/results", headers=MANAGER).json()
    participation = client.get(f"/api/assessments/{CLOSED_ID}/participation", headers=MANAGER).json()
    by_unit = client.get(f"/api/assessments/{CLOSED_ID}/participation?by_unit=true", headers=MANAGER).json()
    k = results["min_group_size"]

    db = SessionLocal()
    try:
        actual = {}
        for row in db.query(ResponseSet).filter_by(cycle_id=CLOSED_ID):
            actual[row.respondent_category] = actual.get(row.respondent_category, 0) + 1
    finally:
        db.close()

    primary_small = {category for category, size in actual.items() if size < k}
    hidden = {row["category"] for row in results["categories"] if row["hidden"]}
    assert primary_small  # the seed must exercise primary suppression
    assert primary_small <= hidden
    assert hidden == {row["category"] for row in participation["groups"] if row["hidden"]}
    assert hidden == {"staff", "mgmt"}  # staff=4; mgmt=6 is secondary suppression

    visible = {row["category"]: row["responses"] for row in results["categories"] if not row["hidden"]}
    assert visible == {row["category"]: row["responses"] for row in participation["groups"] if not row["hidden"]}
    assert results["responses_total"] == participation["responses_total"] == by_unit["responses_total"]
    remainder = results["responses_total"] - sum(visible.values())
    assert remainder == sum(actual[category] for category in hidden)
    assert remainder >= k
    assert all(remainder != actual[category] for category in primary_small)
    assert all(row["responses"] is None for row in results["categories"] if row["hidden"])

    for row in by_unit["groups"]:
        if row["category"] in hidden:
            assert row["hidden"] and row["responses"] is None
    for category, category_total in visible.items():
        cells = [row for row in by_unit["groups"] if row["category"] == category]
        unit_remainder = category_total - sum(row["responses"] for row in cells if not row["hidden"])
        assert unit_remainder == 0 or unit_remainder >= k

    assert [component["code"] for component in results["components"]] == [f"C{i}" for i in range(1, 8)]
    for component in results["components"]:
        assert {cell["category"] for cell in component["by_category"] if cell["hidden"]} == hidden
        assert all(cell["score"] is None for cell in component["by_category"] if cell["hidden"])


def test_results_score_matches_manual_calculation():
    """Бал компонента C1 збігається з ручним розрахунком: (відповідь − 1) / 4 × 100."""
    from app.models import Component, Question
    db = SessionLocal()
    c1 = db.query(Component).filter_by(code="C1").one()
    values = [a.value for a in db.query(Answer).join(ResponseSet).join(Question)
              .filter(ResponseSet.cycle_id == CLOSED_ID, Question.component_id == c1.id)]
    db.close()
    expected = round(sum((v - 1) / 4 * 100 for v in values) / len(values), 1)
    data = client.get(f"/api/assessments/{CLOSED_ID}/results", headers=MANAGER).json()
    assert next(c for c in data["components"] if c["code"] == "C1")["score"] == expected
