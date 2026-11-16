"""
Тести бази даних і захисту анонімності.
Запуск з папки backend:  python -m pytest
"""
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app import seed
from app.anonymity import suppress_small_groups
from app.database import SessionLocal, engine
from app.main import app
from app.models import ResponseSet

client = TestClient(app)


def test_all_tables_created():
    tables = set(inspect(engine).get_table_names())
    assert tables == {"components", "questions", "cycles", "response_sets", "answers",
                      "access_tokens", "objective_indicators", "recommendations"}


def test_demo_data_loaded():
    db = SessionLocal()
    assert db.query(ResponseSet).count() == 804   # 268 анкет × 3 цикли
    db.close()


def test_seed_does_not_wipe_without_reset():
    """seed без --reset не повинен чіпати базу, у якій уже є дані."""
    assert seed.run(reset=False) is False
    db = SessionLocal()
    assert db.query(ResponseSet).count() == 804
    db.close()


def test_responses_have_no_identity_columns():
    """У таблиці анкет немає жодного поля, що вказує на людину."""
    columns = {c["name"] for c in inspect(engine).get_columns("response_sets")}
    assert columns == {"id", "cycle_id", "respondent_category", "unit"}


def test_token_not_linked_to_responses():
    """Токен доступу не пов'язаний з анкетою: не можна дізнатися, хто що відповів."""
    foreign_keys = inspect(engine).get_foreign_keys("access_tokens")
    assert [fk["referred_table"] for fk in foreign_keys] == ["cycles"]


def test_suppress_small_groups_hides_everything_but_label():
    groups = [{"category": "cadets", "responses": 210, "avg": 3.4},
              {"category": "staff", "responses": 4, "avg": 2.9}]
    result = suppress_small_groups(groups, k=5, keep_keys=("category",))
    assert result[0] == {"category": "cadets", "responses": 210, "avg": 3.4, "hidden": False}
    assert result[1] == {"category": "staff", "responses": None, "avg": None, "hidden": True}


def test_participation_hides_small_category():
    response = client.get("/cycles/3/participation")
    assert response.status_code == 200
    staff = next(g for g in response.json() if g["category"] == "staff")
    assert staff == {"category": "staff", "responses": None, "hidden": True}


def test_participation_by_unit_never_shows_group_below_k():
    """Навіть при розбитті категорія + підрозділ жодна видима група не менша за 5."""
    groups = client.get("/cycles/3/participation", params={"by_unit": True}).json()
    visible = [g for g in groups if not g["hidden"]]
    hidden = [g for g in groups if g["hidden"]]
    assert all(g["responses"] >= 5 for g in visible)
    assert hidden, "у демо-даних мають бути малі групи, щоб перевірити приховування"
    assert all(g["responses"] is None for g in hidden)


def test_unknown_cycle_returns_404():
    assert client.get("/cycles/999/participation").status_code == 404
