"""
API зрілості за Додатком В: анонімні анкети за одноразовим кодом, експертна оцінка, чек-лист,
об'єктивні показники (вносить один, підтверджує інший) і GET /maturity на seed-даних.

Більшість перевірок — у демо-режимі X-Role; CSRF і «не той самий користувач» — на справжніх сесіях V2.
Записи створюються у власному циклі модуля (POST /api/assessments), seed-цикли 1 і 2 не змінюються.
"""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.annex_v import FORMS
from app.database import SessionLocal, engine
from app.main import app
from app.models import AnnexVResponse, AuditEvent

from v2_helpers import login, make_user

client = TestClient(app)
ADMIN, OFFICER, MANAGER = {"X-Role": "admin"}, {"X-Role": "data_officer"}, {"X-Role": "manager"}
FIRST, LATER = 1, 2            # закриті seed-цикли 2025-II і 2026-I


@pytest.fixture(autouse=True)
def demo(monkeypatch):
    monkeypatch.setenv("INTEGRITY_ANALYTICS_DEMO", "1")


@pytest.fixture(scope="module")
def cycle_id() -> int:
    body = {"name": "SYN Annex V", "start_date": date.today().isoformat(), "categories": ["npp", "cadets"],
            "min_group_size": 5}
    created = client.post("/api/assessments", json=body, headers=ADMIN)
    assert created.status_code == 201, created.text
    cid = created.json()["id"]
    assert client.post(f"/api/assessments/{cid}/activate", headers=ADMIN).status_code == 200
    return cid


def token(cid: int, category: str = "npp") -> str:
    response = client.post(f"/api/assessments/{cid}/tokens", params={"count": 1, "category": category},
                           headers=OFFICER)
    assert response.status_code == 201, response.text
    return response.json()["tokens"][0]


def answers(form: int, letter: str = "c") -> dict:
    return {qid: f"{qid}-{letter}" for qid in FORMS[form]}


def submission(code: str, **override) -> dict:
    return {"access_token": code, "category": "npp", "form": 2, "version": "2.0.0", "answers": answers(2),
            **override}


def submit(cid: int, body: dict):
    return TestClient(app).post(f"/api/assessments/{cid}/annex-v/responses", json=body)


# --- 1. Анонімна анкета ----------------------------------------------------------------------------------------

def test_anonymous_submission_consumes_token_once(cycle_id):
    code = token(cycle_id)
    first = submit(cycle_id, submission(code))
    assert first.status_code == 201 and first.json() == {"status": "accepted"}   # без id і відповідей
    again = submit(cycle_id, submission(code))
    assert again.status_code == 409
    # той самий код не підходить і для анкети персоналу: одна людина — одне подання
    questions = client.get(f"/api/assessments/{cycle_id}/questionnaires").json()
    survey = client.post(f"/api/assessments/{cycle_id}/submissions",
                         json={"token": code, "questionnaire_version": "demo-v1", "respondent_category": "npp",
                               "unit": "Факультет 1",
                               "answers": [{"question_id": q["id"], "value": q["scale"][0]}
                                           for c in questions for q in c["questions"]]})
    assert survey.status_code == 403


def test_submission_requires_matching_category_and_valid_token(cycle_id):
    code = token(cycle_id, "cadets")
    assert submit(cycle_id, submission(code, category="npp")).status_code == 409     # категорія коду інша
    assert submit(cycle_id, submission("невідомий-код")).status_code == 409
    assert submit(cycle_id, submission(code, category="staff")).status_code == 422   # не в категоріях циклу
    assert submit(cycle_id, submission(code, category="cadets")).status_code == 201


@pytest.mark.parametrize("override", [
    {"version": "2.1.0"},
    {"form": 3},
    {"answers": {**answers(2), "av-f2-culture-1": "av-f2-culture-1-z"}},
    {"answers": {k: v for k, v in answers(2).items() if k != "av-f2-system-1"}},
    {"answers": answers(1)},                                       # відповіді форми 1 при form=2
    {"extra": "field"},
])
def test_invalid_submission_is_422_and_token_kept(cycle_id, override):
    code = token(cycle_id)
    assert submit(cycle_id, submission(code, **override)).status_code == 422
    assert submit(cycle_id, submission(code)).status_code == 201                    # код не згорів


def test_closed_cycle_rejects_submission():
    assert submit(FIRST, submission("будь-який")).status_code == 409


def test_whistleblowers_option_f_is_accepted(cycle_id):
    body = submission(token(cycle_id), form=1, answers={**answers(1), "av-f1-accountability-3": "av-f1-accountability-3-f"})
    assert submit(cycle_id, body).status_code == 201


def test_stored_response_has_no_identity_or_time():
    columns = {c["name"] for c in inspect(engine).get_columns("annex_v_responses")}
    assert columns == {"id", "cycle_id", "respondent_category", "form", "version"}
    assert {c["name"] for c in inspect(engine).get_columns("annex_v_answers")} == {
        "id", "response_id", "question_id", "option_id"}


def test_submission_is_not_audited(cycle_id):
    code = token(cycle_id)
    with SessionLocal() as db:
        before = db.query(AuditEvent).count()                       # після видачі коду
        responses_before = db.query(AnnexVResponse).filter_by(cycle_id=cycle_id).count()
    assert submit(cycle_id, submission(code)).status_code == 201
    with SessionLocal() as db:
        assert db.query(AuditEvent).count() == before
        assert db.query(AnnexVResponse).filter_by(cycle_id=cycle_id).count() == responses_before + 1


def test_submission_ignores_session_and_x_role(cycle_id):
    code = token(cycle_id)
    response = client.post(f"/api/assessments/{cycle_id}/annex-v/responses", json=submission(code),
                           headers=ADMIN)
    assert response.status_code == 201


# --- 2. Експертна оцінка ---------------------------------------------------------------------------------------

def expert_body(**override) -> dict:
    return {"expert_label": "Член робочої групи", "form": 1, "version": "2.0.0", "answers": answers(1), **override}


def test_admin_creates_expert_assessment(cycle_id):
    response = client.post(f"/api/assessments/{cycle_id}/annex-v/expert", json=expert_body(), headers=ADMIN)
    assert response.status_code == 201 and set(response.json()) == {"id"}


@pytest.mark.parametrize("headers", [OFFICER, MANAGER, {}])
def test_expert_assessment_roles(cycle_id, headers):
    response = client.post(f"/api/assessments/{cycle_id}/annex-v/expert", json=expert_body(), headers=headers)
    assert response.status_code in (401, 403)


@pytest.mark.parametrize("override", [{"expert_label": "Іван Іванович Петренко"}, {"expert_label": "П. І. Петренко"},
                                      {"expert_label": "ab"}, {"expert_label": "expert@example.test"},
                                      {"form": 2, "answers": answers(2)}, {"version": "1.0"},
                                      {"answers": {"av-f1-culture-1": "av-f1-culture-1-a"}}])
def test_expert_assessment_validation(cycle_id, override):
    response = client.post(f"/api/assessments/{cycle_id}/annex-v/expert", json=expert_body(**override),
                           headers=ADMIN)
    assert response.status_code == 422


def test_expert_assessment_for_draft_is_409():
    draft = client.post("/api/assessments", json={"name": "SYN draft", "start_date": date.today().isoformat(),
                                                   "categories": ["npp"], "min_group_size": 5}, headers=ADMIN)
    response = client.post(f"/api/assessments/{draft.json()['id']}/annex-v/expert", json=expert_body(),
                           headers=ADMIN)
    assert response.status_code == 409


def test_expert_requires_csrf_for_session(cycle_id):
    session, csrf = login(make_user("admin"))
    url = f"/api/assessments/{cycle_id}/annex-v/expert"
    assert session.post(url, json=expert_body()).status_code == 403
    assert session.post(url, json=expert_body(), headers=csrf).status_code == 201


# --- 3. Чек-лист -----------------------------------------------------------------------------------------------

def test_seed_checklist_is_entered_and_mostly_confirmed():
    response = client.get(f"/api/assessments/{LATER}/checklist", headers=MANAGER)
    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["code"] for i in items] == [f"B-{n:02d}" for n in range(1, 21)]
    assert all(i["status"] in {"yes", "partial", "no"} and i["source"] == "Додаток Б (адаптовано)" for i in items)
    assert {i["code"] for i in items if not i["confirmed"]} == {"B-11", "B-16"}
    assert set(items[0]) >= {"code", "criterion", "text", "source", "status", "evidence", "entered_role",
                             "entered_at", "confirmed", "confirmed_role", "confirmed_at"}
    assert "user_id" not in json.dumps(items)


@pytest.mark.parametrize("headers,status", [(ADMIN, 200), (OFFICER, 200), (MANAGER, 200),
                                            ({"X-Role": "respondent"}, 403), ({}, 401)])
def test_checklist_read_roles(headers, status):
    assert client.get(f"/api/assessments/{FIRST}/checklist", headers=headers).status_code == status


def test_checklist_enter_confirm_and_reset(cycle_id):
    url = f"/api/assessments/{cycle_id}/checklist/B-03"
    assert client.post(f"{url}/confirm", headers=ADMIN).status_code == 409                 # ще не заповнено
    entered = client.put(url, json={"status": "partial", "evidence": "  Наказ  №1 "}, headers=OFFICER)
    assert entered.status_code == 200
    item = entered.json()
    assert item["status"] == "partial" and item["evidence"] == "Наказ №1" and item["entered_role"] == "data_officer"
    assert item["confirmed"] is False and item["entered_at"].endswith("Z")
    confirmed = client.post(f"{url}/confirm", headers=ADMIN)
    assert confirmed.status_code == 200 and confirmed.json()["confirmed"] is True
    assert confirmed.json()["confirmed_role"] == "admin"
    assert client.post(f"{url}/confirm", headers=ADMIN).status_code == 409                 # уже підтверджено
    changed = client.put(url, json={"status": "yes"}, headers=OFFICER)
    assert changed.json()["confirmed"] is False and changed.json()["confirmed_role"] is None


def test_checklist_cannot_be_confirmed_by_same_demo_role(cycle_id):
    url = f"/api/assessments/{cycle_id}/checklist/B-04"
    assert client.put(url, json={"status": "yes"}, headers=ADMIN).status_code == 200
    assert client.post(f"{url}/confirm", headers=ADMIN).status_code == 409


@pytest.mark.parametrize("code,body,status", [("B-99", {"status": "yes"}, 404), ("B-01", {"status": "done"}, 422),
                                              ("B-01", {"status": None}, 422),
                                              ("B-01", {"status": "yes", "user": "x"}, 422)])
def test_checklist_put_validation(cycle_id, code, body, status):
    assert client.put(f"/api/assessments/{cycle_id}/checklist/{code}", json=body, headers=OFFICER).status_code == status


@pytest.mark.parametrize("headers", [MANAGER, {"X-Role": "auditor"}])
def test_checklist_write_roles(cycle_id, headers):
    assert client.put(f"/api/assessments/{cycle_id}/checklist/B-01", json={"status": "yes"},
                      headers=headers).status_code == 403
    assert client.post(f"/api/assessments/{cycle_id}/checklist/B-01/confirm", headers=headers).status_code == 403


def test_officer_cannot_confirm(cycle_id):
    url = f"/api/assessments/{cycle_id}/checklist/B-05"
    client.put(url, json={"status": "yes"}, headers=ADMIN)
    assert client.post(f"{url}/confirm", headers=OFFICER).status_code == 403


def test_checklist_sessions_same_user_rejected_other_admin_confirms(cycle_id):
    url = f"/api/assessments/{cycle_id}/checklist/B-06"
    first, first_csrf = login(make_user("admin"))
    second, second_csrf = login(make_user("admin"))
    assert first.put(url, json={"status": "yes"}).status_code == 403                       # без CSRF
    assert first.put(url, json={"status": "yes"}, headers=first_csrf).status_code == 200
    assert first.post(f"{url}/confirm", headers=first_csrf).status_code == 409             # власний запис
    assert second.post(f"{url}/confirm").status_code == 403                                # без CSRF
    response = second.post(f"{url}/confirm", headers=second_csrf)
    assert response.status_code == 200 and response.json()["confirmed"] is True
    with SessionLocal() as db:
        events = [e for e in db.query(AuditEvent).filter_by(assessment_id=cycle_id)
                  if e.action.startswith("checklist.")]
    assert {e.action for e in events} == {"checklist.update", "checklist.confirm"}
    assert {e.details for e in events} == {"{}"}                     # лише роль і цикл, без статусів і доказів
    assert any(e.actor_user_id is not None for e in events)


def test_data_officer_session_enters_checklist(cycle_id):
    officer, csrf = login(make_user("data_officer"))
    url = f"/api/assessments/{cycle_id}/checklist/B-07"
    assert officer.put(url, json={"status": "no"}, headers=csrf).status_code == 200
    assert officer.post(f"{url}/confirm", headers=csrf).status_code == 403


# --- 4. Об'єктивні показники -----------------------------------------------------------------------------------

def indicator(**override) -> dict:
    return {"criterion": "education", "name": "Персонал, що пройшов навчання", "value": 81.5, "target": 90,
            "period": "2026-II", **override}


def test_indicator_enter_and_confirm(cycle_id):
    created = client.post(f"/api/assessments/{cycle_id}/objective-indicators", json=indicator(), headers=OFFICER)
    assert created.status_code == 201
    item = created.json()
    assert item | {"id": 0, "entered_at": ""} == {
        "id": 0, "criterion": "education", "name": "Персонал, що пройшов навчання", "unit": "%", "value": 81.5,
        "target": 90.0, "period": "2026-II", "entered_role": "data_officer", "entered_at": "", "confirmed": False,
        "confirmed_role": None, "confirmed_at": None}
    confirm = client.post(f"/api/objective-indicators/{item['id']}/confirm", headers=ADMIN)
    assert confirm.status_code == 200 and confirm.json()["confirmed"] is True
    assert client.post(f"/api/objective-indicators/{item['id']}/confirm", headers=ADMIN).status_code == 409
    listed = client.get(f"/api/assessments/{cycle_id}/objective-indicators", headers=MANAGER).json()["items"]
    assert any(i["id"] == item["id"] and i["confirmed"] for i in listed)


@pytest.mark.parametrize("override", [{"value": 101}, {"target": -1}, {"value": True}, {"value": "80"},
                                      {"criterion": "maturity"}, {"criterion": "unknown"}, {"name": "ab"},
                                      {"period": "  "}])
def test_indicator_validation(cycle_id, override):
    response = client.post(f"/api/assessments/{cycle_id}/objective-indicators", json=indicator(**override),
                           headers=OFFICER)
    assert response.status_code == 422


def test_indicator_confirm_rules(cycle_id):
    assert client.post("/api/objective-indicators/999999/confirm", headers=ADMIN).status_code == 404
    own = client.post(f"/api/assessments/{cycle_id}/objective-indicators", json=indicator(), headers=ADMIN).json()
    assert client.post(f"/api/objective-indicators/{own['id']}/confirm", headers=ADMIN).status_code == 409
    assert client.post(f"/api/objective-indicators/{own['id']}/confirm", headers=OFFICER).status_code == 403
    assert client.post(f"/api/assessments/{cycle_id}/objective-indicators", json=indicator(),
                       headers=MANAGER).status_code == 403


def test_indicator_sessions_same_user_rejected(cycle_id):
    first, first_csrf = login(make_user("admin"))
    second, second_csrf = login(make_user("admin"))
    url = f"/api/assessments/{cycle_id}/objective-indicators"
    assert first.post(url, json=indicator()).status_code == 403                           # без CSRF
    item = first.post(url, json=indicator(), headers=first_csrf).json()
    assert first.post(f"/api/objective-indicators/{item['id']}/confirm", headers=first_csrf).status_code == 409
    assert second.post(f"/api/objective-indicators/{item['id']}/confirm", headers=second_csrf).status_code == 200


# --- 5. GET /maturity ------------------------------------------------------------------------------------------

def maturity(cid: int, headers=ADMIN):
    return client.get(f"/api/assessments/{cid}/maturity", headers=headers)


def test_maturity_requires_demo_flag(monkeypatch):
    monkeypatch.setenv("INTEGRITY_ANALYTICS_DEMO", "0")
    assert maturity(LATER).status_code == 503


@pytest.mark.parametrize("headers,status", [(OFFICER, 403), ({"X-Role": "respondent"}, 403), ({}, 401),
                                            (MANAGER, 200), ({"X-Role": "auditor"}, 200)])
def test_maturity_roles(headers, status):
    assert maturity(LATER, headers).status_code == status


def test_maturity_only_for_closed_cycle(cycle_id):
    assert maturity(cycle_id).status_code == 409
    assert maturity(999999).status_code == 404


def test_seed_maturity_latest_cycle():
    data = maturity(LATER).json()
    assert data["assessment"] == {"id": LATER, "name": "2026-I", "status": "closed"}
    assert data["methodology_version"] == "annex-v-maturity-0.1" and data["min_group_size"] == 5
    assert data["indices"] == {"self": 62.32, "expert": 47.5, "checklist": 70.0}
    assert data["overall_self_declared"]["level"] == 3.6
    assert [c["key"] for c in data["criteria"]] == ["leadership", "ethics", "education", "openness", "officer",
                                                     "strategy", "risks", "checks", "whistleblowers", "audit"]
    leadership = data["criteria"][0]
    assert leadership["self"] == {"level": 4.6, "responses": 20, "status": "ok"}
    assert leadership["expert"] == {"level": 3.0, "experts": 1, "status": "ok"}
    assert leadership["component_code"] == "C1"
    fired = {r["rule_id"] for r in data["recommendations"]}
    assert fired == {"MAT_SELF_EXPERT_GAP_GE_1", "MAT_SELF_CHECKLIST_GAP_GE_1", "MAT_LOW_LEVEL_LT_3",
                     "MAT_OBJECTIVE_BELOW_TARGET", "MAT_OBJECTIVE_UNCONFIRMED"}


def test_seed_maturity_hides_small_categories_and_individual_answers():
    for cid in (FIRST, LATER):
        data = maturity(cid).json()
        text = json.dumps(data, ensure_ascii=False)
        assert data["visible_categories"] == ["cadets", "npp"] and data["suppressed"] is True
        assert '"mgmt"' not in text and '"staff"' not in text            # staff < k, mgmt — вторинно
        assert "av-f" not in text and "option" not in text               # жодних окремих відповідей
        for criterion in data["criteria"]:
            assert {c["category"] for c in criterion["self_by_category"]} <= {"cadets", "npp"}


def test_seed_maturity_earlier_cycle_numbers():
    data = maturity(FIRST).json()
    assert data["indices"] == {"self": 51.96, "expert": 42.5, "checklist": 53.33}
    assert {r["rule_id"] for r in data["recommendations"]} == {
        "MAT_SELF_EXPERT_GAP_GE_1", "MAT_SELF_CHECKLIST_GAP_GE_1", "MAT_LOW_LEVEL_LT_3",
        "MAT_OBJECTIVE_BELOW_TARGET", "MAT_OBJECTIVE_UNCONFIRMED"}
