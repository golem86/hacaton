"""
GET /api/assessments/{id}/annex-v/expert — перегляд внесених експертних оцінок (Анкета 1 Додатка В).

Лише admin; тексти питань і варіантів та рівні — з серверного каталогу annex_v (дзеркало catalog-v2.ts),
експерт — посада без ПІБ; записи за часом внесення; читання не журналюється.
Записи створюються у власному циклі тесту, seed-цикли не змінюються.
"""
import json
import re
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.annex_v import CRITERIA, FORMS, LEVEL_MAPS, LEVELS, OPTION_TEXTS, QUESTION_TEXTS, option_text
from app.database import SessionLocal
from app.main import app
from app.models import AnnexVExpertAssessment, AuditEvent

from v2_helpers import login, make_user, start_login

client = TestClient(app)
ADMIN, OFFICER, MANAGER = {"X-Role": "admin"}, {"X-Role": "data_officer"}, {"X-Role": "manager"}
CATALOG_V2 = Path(__file__).resolve().parents[2] / "frontend" / "src" / "official" / "catalog-v2.ts"
ITEM_KEYS = {"id", "expert_label", "form", "version", "created_at", "entered_role", "entered_by_user_id", "answers"}
ANSWER_KEYS = {"question_id", "question", "criterion", "option_id", "option", "level"}


def new_cycle(activate: bool = True) -> int:
    body = {"name": "SYN Annex V experts", "start_date": date.today().isoformat(), "categories": ["npp"],
            "min_group_size": 5}
    created = client.post("/api/assessments", json=body, headers=ADMIN)
    assert created.status_code == 201, created.text
    cid = created.json()["id"]
    if activate:
        assert client.post(f"/api/assessments/{cid}/activate", headers=ADMIN).status_code == 200
    return cid


def answers(letter: str = "c", **override: str) -> dict:
    result = {qid: f"{qid}-{letter}" for qid in FORMS[1]}
    result.update({f"av-f1-{key}": f"av-f1-{key}-{value}" for key, value in override.items()})
    return result


def add_expert(cid: int, label: str, chosen: dict) -> int:
    body = {"expert_label": label, "form": 1, "version": "2.0.0", "answers": chosen}
    response = client.post(f"/api/assessments/{cid}/annex-v/expert", json=body, headers=ADMIN)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def url(cid) -> str:
    return f"/api/assessments/{cid}/annex-v/expert"


@pytest.fixture(scope="module")
def filled() -> dict:
    """Цикл із двома експертами; час першого запису зсунуто пізніше, щоб перевірити сортування за created_at."""
    cid = new_cycle()
    later = add_expert(cid, "Заступник начальника з навчальної роботи",
                       answers("e", **{"culture-4": "a", "culture-5": "d", "accountability-3": "f"}))
    earlier = add_expert(cid, "Член робочої групи", answers("b", **{"accountability-3": "e"}))
    with SessionLocal() as db:
        db.get(AnnexVExpertAssessment, later).created_at = datetime(2030, 1, 2, 9, 0, 0)
        db.get(AnnexVExpertAssessment, earlier).created_at = datetime(2030, 1, 1, 9, 0, 0)
        db.commit()
    return {"cid": cid, "earlier": earlier, "later": later}


# --- доступ ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("headers,status", [(ADMIN, 200), (OFFICER, 403), (MANAGER, 403),
                                            ({"X-Role": "auditor"}, 403), ({"X-Role": "respondent"}, 403),
                                            ({}, 401)])
def test_only_admin_reads_expert_assessments(filled, headers, status):
    assert client.get(url(filled["cid"]), headers=headers).status_code == status


@pytest.mark.parametrize("role,status", [("admin", 200), ("data_officer", 403), ("user", 403)])
def test_session_roles(filled, monkeypatch, role, status):
    monkeypatch.setenv("INTEGRITY_DEMO_XROLE", "0")
    session, _ = login(make_user(role))
    assert session.get(url(filled["cid"])).status_code == status       # GET без CSRF


def test_session_without_2fa_and_anonymous_are_401(filled, monkeypatch):
    monkeypatch.setenv("INTEGRITY_DEMO_XROLE", "0")
    pending, _ = start_login(make_user("admin"))
    assert pending.get(url(filled["cid"])).status_code == 401
    assert TestClient(app).get(url(filled["cid"]), headers=ADMIN).status_code == 401   # X-Role вимкнено


def test_unknown_cycle_is_404_and_bad_id_is_422():
    assert client.get(url(999_999_999), headers=ADMIN).status_code == 404
    for bad in ("0", "-1", "abc", str(2 ** 63)):
        assert client.get(url(bad), headers=ADMIN).status_code == 422


def test_reading_is_not_audited(filled):
    with SessionLocal() as db:
        before = db.query(AuditEvent).count()
    assert client.get(url(filled["cid"]), headers=ADMIN).status_code == 200
    with SessionLocal() as db:
        assert db.query(AuditEvent).count() == before


# --- структура й значення --------------------------------------------------------------------------------------

def test_empty_cycle_and_draft():
    for cid in (new_cycle(), new_cycle(activate=False)):
        body = client.get(url(cid), headers=ADMIN).json()
        assert body["assessment_id"] == cid and body["form"] == 1 and body["version"] == "2.0.0"
        assert body["count"] == 0 and body["items"] == []
        assert [c["criterion"] for c in body["by_criterion"]] == list(dict.fromkeys(
            q["criterion"] for q in FORMS[1].values()))
        assert all(c["levels"] == [] and c["mean"] is None for c in body["by_criterion"])


def test_structure_order_and_no_personal_fields(filled):
    body = client.get(url(filled["cid"]), headers=ADMIN).json()
    assert set(body) == {"assessment_id", "form", "version", "count", "items", "by_criterion"}
    assert body["count"] == 2
    assert [item["id"] for item in body["items"]] == [filled["earlier"], filled["later"]]   # за created_at
    first = body["items"][0]
    assert set(first) == ITEM_KEYS
    assert first["expert_label"] == "Член робочої групи"
    assert first["created_at"] == "2030-01-01T09:00:00Z"
    assert first["entered_role"] == "admin" and first["entered_by_user_id"] is None   # демо X-Role без id
    assert first["form"] == 1 and first["version"] == "2.0.0"
    assert all(set(answer) == ANSWER_KEYS for item in body["items"] for answer in item["answers"])
    text = json.dumps(body, ensure_ascii=False)
    for forbidden in ("email", "full_name", "\"name\"", "password", "@"):
        assert forbidden not in text
    assert set(body["by_criterion"][0]) == {"criterion", "title", "levels", "mean"}


def test_answers_follow_catalog_texts_and_levels(filled):
    body = client.get(url(filled["cid"]), headers=ADMIN).json()
    later = body["items"][1]
    assert [a["question_id"] for a in later["answers"]] == list(FORMS[1])               # порядок каталогу
    for answer in later["answers"]:
        question = FORMS[1][answer["question_id"]]
        assert answer["criterion"] == question["criterion"]
        assert answer["question"] == QUESTION_TEXTS[answer["question_id"]]
        assert answer["level"] == question["options"][answer["option_id"]]
        assert answer["option"] == option_text(question["criterion"], answer["option_id"])
        assert answer["option"] in OPTION_TEXTS[question["criterion"]]
    by_id = {a["question_id"]: a for a in later["answers"]}
    assert by_id["av-f1-accountability-3"]["option_id"].endswith("-f") and by_id["av-f1-accountability-3"]["level"] == 5
    assert by_id["av-f1-accountability-3"]["option"] == OPTION_TEXTS["whistleblowers"][5]
    assert by_id["av-f1-culture-1"]["option"] == OPTION_TEXTS["leadership"][4]


def test_by_criterion_levels_and_mean(filled):
    body = client.get(url(filled["cid"]), headers=ADMIN).json()
    summary = {c["criterion"]: c for c in body["by_criterion"]}
    assert set(summary) == set(CRITERIA)
    assert all(summary[key]["title"] == CRITERIA[key]["name_uk"] for key in summary)
    # експерти в порядку записів: спершу «b» (рівень 2), потім «e» (рівень 5)
    assert summary["leadership"] == {"criterion": "leadership", "title": CRITERIA["leadership"]["name_uk"],
                                     "levels": [2.0, 5.0], "mean": 3.5}
    assert summary["openness"]["levels"] == [2.0, 2.5]            # (a=1 + d=4) / 2 в межах одного запису
    assert summary["openness"]["mean"] == 2.25
    assert summary["whistleblowers"]["levels"] == [4.0, 5.0]      # e=4, f=5 за Додатком Г
    assert summary["whistleblowers"]["mean"] == 4.5
    assert all(len(c["levels"]) == body["count"] for c in body["by_criterion"])


def test_record_outside_current_catalog_is_listed_but_not_summarised():
    cid = new_cycle()
    with SessionLocal() as db:
        db.add(AnnexVExpertAssessment(cycle_id=cid, expert_label="Експерт попередньої редакції", form=1,
                                      version="1.0.0", answers_json=json.dumps({"av-f1-culture-1": "av-f1-culture-1-z"}),
                                      entered_role="admin", entered_by_user_id=None, created_at=datetime(2030, 1, 1)))
        db.commit()
    body = client.get(url(cid), headers=ADMIN).json()
    assert body["count"] == 1
    assert body["items"][0]["answers"] == [{"question_id": "av-f1-culture-1", "question": QUESTION_TEXTS["av-f1-culture-1"],
                                            "criterion": "leadership", "option_id": "av-f1-culture-1-z",
                                            "option": None, "level": None}]
    assert all(c["levels"] == [] and c["mean"] is None for c in body["by_criterion"])


def test_session_admin_id_is_returned():
    session, csrf = login(make_user("admin"))
    cid = new_cycle()
    body = {"expert_label": "Голова робочої групи", "form": 1, "version": "2.0.0", "answers": answers("d")}
    assert session.post(url(cid), json=body, headers=csrf).status_code == 201
    listed = session.get(url(cid)).json()
    assert listed["items"][0]["entered_role"] == "admin"
    assert isinstance(listed["items"][0]["entered_by_user_id"], int)


# --- каталог текстів ------------------------------------------------------------------------------------------

def test_server_texts_mirror_frontend_catalog():
    """Тексти форми 1 на сервері — дослівно ті самі, що у fullTemplates (catalog-v2.ts, редакція 2.0.0)."""
    source = CATALOG_V2.read_text(encoding="utf-8")
    choices = source[source.index("const choices = {"):source.index("} as const")]
    frontend_options = {key: tuple(re.findall(r"^    '(.*)',$", block, re.M))
                        for key, block in re.findall(r"^  (\w+): \[\n(.*?)\n  \],", choices, re.M | re.S)}
    assert frontend_options == {key: tuple(texts) for key, texts in OPTION_TEXTS.items()}
    sections = {"1": "culture", "2": "system", "3": "accountability", "4": "maturity"}
    form1 = source[source.index("const form1"):source.index("const form2")]
    frontend_questions = {f"av-f1-{sections[s]}-{n}": text for s, n, text in
                          re.findall(r"section: (\d), number: (\d+), page: \d+, text: '(.*?)'", form1)}
    assert frontend_questions == QUESTION_TEXTS
    assert set(QUESTION_TEXTS) == set(FORMS[1])
    for qid, question in FORMS[1].items():
        assert len(OPTION_TEXTS[question["criterion"]]) == len(LEVEL_MAPS.get(question["criterion"], LEVELS))
