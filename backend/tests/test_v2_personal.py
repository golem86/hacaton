"""Персональний контур V2: власник лише з сесії, CSRF, незмінність завершених спроб, Reporting."""
from io import BytesIO
from zipfile import ZipFile

from v2_helpers import login, make_user

ALL_ANSWERS = {f"q{i}": 3 for i in range(1, 8)}


def test_personal_attempts_are_server_owned_and_completed_attempts_are_immutable():
    client_a, csrf_a = login(make_user())
    catalog = client_a.get("/v2/user/assessments")
    assert catalog.status_code == 200 and catalog.json()[0]["questions"]
    attempt = client_a.post("/v2/user/attempts", headers=csrf_a, json={
        "id": "attempt-owned-by-a", "assessment_id": "personal-2026-q4", "answers": {"q1": 3}})
    assert attempt.status_code == 201

    client_b, csrf_b = login(make_user())
    assert client_b.get("/v2/user/attempts/attempt-owned-by-a").status_code == 404
    assert client_b.patch("/v2/user/attempts/attempt-owned-by-a", headers=csrf_b,
                          json={"answers": {"q1": 5}}).status_code == 404
    assert client_b.post("/v2/user/attempts", headers=csrf_b, json={
        "id": "attempt-owned-by-a", "assessment_id": "personal-2026-q4", "answers": {"q1": 1}}).status_code == 404

    url = "/v2/user/attempts/attempt-owned-by-a/complete"
    assert client_a.post(url, headers=csrf_a, json={"answers": ALL_ANSWERS}).status_code == 200
    assert client_a.post(url, headers=csrf_a, json={"answers": ALL_ANSWERS}).status_code == 409
    assert client_a.patch("/v2/user/attempts/attempt-owned-by-a", headers=csrf_a,
                          json={"answers": {"q1": 1}}).status_code == 409
    assert client_a.get("/v2/user/stats").json()["completed_tests"] == 1


def test_personal_answers_reject_non_integer_values():
    client, csrf = login(make_user())
    for bad in ("4", 4.5, True):
        response = client.post("/v2/user/attempts", headers=csrf,
                               json={"assessment_id": "personal-2026-q4", "answers": {"q1": bad}})
        assert response.status_code == 422, bad


def test_admin_report_exposes_only_allowed_aggregates():
    client, _ = login(make_user("admin"))
    report = client.get("/v2/admin/reports/1")
    assert report.status_code == 200
    assert report.headers["cache-control"] == "no-store"
    assert report.json()["official_index"] is None
    assert report.json()["aggregates"] == client.get("/api/assessments/1/results").json()
    assert report.json()["exports"] == {"pdf": "available", "xlsx": "available"}
    for format, media_type, signature in (
        ("pdf", "application/pdf", b"%PDF"),
        ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", b"PK"),
    ):
        file = client.get(f"/v2/admin/reports/1/export?format={format}")
        assert file.status_code == 200
        assert file.headers["content-type"] == media_type
        assert file.headers["content-disposition"] == f'attachment; filename="integrity-report-1.{format}"'
        assert file.headers["cache-control"] == "no-store"
        assert file.content.startswith(signature)
        if format == "xlsx":
            with ZipFile(BytesIO(file.content)) as xlsx:
                assert xlsx.testzip() is None
                strings = xlsx.read("xl/sharedStrings.xml").decode()
                assert "Бали компонентів" in strings and "Приховано" in strings


def test_prototype_duplicate_admin_routes_are_removed():
    client, _ = login(make_user("admin"))
    for path in ("/v2/admin/assessments", "/v2/admin/assessments/1", "/v2/admin/assessments/1/results",
                 "/v2/admin/comparisons?assessment_id=1&comparison_assessment_id=2"):
        assert client.get(path).status_code == 404, path
