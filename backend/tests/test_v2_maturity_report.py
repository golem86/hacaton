"""
Звіт зрілості за Додатком В: GET /v2/admin/reports/{id}/maturity-export?format=pdf|xlsx.
Доступ лише admin (сесія V2), ті самі умови, що й GET /api/assessments/{id}/maturity,
значення XLSX = відповідь /maturity, журнал report.maturity_export.
"""
import re
from datetime import date, datetime, timezone
from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import AuditEvent
from app.services import maturity, maturity_report
from app.services.reporting import HIDDEN, MISSING
from v2_helpers import login, make_user

LATER = 2                       # закритий seed-цикл 2026-I
PDF_TYPE = "application/pdf"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
X_ADMIN = {"X-Role": "admin"}


def path(cid: int, format: str = "xlsx") -> str:
    return f"/v2/admin/reports/{cid}/maturity-export?format={format}"


@pytest.fixture(autouse=True)
def demo(monkeypatch):
    monkeypatch.setenv("INTEGRITY_ANALYTICS_DEMO", "1")


@pytest.fixture(scope="module")
def admin():
    client, _ = login(make_user("admin"))
    return client


def read_xlsx(content: bytes) -> dict[str, list[list]]:
    """Аркуші XLSX як списки рядків (рядки — str, числа — float); без сторонніх бібліотек."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rel_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    with ZipFile(BytesIO(content)) as book:
        strings = [("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
                   for si in ElementTree.fromstring(book.read("xl/sharedStrings.xml")).findall("m:si", ns)]
        rels = {r.get("Id"): r.get("Target") for r in ElementTree.fromstring(book.read("xl/_rels/workbook.xml.rels"))}
        workbook = ElementTree.fromstring(book.read("xl/workbook.xml"))
        sheets = {}
        for sheet in workbook.find("m:sheets", ns):
            xml = ElementTree.fromstring(book.read("xl/" + rels[sheet.get(rel_ns)]))
            assert xml.find(".//m:f", ns) is None                  # жодних формул
            rows = []
            for row in xml.iter(f"{{{ns['m']}}}row"):
                while len(rows) < int(row.get("r")) - 1:
                    rows.append([])                                 # порожні рядки в XML не пишуться
                cells = []
                for cell in row.findall("m:c", ns):
                    column = ord(re.match(r"[A-Z]", cell.get("r")).group()) - ord("A")
                    while len(cells) < column:
                        cells.append(None)
                    value = cell.find("m:v", ns)
                    if value is None:
                        cells.append(None)
                    elif cell.get("t") == "s":
                        cells.append(strings[int(value.text)])
                    else:
                        cells.append(float(value.text))
                rows.append(cells)
            sheets[sheet.get("name")] = rows
    return sheets


def table(rows: list[list], header_first: str) -> list[list]:
    """Рядки таблиці під заголовком, що починається з header_first, до порожнього рядка."""
    start = next(i for i, row in enumerate(rows) if row and row[0] == header_first)
    body = []
    for row in rows[start + 1:]:
        if not row or row[0] is None:
            break
        body.append(row)
    return body


# --- доступ ----------------------------------------------------------------------------------------------------

def test_requires_admin_session():
    assert TestClient(app).get(path(LATER)).status_code == 401
    for role in ("user", "data_officer"):
        client, _ = login(make_user(role))
        assert client.get(path(LATER)).status_code == 403
    # демо X-Role не є сесією V2
    assert TestClient(app).get(path(LATER), headers=X_ADMIN).status_code == 401


def test_same_conditions_as_maturity(admin, monkeypatch):
    for format in ("pdf", "xlsx"):
        assert admin.get(path(99999, format)).status_code == 404
    assert admin.get(path(0)).status_code == 422
    assert admin.get(path(2 ** 63)).status_code == 422
    assert admin.get(f"/v2/admin/reports/{LATER}/maturity-export?format=csv").status_code == 422
    assert admin.get(f"/v2/admin/reports/{LATER}/maturity-export").status_code == 422

    body = {"name": "SYN maturity export", "start_date": date.today().isoformat(), "categories": ["npp"],
            "min_group_size": 5}
    created = TestClient(app).post("/api/assessments", json=body, headers=X_ADMIN)
    assert created.status_code == 201, created.text
    open_id = created.json()["id"]
    response = admin.get(path(open_id, "pdf"))
    assert response.status_code == 409
    assert TestClient(app).get(f"/api/assessments/{open_id}/maturity", headers=X_ADMIN).status_code == 409

    monkeypatch.setenv("INTEGRITY_ANALYTICS_DEMO", "0")
    assert admin.get(path(LATER)).status_code == 503


# --- формати й заголовки ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("format,media", [("pdf", PDF_TYPE), ("xlsx", XLSX_TYPE)])
def test_formats_and_headers(admin, format, media):
    response = admin.get(path(LATER, format))
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == media
    disposition = response.headers["content-disposition"]
    assert disposition == f'attachment; filename="maturity-report-{LATER}.{format}"'
    assert disposition.isascii()
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_pdf_is_pdf_with_embedded_cyrillic_font(admin):
    content = admin.get(path(LATER, "pdf")).content
    assert content.startswith(b"%PDF")
    assert re.search(rb"/BaseFont\s*/[A-Z]{6}\+DejaVuSans", content)    # підмножина DejaVuSans (кирилиця)


# --- вміст = /maturity -----------------------------------------------------------------------------------------

def test_xlsx_values_match_maturity_endpoint(admin):
    data = TestClient(app).get(f"/api/assessments/{LATER}/maturity", headers=X_ADMIN).json()
    sheets = read_xlsx(admin.get(path(LATER, "xlsx")).content)
    assert list(sheets) == ["Зрілість", "Розриви й пропозиції", "Джерела"]

    main = sheets["Зрілість"]
    assert main[0][0] == maturity_report.TITLE
    assert any(row and row[0] == maturity_report.SYNTHETIC_NOTE for row in main)   # seed — синтетична БД
    summary = {row[0]: row[1] for row in table(main, "Показник")}
    assert summary["Назва циклу"] == "2026-I" and summary["Версія методики"] == maturity.VERSION
    assert summary["Дані"] == "Синтетичні (демонстрація)"
    assert summary["Поріг групи (k)"] == data["min_group_size"]
    assert summary["Групи, менші за поріг"] == HIDDEN                 # seed: малі групи є
    assert summary["Індекс самооцінювання (0–100)"] == data["indices"]["self"]
    assert summary["Експертний індекс (0–100)"] == data["indices"]["expert"]
    assert summary["Індекс чек-листа (0–100)"] == data["indices"]["checklist"]

    levels = table(main, "Критерій")
    assert [row[0] for row in levels] == [c["name_uk"] for c in data["criteria"]]
    for row, c in zip(levels, data["criteria"]):
        final, source = maturity.base_level(c["self"]["level"], c["expert"]["level"])
        assert row[1:9] == [c["self"]["level"], c["self"]["responses"], c["expert"]["level"], c["expert"]["experts"],
                            c["checklist"]["level"],
                            f'{c["checklist"]["items_confirmed"]} з {c["checklist"]["items_total"]}',
                            final, maturity_report.SOURCE_NAMES[source]]

    gaps_sheet = sheets["Розриви й пропозиції"]
    gaps = table(gaps_sheet, "Критерій")
    for row, c in zip(gaps, data["criteria"]):
        by_right = {g["right"]: g for g in c["gaps"]}
        for diff_cell, flag_cell, gap in ((row[1], row[2], by_right["expert"]), (row[3], row[4], by_right["checklist"])):
            assert diff_cell == gap["diff"]
            assert flag_cell == (maturity_report.FLAG_YES if gap["flag"] else maturity_report.FLAG_NO)
    recs_start = next(i for i, row in enumerate(gaps_sheet) if row and row[0] == "Пропозиції (чернетка для робочої групи)")
    recs = table(gaps_sheet[recs_start:], "Критерій")
    assert [(row[1], row[2]) for row in recs] == [(r["rule_id"], r["text"]) for r in data["recommendations"]]
    rules = table(gaps_sheet, "Код правила")
    assert {row[0] for row in rules} == set(maturity.RULE_CONDITIONS)
    assert {r["rule_id"] for r in data["recommendations"]} <= set(maturity.RULE_CONDITIONS)

    sources = {row[0]: row[1] for row in table(sheets["Джерела"], "Розділ")}
    assert "k = 5" in sources["Самооцінювання"]
    assert "посадою" in sources["Експерт"] and "не особою" in sources["Експерт"]
    assert "чернетка для робочої групи" in sources["Пропозиції"]
    assert sources["Правило рівнів"] == data["level_rule"]


def test_xlsx_does_not_list_hidden_categories(admin):
    text = repr(read_xlsx(admin.get(path(LATER, "xlsx")).content))
    for hidden in ("Керівництво", "Персонал", "mgmt", "staff"):           # seed: staff < k, mgmt — вторинно
        assert hidden not in text


def test_export_is_audited_without_details(admin):
    with SessionLocal() as db:
        before = db.query(AuditEvent).filter(AuditEvent.action == "report.maturity_export").count()
    assert admin.get(path(LATER, "pdf")).status_code == 200
    assert admin.get(path(99999, "pdf")).status_code == 404               # невдала спроба не журналюється
    with SessionLocal() as db:
        events = (db.query(AuditEvent).filter(AuditEvent.action == "report.maturity_export")
                  .order_by(AuditEvent.id).all())
    assert len(events) == before + 1
    event = events[-1]
    assert event.actor_role == "admin" and event.assessment_id == LATER
    assert isinstance(event.actor_user_id, int) and event.actor_user_id >= 1
    assert event.details == "{}"


# --- подання без БД --------------------------------------------------------------------------------------------

def sample(**override) -> dict:
    gaps = [{"rule_id": maturity.RULE_SELF_EXPERT, "left": "self", "right": "expert", "diff": None, "flag": False},
            {"rule_id": maturity.RULE_SELF_CHECKLIST, "left": "self", "right": "checklist", "diff": None,
             "flag": False}]
    data = {
        "assessment": {"id": 9, "name": "=1+1", "status": "closed"}, "methodology_version": maturity.VERSION,
        "level_rule": "a=1…e=5", "min_group_size": 5, "suppressed": True,
        "criteria": [{"key": "ethics", "name_uk": "Етичні стандарти", "component_code": "C1",
                      "self": {"level": None, "responses": None, "status": "suppressed"}, "self_by_category": [],
                      "expert": {"level": None, "experts": 0, "status": "missing"},
                      "checklist": {"level": None, "items_total": 2, "items_confirmed": 0, "status": "missing"},
                      "objective": [], "gaps": gaps}],
        "overall_self_declared": {"level": None, "responses": None, "status": "suppressed", "expert_level": None},
        "indices": {"self": None, "expert": None, "checklist": None}, "recommendations": [],
    }
    data.update(override)
    return data


def test_hidden_and_missing_values_never_become_zero():
    doc = maturity_report.build(sample(), datetime(2026, 11, 20, tzinfo=timezone.utc), synthetic=False)
    assert doc.notes == (maturity_report.NOTE,)
    sheets = read_xlsx(maturity_report.render(doc, "xlsx"))
    levels = table(sheets["Зрілість"], "Критерій")
    assert levels == [["Етичні стандарти", HIDDEN, HIDDEN, MISSING, 0.0, MISSING, "0 з 2", MISSING, "—"]]
    summary = {row[0]: row[1] for row in table(sheets["Зрілість"], "Показник")}
    assert summary["Назва циклу"] == "=1+1"                                # літеральний текст, не формула
    assert summary["Дані"] == "Не позначені як синтетичні"
    assert summary["Експертний індекс (0–100)"] == maturity_report.NOT_COMPUTED
    gaps = table(sheets["Розриви й пропозиції"], "Критерій")
    assert gaps[0] == ["Етичні стандарти", MISSING, "—", MISSING, "—"]
    assert maturity_report.render(doc, "pdf").startswith(b"%PDF")


def test_base_level_follows_methodology():
    assert maturity.base_level(4.2, 2.8) == (2.8, "expert")
    assert maturity.base_level(4.2, None) == (4.2, "self")
    assert maturity.base_level(None, None) == (None, None)
