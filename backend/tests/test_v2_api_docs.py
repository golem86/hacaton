"""
Swagger UI і OpenAPI-схема лише для адміністратора V2; backend перевіряє права на кожному endpoint
незалежно від інтерфейсу (кнопка Execute у Swagger — звичайний HTTP-запит).

Демо-режим X-Role ВИМКНЕНО (як у release); окремий тест перевіряє, що навіть увімкнений X-Role
не відкриває /docs і /openapi.json.
"""
import re

import pytest
from fastapi.testclient import TestClient

from app.main import app

from v2_helpers import login, make_user, start_login

OPEN_ID = 3
DOC_URLS = ["/docs", "/openapi.json"]

# Endpoint-и, публічні за V2 Integration Contract (розділ 2.1): усі інші мають відмовляти без сесії
PUBLIC = {
    ("GET", "/"), ("GET", "/api/health"),
    ("GET", "/api/assessments"), ("GET", "/api/assessments/{assessment_id}"),
    ("GET", "/api/assessments/{assessment_id}/questionnaires"), ("GET", "/api/units"),
    ("POST", "/api/assessments/{assessment_id}/submissions"),            # анонімно, лише за одноразовим кодом
}
PATH_VALUES = {"assessment_id": str(OPEN_ID), "attempt_id": "nonexistent", "version": "team-results-demo-0.1"}


@pytest.fixture(autouse=True)
def no_demo_xrole(monkeypatch):
    monkeypatch.setenv("INTEGRITY_DEMO_XROLE", "0")


def schema_operations():
    for path, ops in app.openapi()["paths"].items():
        for method in ops:
            yield method.upper(), path


def concrete(path: str) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: PATH_VALUES[m.group(1)], path)


# --- Swagger UI і схема ------------------------------------------------------------------------------------

@pytest.mark.parametrize("url", DOC_URLS)
def test_docs_require_login(url):
    assert TestClient(app).get(url).status_code == 401


@pytest.mark.parametrize("url", ["/redoc", "/docs/oauth2-redirect"])
def test_other_docs_routes_do_not_exist(url):
    assert TestClient(app).get(url).status_code == 404


@pytest.mark.parametrize("url", DOC_URLS)
def test_x_role_header_does_not_open_docs_even_in_demo_mode(monkeypatch, url):
    monkeypatch.setenv("INTEGRITY_DEMO_XROLE", "1")
    assert TestClient(app).get(url, headers={"X-Role": "admin"}).status_code == 401


@pytest.mark.parametrize("url", DOC_URLS)
def test_docs_forbidden_for_user_role(url):
    client, _ = login(make_user("user"))
    assert client.get(url).status_code == 403


@pytest.mark.parametrize("url", DOC_URLS)
def test_docs_require_completed_2fa(url):
    client, _ = start_login(make_user("admin"))          # пароль прийнято, 2FA не пройдено
    assert client.get(url).status_code == 401


def test_admin_gets_swagger_ui_without_caching():
    client, _ = login(make_user("admin"))
    response = client.get("/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "swagger-ui" in response.text and "/openapi.json" in response.text
    assert "swagger-ui-dist@5.17.14" in response.text                 # версію зафіксовано
    assert response.headers["cache-control"] == "no-store"


def test_admin_gets_openapi_with_csrf_scheme_for_write_operations():
    client, _ = login(make_user("admin"))
    response = client.get("/openapi.json")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    schema = response.json()
    scheme = schema["components"]["securitySchemes"]["csrfToken"]
    assert scheme == {**scheme, "type": "apiKey", "in": "header", "name": "X-CSRF-Token"}
    for path, ops in schema["paths"].items():
        for method, op in ops.items():
            if method in {"post", "put", "patch", "delete"}:
                assert op.get("security") == [{"csrfToken": []}], f"{method} {path}"
    assert "/docs" not in schema["paths"] and "/openapi.json" not in schema["paths"]


# --- Backend перевіряє права на кожному endpoint (не лише інтерфейс) ------------------------------------------

def test_schema_has_no_unexpected_public_operations():
    operations = set(schema_operations())
    assert PUBLIC <= operations
    assert len(operations) > len(PUBLIC) + 20                        # схема справді містить захищені операції


@pytest.mark.parametrize("method,path", sorted(op for op in schema_operations() if op not in PUBLIC and not op[1].startswith("/v2/auth/")))
def test_every_protected_endpoint_rejects_anonymous_request(method, path):
    # Імітація Execute без сесії, зокрема з підробленим X-Role
    response = TestClient(app).request(method, concrete(path), headers={"X-Role": "admin"})
    assert response.status_code in (401, 403), f"{method} {path} → {response.status_code}"


@pytest.mark.parametrize("method,path", sorted(op for op in schema_operations()
                                                 if op[1].startswith(("/api/", "/v2/admin/")) and op not in PUBLIC))
def test_admin_endpoints_forbidden_for_user_session(method, path):
    client, csrf = login(make_user("user"))
    response = client.request(method, concrete(path), headers=csrf)
    assert response.status_code == 403, f"{method} {path} → {response.status_code}"


@pytest.mark.parametrize("method,path", sorted(op for op in schema_operations() if op[1].startswith("/v2/user/")))
def test_personal_endpoints_forbidden_for_admin_session(method, path):
    client, csrf = login(make_user("admin"))
    response = client.request(method, concrete(path), headers=csrf)
    assert response.status_code == 403, f"{method} {path} → {response.status_code}"


def test_execute_write_without_csrf_is_rejected_for_admin_session():
    client, _ = login(make_user("admin"))
    assert client.post(f"/api/assessments/{OPEN_ID}/tokens", params={"count": 1}).status_code == 403


def test_execute_write_with_session_csrf_succeeds_for_admin():
    client, csrf = login(make_user("admin"))
    token = client.get("/v2/auth/csrf").json()["csrf_token"]          # як «Authorize» у Swagger
    assert {"X-CSRF-Token": token} == csrf
    assert client.post(f"/api/assessments/{OPEN_ID}/tokens", params={"count": 1}, headers=csrf).status_code == 201
