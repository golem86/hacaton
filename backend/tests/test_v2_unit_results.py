"""Екран «Результати підрозділу»: GET /v2/user/unit-results і серверна команда app.v2_unit_cli."""
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func

from app import v2_unit_cli
from app.database import SessionLocal
from app.main import app
from app.models import Answer, AuditEvent, Cycle, Question, ResponseSet, Unit, UserUnit
from app.services.unit_results import assign_unit
from app.v2_auth import find_user_by_email
from tests.v2_helpers import login, make_user

URL = "/v2/user/unit-results"


def _user_id(email: str) -> int:
    return int(find_user_by_email(email)["id"])


def _assign(email: str, unit: str | None) -> None:
    with SessionLocal() as db:
        assign_unit(db, _user_id(email), unit)
        db.commit()


def _closed_cycle(cells: dict[str, dict[str, int]], k: int = 5, status: str = "closed") -> int:
    """Цикл із заданою таблицею «підрозділ → {категорія: кількість анкет}».

    Кожна анкета відповідає на всі питання анкети (kind=survey); значення — максимум шкали для
    першого підрозділу і мінімум для решти, щоб бали підрозділів відрізнялися."""
    with SessionLocal() as db:
        cycle = Cycle(name=f"T-{uuid4().hex[:8]}", start_date=date(2026, 1, 1), status=status, min_group_size=k)
        db.add(cycle)
        db.flush()
        questions = db.query(Question).filter_by(kind="survey").order_by(Question.id).all()
        for index, (unit, by_category) in enumerate(cells.items()):
            if db.query(Unit).filter_by(name=unit).first() is None:
                db.add(Unit(name=unit))
                db.flush()
            for category, n in by_category.items():
                for _ in range(n):
                    rs = ResponseSet(cycle_id=cycle.id, respondent_category=category, unit=unit)
                    db.add(rs)
                    db.flush()
                    for q in questions:
                        db.add(Answer(response_set_id=rs.id, question_id=q.id,
                                      value=q.scale_max if index == 0 else q.scale_min))
        db.commit()
        return cycle.id


def _user_in(unit: str) -> TestClient:
    email = make_user()
    _assign(email, unit)
    return login(email)[0]


def _get(client: TestClient, assessment_id, **params):
    return client.get(URL, params={"assessment_id": assessment_id, **params})


def _is_hidden(body: dict) -> bool:
    return (body["privacy_status"] == "suppressed" and body["responses"] is None
            and all(c["score"] is None and c["status"] == "suppressed" for c in body["components"]))


def test_requires_user_session():
    assert TestClient(app).get(URL, params={"assessment_id": 1}).status_code == 401
    admin_client, _ = login(make_user("admin"))
    assert _get(admin_client, 1).status_code == 403


def test_no_unit_returns_no_data():
    client, _ = login(make_user())
    body = _get(client, 1).json()
    assert body["privacy_status"] == "no_unit" and body["unit"] is None and body["responses"] is None
    assert len(body["components"]) == 7
    assert all(c["score"] is None and c["status"] == "suppressed" for c in body["components"])


def test_available_unit_scores_match_direct_calculation_and_have_no_breakdowns():
    cycle_id = _closed_cycle({"Повна А": {"cadets": 12, "npp": 11}, "Повна Б": {"cadets": 10}})
    body = _get(_user_in("Повна А"), cycle_id).json()
    with SessionLocal() as db:
        from app.models import Component
        q = (db.query(Question.component_id,
                      func.avg((Answer.value - Question.scale_min) * 100.0 / (Question.scale_max - Question.scale_min)))
             .join(Answer, Answer.question_id == Question.id)
             .join(ResponseSet, ResponseSet.id == Answer.response_set_id)
             .filter(ResponseSet.cycle_id == cycle_id, ResponseSet.unit == "Повна А", Question.kind == "survey")
             .group_by(Question.component_id).all())
        codes = {c.id: c.code for c in db.query(Component)}
    expected = {codes[cid]: round(score, 1) for cid, score in q}
    assert body["privacy_status"] == "available" and body["unit"] == "Повна А"
    assert body["responses"] == 20                        # 23 анкети → вниз до кратного 5
    assert {c["code"]: c["score"] for c in body["components"] if c["status"] == "available"} == expected
    assert set(body) == {"assessment", "unit", "methodology_version", "min_group_size", "privacy_status",
                         "responses", "components"}
    assert all(set(c) == {"code", "name", "score", "status"} for c in body["components"])


def test_demo_cycle_with_small_category_cells_is_hidden():
    # У демо-даних керівництво (6) і персонал (4) розкидані по підрозділах дрібними клітинками.
    body = _get(_user_in("Факультет 1"), 1).json()
    assert _is_hidden(body)


def test_client_cannot_choose_another_unit():
    cycle_id = _closed_cycle({"Вибір А": {"cadets": 10}, "Вибір Б": {"cadets": 10}})
    client = _user_in("Вибір А")
    own = _get(client, cycle_id).json()
    assert own["privacy_status"] == "available"
    for extra in ({"unit": "Вибір Б"}, {"unit_id": 2}, {"category": "mgmt"}):
        assert _get(client, cycle_id, **extra).json() == own


def test_open_unknown_draft_and_invalid_cycles():
    client = _user_in("Факультет 1")
    assert _get(client, 3).status_code == 409          # цикл 3 у демо-даних відкритий
    assert _get(client, 999999).status_code == 404
    draft = _closed_cycle({"Чернетка": {"cadets": 10}}, status="draft")
    assert _get(client, draft).status_code == 404      # чернетка не відрізняється від неіснуючого
    assert _get(client, 0).status_code == 422
    assert _get(client, 2**63).status_code == 422


def test_small_unit_is_hidden_and_identical_to_empty_unit():
    cycle_id = _closed_cycle({"Велика": {"cadets": 20}, "Мала": {"cadets": 3}})
    with SessionLocal() as db:
        if db.query(Unit).filter_by(name="Порожня").first() is None:
            db.add(Unit(name="Порожня"))
            db.commit()
    a = _get(_user_in("Мала"), cycle_id).json()
    b = _get(_user_in("Порожня"), cycle_id).json()
    assert _is_hidden(a) and _is_hidden(b)
    assert {k: v for k, v in a.items() if k != "unit"} == {k: v for k, v in b.items() if k != "unit"}


# Регресії за атаками з незалежної перевірки (віднімання між підрозділами, категоріями й підсумком)

def test_rest_of_cycle_small_hides_large_unit():
    cycle_id = _closed_cycle({"Велика": {"cadets": 20}, "Мала": {"cadets": 3}})
    assert _is_hidden(_get(_user_in("Велика"), cycle_id).json())


def test_lone_manager_inside_large_unit_hides_all_units():
    # A = staff 8 + mgmt 1, B = staff 8, C = cadets 6 + mgmt 4: раніше A і B були видимі, і разом із
    # балом staff з /results відновлювались бали єдиного керівника з A.
    cycle_id = _closed_cycle({"A": {"staff": 8, "mgmt": 1}, "B": {"staff": 8}, "C": {"cadets": 6, "mgmt": 4}})
    for unit in ("A", "B", "C"):
        assert _is_hidden(_get(_user_in(unit), cycle_id).json()), unit


def test_small_cell_in_other_unit_hides_own_unit():
    # A і B — по 8 staff, C = staff 3 + cadets 6: staff_C = (19·S − 8·A − 8·B) / 3 розкрив би 3 людей.
    cycle_id = _closed_cycle({"A": {"staff": 8}, "B": {"staff": 8}, "C": {"staff": 3, "cadets": 6}})
    assert _is_hidden(_get(_user_in("A"), cycle_id).json())
    assert _is_hidden(_get(_user_in("B"), cycle_id).json())


def test_unit_total_does_not_reveal_hidden_cell_size():
    # A = staff 6 + mgmt 1: точна кількість 7 разом із клітинкою staff×A = 6 показала б, що
    # єдиний керівник підрозділу взяв участь.
    cycle_id = _closed_cycle({"A": {"staff": 6, "mgmt": 1}, "B": {"cadets": 10}})
    assert _is_hidden(_get(_user_in("A"), cycle_id).json())


def test_reassigned_user_sees_only_whole_cell_aggregates():
    # Переведення між підрозділами допустиме лише тоді, коли всі клітинки ≥ k: тоді різниця
    # двох підрозділів — це сума цілих клітинок, кожна з яких ≥ k.
    cycle_id = _closed_cycle({"X": {"cadets": 10}, "Y": {"cadets": 10, "npp": 5}})
    email = make_user()
    _assign(email, "X")
    client, _ = login(email)
    assert _get(client, cycle_id).json()["privacy_status"] == "available"
    _assign(email, "Y")
    assert _get(client, cycle_id).json()["responses"] == 15


def test_whole_cycle_in_one_unit_is_available():
    cycle_id = _closed_cycle({"Єдина": {"cadets": 6}})
    body = _get(_user_in("Єдина"), cycle_id).json()
    assert body["privacy_status"] == "available" and body["responses"] == 5     # 6 → 5


def test_user_session_has_no_management_analytics():
    client = _user_in("Факультет 1")
    assert client.get("/api/assessments/1/results").status_code in (401, 403)


# ---------------------------------------------------------------------------
# Серверна команда
# ---------------------------------------------------------------------------

def _unit_of(email: str) -> str | None:
    with SessionLocal() as db:
        row = db.get(UserUnit, _user_id(email))
        return row.unit if row else None


def _audit_count() -> int:
    with SessionLocal() as db:
        return db.query(AuditEvent).filter_by(action="user.unit_change").count()


def test_cli_plan_does_not_change_anything(capsys):
    email = make_user()
    before = _audit_count()
    assert v2_unit_cli.main(["set-unit", "--email", email, "--unit", "Факультет 2"]) == 0
    assert _unit_of(email) is None and _audit_count() == before
    assert "ПЛАН" in capsys.readouterr().out


def test_cli_confirm_assigns_and_audits_without_personal_data(capsys):
    email = make_user()
    before = _audit_count()
    assert v2_unit_cli.main(["set-unit", "--email", email, "--unit", "Факультет 2", "--confirm"]) == 0
    assert _unit_of(email) == "Факультет 2" and _audit_count() == before + 1
    out = capsys.readouterr().out
    assert email not in out
    with SessionLocal() as db:
        event = db.query(AuditEvent).filter_by(action="user.unit_change").order_by(AuditEvent.id.desc()).first()
        assert event.actor_role == "server"
        dumped = " ".join(str(v) for v in vars(event).values())
        assert email not in dumped and "Факультет 2" not in dumped
    assert v2_unit_cli.main(["clear-unit", "--email", email, "--confirm"]) == 0
    assert _unit_of(email) is None


def test_cli_refuses_unknown_unit_and_user():
    email = make_user()
    assert v2_unit_cli.main(["set-unit", "--email", email, "--unit", "Вигаданий підрозділ", "--confirm"]) == 2
    assert _unit_of(email) is None
    assert v2_unit_cli.main(["set-unit", "--email", f"{uuid4().hex}@example.test", "--unit", "Факультет 1",
                             "--confirm"]) == 2


def test_cli_refuses_unchanged():
    email = make_user()
    assert v2_unit_cli.main(["set-unit", "--email", email, "--unit", "Факультет 1", "--confirm"]) == 0
    assert v2_unit_cli.main(["set-unit", "--email", email, "--unit", "Факультет 1", "--confirm"]) == 2


def test_no_web_route_changes_unit():
    admin_client, headers = login(make_user("admin"))
    paths = app.openapi()["paths"]
    unit_paths = {p: set(ops) for p, ops in paths.items() if "unit" in p and ("admin" in p or "user" in p)}
    assert unit_paths == {URL: {"get"}}
    target = make_user()
    for path in (f"/v2/admin/users/{_user_id(target)}/unit", "/v2/user/unit"):
        assert admin_client.post(path, json={"unit": "Факультет 1"}, headers=headers).status_code in (404, 405)
    assert _unit_of(target) is None
