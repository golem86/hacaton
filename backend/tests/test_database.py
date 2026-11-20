"""
Тести бази даних і захисту анонімності.
Запуск з папки backend:  python -m pytest
"""
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app import seed
from app.anonymity import suppress_small_groups, visible_groups
from app.database import SessionLocal, engine
from app.main import app
from app.models import ResponseSet

client = TestClient(app)


def test_all_tables_created():
    tables = set(inspect(engine).get_table_names())
    assert tables == {"components", "questions", "cycles", "units", "response_sets", "answers",
                      "access_tokens", "access_token_policies", "cycle_configs",
                      "objective_indicators", "recommendations", "recommendation_actions", "audit_events",
                      "instance_meta", "annex_v_responses", "annex_v_answers", "annex_v_expert_assessments",
                      "checklist_entries", "maturity_indicators", "user_units"}


def test_demo_data_loaded():
    db = SessionLocal()
    # закритий цикл 1 інші тести не змінюють: у ньому рівно 268 демо-анкет (6 + 48 + 210 + 4)
    assert db.query(ResponseSet).filter_by(cycle_id=1).count() == 268
    db.close()


def test_seed_does_not_wipe_without_reset():
    """seed без --reset не повинен чіпати базу, у якій уже є дані."""
    db = SessionLocal()
    before = db.query(ResponseSet).count()
    assert seed.run(reset=False) is False
    assert db.query(ResponseSet).count() == before
    db.close()


def test_seed_does_not_wipe_partially_filled_database(tmp_path, monkeypatch):
    """РЕГРЕСІЯ: у базі є лише компонент (анкет немає) — seed без --reset НЕ має його видалити."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import Base
    from app.models import Component

    tmp_engine = create_engine(f"sqlite:///{tmp_path / 'partial.db'}")
    TmpSession = sessionmaker(bind=tmp_engine)
    Base.metadata.create_all(tmp_engine)
    with TmpSession() as db:
        db.add(Component(code="X1", name="Створений вручну", weight=1.0))
        db.commit()

    monkeypatch.setattr(seed, "engine", tmp_engine)
    monkeypatch.setattr(seed, "SessionLocal", TmpSession)

    assert seed.run(reset=False) is False
    with TmpSession() as db:
        assert [c.code for c in db.query(Component)] == ["X1"]


def test_seed_fills_empty_database(tmp_path, monkeypatch):
    """Порожню базу seed без --reset заповнює (і нічого не стирає)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    tmp_engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    TmpSession = sessionmaker(bind=tmp_engine)
    monkeypatch.setattr(seed, "engine", tmp_engine)
    monkeypatch.setattr(seed, "SessionLocal", TmpSession)

    assert seed.run(reset=False) is True
    with TmpSession() as db:
        assert db.query(ResponseSet).count() == 804


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
              {"category": "npp", "responses": 48, "avg": 3.6},
              {"category": "mgmt", "responses": 6, "avg": 4.1},
              {"category": "staff", "responses": 4, "avg": 2.9}]
    result = suppress_small_groups(groups, k=5, keep_keys=("category",))
    assert result[0] == {"category": "cadets", "responses": 210, "avg": 3.4, "hidden": False}
    assert result[1] == {"category": "npp", "responses": 48, "avg": 3.6, "hidden": False}
    # staff < 5 → прихована; mgmt прихована ДОДАТКОВО, бо інакше staff = підсумок − видимі
    assert result[2] == {"category": "mgmt", "responses": None, "avg": None, "hidden": True}
    assert result[3] == {"category": "staff", "responses": None, "avg": None, "hidden": True}


# Участь бачать admin і data_officer (V2_HARDENING_CONTRACT, розділ 1); manager — ні
MANAGER = {"X-Role": "admin"}


def test_visible_groups_drop_hidden_groups_entirely():
    groups = [{"category": "cadets", "responses": 210}, {"category": "npp", "responses": 48},
              {"category": "mgmt", "responses": 6}, {"category": "staff", "responses": 4}]
    shown, suppressed = visible_groups(groups, k=5)
    assert shown == [{"category": "cadets", "responses": 210, "hidden": False},
                     {"category": "npp", "responses": 48, "hidden": False}]
    assert suppressed is True
    assert visible_groups(groups[:2], k=5) == ([{**g, "hidden": False} for g in groups[:2]], False)


def test_participation_hides_small_category():
    """D4: прихована категорія не перелічується взагалі — навіть назва підтвердила б участь."""
    response = client.get("/api/assessments/1/participation", headers=MANAGER)
    assert response.status_code == 200
    data = response.json()
    assert {g["category"] for g in data["groups"]} == {"cadets", "npp"}
    assert all(g["hidden"] is False for g in data["groups"])
    assert data["suppressed"] is True and data["counts_exact"] is True


def test_participation_by_unit_never_shows_group_below_k():
    """Навіть при розбитті категорія + підрозділ жодна видима група не менша за 5, приховані не віддаються."""
    data = client.get("/api/assessments/1/participation", params={"by_unit": True}, headers=MANAGER).json()
    groups = data["groups"]
    assert groups and all(g["hidden"] is False and g["responses"] >= 5 for g in groups)
    true_cells = true_counts(1, by_unit=True)
    assert any(n < 5 for n in true_cells.values()), "у демо-даних мають бути малі групи"
    assert len(groups) < len(true_cells) and data["suppressed"] is True
    assert {g["category"] for g in groups} <= {"cadets", "npp"}       # клітинок прихованих категорій немає


def true_counts(assessment_id: int, by_unit: bool = False) -> dict:
    """Справжні кількості з бази — щоб перевірити, що API їх не розкриває."""
    db = SessionLocal()
    counts: dict = {}
    for rs in db.query(ResponseSet).filter_by(cycle_id=assessment_id):
        key = (rs.respondent_category, rs.unit) if by_unit else rs.respondent_category
        counts[key] = counts.get(key, 0) + 1
    db.close()
    return counts


def test_hidden_group_cannot_be_recovered_from_total():
    """РЕГРЕСІЯ: «підсумок − сума видимих» не повинен давати розмір групи < k."""
    data = client.get("/api/assessments/1/participation", headers=MANAGER).json()
    assert "tokens_used" not in data
    leftover = data["responses_total"] - sum(g["responses"] for g in data["groups"])
    assert leftover == 0 or leftover >= 5
    # залишок — сума кількох прихованих груп, а не розмір однієї малої
    assert leftover not in {n for n in true_counts(1).values() if n < 5}


def test_hidden_unit_cell_cannot_be_recovered_from_category_total():
    """РЕГРЕСІЯ: у розбивці по підрозділах підсумок категорії − видимі клітинки ≥ k або 0."""
    k = 5
    categories = client.get("/api/assessments/1/participation", headers=MANAGER).json()["groups"]
    cells = client.get("/api/assessments/1/participation", params={"by_unit": True},
                       headers=MANAGER).json()["groups"]
    true_cat = true_counts(1)
    for cat in categories:
        visible_cells = [c for c in cells if c["category"] == cat["category"]]
        leftover = cat["responses"] - sum(c["responses"] for c in visible_cells)
        assert leftover == 0 or leftover >= k
    # категорію, приховану в загальній розбивці, не можна «зібрати» з підрозділів
    hidden_categories = set(true_cat) - {c["category"] for c in categories}
    assert hidden_categories == {"mgmt", "staff"}
    assert not [c for c in cells if c["category"] in hidden_categories]
    # і жодна видима клітинка не збігається з малою справжньою групою
    true_cells = true_counts(1, by_unit=True)
    for c in cells:
        assert true_cells[(c["category"], c["unit"])] >= k


def test_open_assessment_shows_no_breakdown():
    """Поки цикл відкритий — лише загальна кількість, без розбивки (захист від порівняння «до/після»)."""
    data = client.get("/api/assessments/3/participation", headers=MANAGER).json()
    assert data["status"] == "open"
    assert data["groups"] is None and data["counts_exact"] is False
    assert data["responses_total"] % 5 == 0 and data["tokens_unused"] % 5 == 0   # D7: округлено до 5
    data_by_unit = client.get("/api/assessments/3/participation", params={"by_unit": True},
                              headers=MANAGER).json()
    assert data_by_unit["groups"] is None


def test_hidden_flags_property_on_many_random_cases():
    """Для будь-яких розмірів груп сума прихованих або 0, або ≥ k, і всі групи < k приховані."""
    import random
    from app.anonymity import hidden_flags
    rng = random.Random(7)
    for _ in range(2000):
        k = rng.randint(2, 10)
        sizes = [rng.randint(1, 30) for _ in range(rng.randint(1, 6))]
        flags = hidden_flags(sizes, k)
        hidden_sum = sum(s for s, h in zip(sizes, flags) if h)
        assert hidden_sum == 0 or hidden_sum >= k or all(flags)
        assert all(h for s, h in zip(sizes, flags) if s < k)


def test_unknown_assessment_returns_404():
    assert client.get("/api/assessments/999/participation", headers=MANAGER).status_code == 404
