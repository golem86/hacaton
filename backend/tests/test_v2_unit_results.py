"""
GET /v2/user/unit-results — «Результати підрозділу» для користувача V2.

Підрозділ визначає лише сервер (unit_membership), показуються лише закриті цикли, поріг k
(первинне і вторинне приховування), бали C1–C7 — як в адмінських /api/assessments/{id}/results,
жодних даних інших підрозділів чи розрізів за категорією.
"""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Answer, Component, Cycle, Question, ResponseSet, Unit
from app.routes import v2_unit_results
from app.unit_membership import set_user_unit_id
from app.v2_auth import find_user_id

from v2_helpers import login, make_user, start_login

URL = "/v2/user/unit-results"
K = 5
OPEN_ID = 3                                          # seed: цикл 2026-II відкритий
A, B, C = "Факультет 1", "Факультет 2", "Кафедра загальних дисциплін"   # підрозділи з seed
KEYS = {"status", "assessment", "unit", "min_group_size", "respondents", "components",
        "available_assessments", "methodology_version"}
CODES = [f"C{i}" for i in range(1, 8)]


def unit_id(name: str) -> int:
    with SessionLocal() as db:
        return db.query(Unit).filter_by(name=name).one().id


def make_cycle(groups: dict[str, int], status: str = "closed", offsets: dict[str, int] | None = None,
               skip: dict[str, tuple[str, int]] | None = None,
               categories: dict[str, list[str]] | None = None) -> int:
    """
    groups: підрозділ → кількість анкет. Відповіді детерміновані (індекс анкети, питання, зсув підрозділу),
    тож той самий підрозділ у різних циклах має однакові відповіді.
    skip: підрозділ → (код компонента, скільки перших анкет його не заповнили).
    categories: підрозділ → категорія кожної анкети (інакше по черзі cadets/staff).
    """
    offsets = offsets or {}
    skip = skip or {}
    with SessionLocal() as db:
        cycle = Cycle(name=f"UNIT-{status}-{sum(groups.values())}", start_date=date(2001, 1, 1),
                      status=status, min_group_size=K)
        db.add(cycle)
        db.flush()
        questions = (db.query(Question).join(Component).filter(Question.kind == "survey")
                     .order_by(Question.id).all())
        for unit, count in groups.items():
            for i in range(count):
                category = (categories or {}).get(unit, [])[i] if unit in (categories or {}) else                     ("staff" if i % 2 else "cadets")
                rs = ResponseSet(cycle_id=cycle.id, respondent_category=category, unit=unit)
                db.add(rs)
                for j, q in enumerate(questions):
                    code, skipped = skip.get(unit, (None, 0))
                    if q.component.code == code and i < skipped:
                        continue
                    rs.answers.append(Answer(question_id=q.id, value=1 + (i * 3 + j + offsets.get(unit, 0)) % 5))
        db.commit()
        return cycle.id


def client_in(unit: str | None, role: str = "user") -> TestClient:
    email = make_user(role)
    if unit is not None:
        with SessionLocal() as db:
            set_user_unit_id(db, find_user_id(email), unit_id(unit))
            db.commit()
    client, _ = login(email)
    return client


def get(client: TestClient, assessment_id: int | None = None, **params):
    if assessment_id is not None:
        params["assessment_id"] = assessment_id
    return client.get(URL, params=params)


def scores(body: dict) -> dict[str, float | None]:
    return {c["code"]: c["score"] for c in body["components"]}


# --- Доступ ---------------------------------------------------------------------------------------------

def test_requires_verified_v2_session():
    assert TestClient(app).get(URL).status_code == 401
    assert TestClient(app).get(URL, headers={"X-Role": "admin"}).status_code == 401
    pending, _ = start_login(make_user())                       # пароль прийнято, 2FA не пройдено
    assert pending.get(URL).status_code == 401


@pytest.mark.parametrize("role", ["admin", "data_officer"])
def test_any_verified_role_gets_own_unit(role):
    cycle_id = make_cycle({A: 6})
    response = get(client_in(A, role), cycle_id)
    assert response.status_code == 200
    assert response.json()["status"] == "available" and response.json()["unit"]["name"] == A


# --- Статуси --------------------------------------------------------------------------------------------

def test_no_unit_assigned():
    response = get(client_in(None))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == KEYS
    assert body["status"] == "no_unit"
    assert body["unit"] is None and body["respondents"] is None and body["components"] == []
    assert body["available_assessments"] and isinstance(body["methodology_version"], str)


def test_no_closed_cycle(monkeypatch):
    monkeypatch.setattr(v2_unit_results, "_closed_cycles", lambda db: [])
    body = get(client_in(A)).json()
    assert body["status"] == "no_closed_cycle"
    assert body["assessment"] is None and body["available_assessments"] == []
    assert body["unit"] == {"id": unit_id(A), "name": A}
    assert body["respondents"] is None and body["components"] == []
    assert body["min_group_size"] == K


def test_available_unit_matches_admin_analytics():
    cycle_id = make_cycle({A: 7})                               # у циклі лише підрозділ A
    response = get(client_in(A), cycle_id)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == KEYS
    assert body["status"] == "available"
    assert body["assessment"]["id"] == cycle_id and body["assessment"]["status"] == "closed"
    assert body["unit"] == {"id": unit_id(A), "name": A}
    assert body["min_group_size"] == K and body["respondents"] == 7
    assert [c["code"] for c in body["components"]] == CODES
    assert all(set(c) == {"code", "name", "score", "status"} for c in body["components"])
    assert all(c["status"] == "available" and c["score"] is not None for c in body["components"])

    admin, _ = login(make_user("admin"))
    official = admin.get(f"/api/assessments/{cycle_id}/results").json()
    assert official["responses_total"] == body["respondents"]
    assert scores(body) == {c["code"]: c["score"] for c in official["components"]}
    assert [c["name"] for c in body["components"]] == [c["name"] for c in official["components"]]


def test_insufficient_data_for_small_unit_and_secondary_suppression():
    cycle_id = make_cycle({A: 7, B: 6, C: 2})                   # C < k; вторинно приховується B (найменший видимий)
    for unit in (C, B):
        body = get(client_in(unit), cycle_id).json()
        assert body["status"] == "insufficient_data", unit
        assert body["unit"]["name"] == unit
        assert body["respondents"] is None and body["components"] == []
        assert body["min_group_size"] == K
    assert get(client_in(A), cycle_id).json()["status"] == "available"


def test_respondents_hidden_when_participation_by_unit_would_reveal_hidden_cells():
    # A: 6 cadets + 2 staff, B: 6 staff. participation?by_unit=true показує клітинку cadets×A (6),
    # а staff×A (2) і staff×B (6) приховує. 8 − 6 = 2 < k — кількість A розкрила б приховану клітинку.
    cycle_id = make_cycle({A: 8, B: 6}, categories={A: ["cadets"] * 6 + ["staff"] * 2, B: ["staff"] * 6})
    admin, _ = login(make_user("admin"))
    cells = admin.get(f"/api/assessments/{cycle_id}/participation", params={"by_unit": "true"}).json()["groups"]
    assert sum(c["responses"] for c in cells if c["unit"] == A) == 6
    body = get(client_in(A), cycle_id).json()
    assert body["status"] == "available" and body["respondents"] is None
    assert all(c["status"] == "available" and c["score"] is not None for c in body["components"])
    other = get(client_in(B), cycle_id).json()                  # для B прихований залишок = 6 ≥ k
    assert other["status"] == "available" and other["respondents"] == 6


def test_component_answered_by_fewer_than_k_is_suppressed():
    cycle_id = make_cycle({A: 7}, skip={A: ("C7", 3)})          # C7 заповнили лише 4 анкети з 7
    components = {c["code"]: c for c in get(client_in(A), cycle_id).json()["components"]}
    assert components["C7"]["score"] is None and components["C7"]["status"] == "suppressed"
    assert all(components[code]["status"] == "available" for code in CODES[:6])


# --- Цикли ----------------------------------------------------------------------------------------------

def test_open_cycle_is_409_and_draft_is_404_except_admin():
    client = client_in(A)
    draft = make_cycle({A: 6}, status="draft")
    assert get(client, OPEN_ID).status_code == 409
    assert get(client, make_cycle({A: 6}, status="open")).status_code == 409
    assert get(client, draft).status_code == 404                # чернетка = неіснуючий цикл (get_public_assessment)
    assert get(client_in(A, "data_officer"), draft).status_code == 404
    assert get(client_in(A, "admin"), draft).status_code == 409


def test_unknown_cycle_is_404_and_bad_id_is_422():
    client = client_in(A)
    assert get(client, 99_999_999).status_code == 404
    assert get(client, 0).status_code == 422
    assert client.get(URL, params={"assessment_id": "abc"}).status_code == 422


def test_default_is_newest_closed_cycle():
    make_cycle({A: 6})
    body = get(client_in(A)).json()
    with SessionLocal() as db:
        expected = [c.id for c in db.query(Cycle).filter(Cycle.status == "closed")
                    .order_by(Cycle.start_date.desc(), Cycle.id.desc())]
    assert [c["id"] for c in body["available_assessments"]] == expected
    assert all(set(c) == {"id", "name"} for c in body["available_assessments"])
    assert OPEN_ID not in expected
    assert body["assessment"]["id"] == expected[0]


# --- Підрозділ лише з сервера, інші підрозділи не розкриваються ------------------------------------------

def test_unit_id_query_parameter_does_not_change_unit():
    cycle_id = make_cycle({A: 6, B: 6}, offsets={B: 2})
    client = client_in(A)
    own = get(client, cycle_id).json()
    for value in (unit_id(B), unit_id(C), "abc"):
        response = get(client, cycle_id, unit_id=value)
        assert response.status_code == 200
        assert response.json() == own
    assert own["unit"]["name"] == A and own["respondents"] == 6


def test_response_contains_no_data_of_other_units():
    only_a = make_cycle({A: 7})
    mixed = make_cycle({A: 7, B: 9}, offsets={B: 3})            # A має ті самі відповіді, що й у only_a
    client = client_in(A)
    alone = get(client, only_a).json()
    body = get(client, mixed).json()
    assert body["status"] == "available" and body["respondents"] == 7
    assert scores(body) == scores(alone)                         # B не впливає на бали A

    admin, _ = login(make_user("admin"))
    overall = {c["code"]: c["score"] for c in admin.get(f"/api/assessments/{mixed}/results").json()["components"]}
    assert scores(body) != overall                                # це не загальний бал циклу

    text = json.dumps(body, ensure_ascii=False)
    for marker in (B, C, "by_category", "categories", "responses_total", "cadets", "staff", "answers"):
        assert marker not in text, marker

    other = get(client_in(B), mixed).json()
    assert other["unit"]["name"] == B and other["respondents"] == 9
    assert A not in json.dumps(other, ensure_ascii=False)
