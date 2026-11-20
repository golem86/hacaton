from datetime import datetime, timezone
from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app.main import app
from app.services.reporting import HIDDEN, render_xlsx, report_tables
from v2_helpers import login, make_user


def test_export_requires_admin_and_a_closed_cycle():
    path = "/v2/admin/reports/1/export?format=pdf"
    assert TestClient(app).get(path).status_code == 401
    user, _ = login(make_user("user"))
    assert user.get(path).status_code == 403
    admin, _ = login(make_user("admin"))
    for format in ("pdf", "xlsx"):
        assert admin.get(f"/v2/admin/reports/3/export?format={format}").status_code == 409
        assert admin.get(f"/v2/admin/reports/99999/export?format={format}").status_code == 404
    assert admin.get("/v2/admin/reports/1/export?format=csv").status_code == 422


def test_report_rows_keep_hidden_values_hidden_and_user_text_literal():
    results = {
        "assessment": {"id": 1, "name": "{=1+1}", "status": "closed"},
        "responses_total": None,
        "min_group_size": 5,
        "categories": [{"category": "staff", "responses": 2, "hidden": True}],
        "components": [{"code": "C1", "name": "Компонент", "score": None, "by_category": [
            {"category": "staff", "score": 17.2, "hidden": False},
        ]}],
    }
    tables = report_tables(results, datetime(2026, 11, 20, tzinfo=timezone.utc))
    assert tables[0].rows[-1] == ("Анкет у циклі", HIDDEN)
    assert tables[1].rows == [("C1", "Компонент", HIDDEN)]
    assert tables[2].rows == [("Персонал", HIDDEN)]
    assert tables[3].rows == [("C1", "Персонал", HIDDEN)]
    with ZipFile(BytesIO(render_xlsx(tables))) as xlsx:
        strings = xlsx.read("xl/sharedStrings.xml").decode()
        sheet = ElementTree.fromstring(xlsx.read("xl/worksheets/sheet1.xml"))
    assert "{=1+1}" in strings
    assert sheet.find(".//{*}f") is None
