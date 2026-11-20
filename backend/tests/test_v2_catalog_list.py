"""Каталог особистих самооцінювань: created_at у відповіді, узгоджені дати, достатній обсяг для пагінації.

conftest фіксує V2_CATALOG_NOW = 2026-11-18T12:00:00+00:00, тож статуси детерміновані.
"""
from datetime import datetime

from app.v2_catalog import PERSONAL_ASSESSMENTS, is_open
from v2_helpers import login, make_user

ALL_ANSWERS = {f"q{i}": 3 for i in range(1, 8)}
QUESTION_IDS = [f"q{i}" for i in range(1, 8)]


def _parse(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    assert moment.tzinfo is not None, f"дата без часового поясу: {value}"
    return moment


def test_catalog_has_unique_ids_and_consistent_dates():
    ids = [item["id"] for item in PERSONAL_ASSESSMENTS]
    names = [item["name"] for item in PERSONAL_ASSESSMENTS]
    assert len(ids) == len(set(ids)), "id мають бути унікальними"
    assert len(names) == len(set(names)), "назви мають бути унікальними"
    assert len(PERSONAL_ASSESSMENTS) > 12, "щонайменше три сторінки по 6 для демонстрації пагінації"
    for item in PERSONAL_ASSESSMENTS:
        created, opens, closes = (_parse(item[key]) for key in ("created_at", "opens_at", "closes_at"))
        assert created <= opens <= closes, item["id"]


def test_existing_ids_keep_their_place_and_periods():
    assert PERSONAL_ASSESSMENTS[0]["id"] == "personal-2026-q4"
    assert PERSONAL_ASSESSMENTS[1]["id"] == "personal-2027-q1"
    assert PERSONAL_ASSESSMENTS[0]["opens_at"] == "2026-11-17T00:00:00+00:00"
    assert PERSONAL_ASSESSMENTS[0]["closes_at"] == "2026-11-24T23:59:59+00:00"
    assert PERSONAL_ASSESSMENTS[1]["opens_at"] == "2027-01-01T00:00:00+00:00"
    assert PERSONAL_ASSESSMENTS[1]["closes_at"] == "2027-01-08T23:59:59+00:00"


def test_catalog_mixes_open_past_and_future_items():
    now = _parse("2026-11-18T12:00:00+00:00")
    open_ids = {item["id"] for item in PERSONAL_ASSESSMENTS if is_open(item, now)}
    past = [item for item in PERSONAL_ASSESSMENTS if _parse(item["closes_at"]) < now]
    future = [item for item in PERSONAL_ASSESSMENTS if _parse(item["opens_at"]) > now]
    assert "personal-2026-q4" in open_ids and "personal-2027-q1" not in open_ids
    assert len(open_ids) >= 3 and len(past) >= 3 and len(future) >= 3
    years = {_parse(item["closes_at"]).year for item in PERSONAL_ASSESSMENTS}
    assert {2025, 2026, 2027} <= years


def test_assessments_response_includes_created_at_and_status():
    client, _ = login(make_user())
    response = client.get("/v2/user/assessments")
    assert response.status_code == 200
    items = response.json()
    assert [item["id"] for item in items] == [item["id"] for item in PERSONAL_ASSESSMENTS]
    for item, source in zip(items, PERSONAL_ASSESSMENTS):
        assert item["created_at"] == source["created_at"]
        _parse(item["created_at"])
        assert item["status"] == ("open" if is_open(source) else "unavailable")
        assert [question["id"] for question in item["questions"]] == QUESTION_IDS
    statuses = {item["id"]: item["status"] for item in items}
    assert statuses["personal-2026-q4"] == "open"
    assert statuses["personal-2027-q1"] == "unavailable"
    assert statuses["personal-2025-q1"] == "unavailable"
    assert statuses["training-2026-integrity"] == "open"

    single = client.get("/v2/user/assessments/thematic-2026-reporting-channels")
    assert single.status_code == 200
    assert single.json()["created_at"] == "2026-10-20T08:15:00+00:00"
    assert client.get("/v2/user/assessments/unknown-assessment").status_code == 404


def test_new_catalog_items_follow_the_same_period_rules():
    client, csrf = login(make_user())
    opened = client.post("/v2/user/attempts", headers=csrf, json={
        "assessment_id": "thematic-2026-conflict-of-interest", "answers": {"q1": 4}})
    assert opened.status_code == 201
    assert opened.json()["assessment_name"] == "Тематичне самооцінювання: конфлікт інтересів"
    done = client.post(f"/v2/user/attempts/{opened.json()['id']}/complete", headers=csrf, json={"answers": ALL_ANSWERS})
    assert done.status_code == 200
    for closed_id in ("personal-2025-q1", "personal-2027-q2"):
        response = client.post("/v2/user/attempts", headers=csrf, json={"assessment_id": closed_id, "answers": {"q1": 3}})
        assert response.status_code == 409, closed_id
