"""
Swagger UI і OpenAPI-схема лише для адміністратора V2; backend перевіряє права на кожному endpoint
незалежно від інтерфейсу (кнопка Execute у Swagger — звичайний HTTP-запит).

Демо-режим X-Role ВИМКНЕНО (як у release); окремий тест перевіряє, що навіть увімкнений X-Role
не відкриває /docs і /openapi.json.
"""
import hashlib
import re

import pytest
from fastapi.testclient import TestClient

from app.api_docs import ASSETS_DIR
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
# Swagger UI 5.17.14 з офіційного npm-пакета swagger-ui-dist (integrity tarball звірено з реєстром npm)
VENDORED_SHA256 = {
    "swagger-ui-bundle.js": "c2e4a9ef08144839ff47c14202063ecfe4e59e70a4e7154a26bd50d880c88ba1",
    "swagger-ui.css": "40170f0ee859d17f92131ba707329a88a070e4f66874d11365e9a77d232f6117",
    "LICENSE": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    "NOTICE": "0d20d1adef18aee3f40dd258172155521ce702ac445cb5f7b7d60ed32dad2fb2",
}
ASSET_URLS = ["/docs/swagger-ui/swagger-ui-bundle.js", "/docs/swagger-ui/swagger-ui.css"]
# Фактичні правила CSRF backend для операцій зміни стану (None — CSRF не перевіряється)
EXPECTED_CSRF = {
    ("POST", "/api/assessments/{assessment_id}/submissions"): None,          # публічна анонімна анкета
    ("POST", "/api/assessments/{assessment_id}/tokens"): "session",
    ("POST", "/api/assessments/{assessment_id}/close"): "session",
    ("POST", "/v2/auth/register"): "preauth",
    ("POST", "/v2/auth/login"): "preauth",
    ("POST", "/v2/auth/password-reset/request"): "preauth",
    ("POST", "/v2/auth/password-reset/confirm"): "preauth",
    ("POST", "/v2/auth/2fa/verify"): "session",                              # pending-сесія до 2FA
    ("POST", "/v2/auth/2fa/resend"): "session",
    ("POST", "/v2/auth/logout"): "session",
    ("POST", "/v2/user/attempts"): "session",
    ("PATCH", "/v2/user/attempts/{attempt_id}"): "session",
    ("POST", "/v2/user/attempts/{attempt_id}/complete"): "session",
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

@pytest.mark.parametrize("url", DOC_URLS + ASSET_URLS)
def test_docs_require_login(url):
    assert TestClient(app).get(url).status_code == 401


@pytest.mark.parametrize("url", ["/redoc", "/docs/oauth2-redirect"])
def test_other_docs_routes_do_not_exist(url):
    assert TestClient(app).get(url).status_code == 404


@pytest.mark.parametrize("url", DOC_URLS + ASSET_URLS)
def test_x_role_header_does_not_open_docs_even_in_demo_mode(monkeypatch, url):
    monkeypatch.setenv("INTEGRITY_DEMO_XROLE", "1")
    assert TestClient(app).get(url, headers={"X-Role": "admin"}).status_code == 401


@pytest.mark.parametrize("url", DOC_URLS + ASSET_URLS)
def test_docs_forbidden_for_user_role(url):
    client, _ = login(make_user("user"))
    assert client.get(url).status_code == 403


@pytest.mark.parametrize("url", DOC_URLS + ASSET_URLS)
def test_docs_require_completed_2fa(url):
    client, _ = start_login(make_user("admin"))          # пароль прийнято, 2FA не пройдено
    assert client.get(url).status_code == 401


def test_admin_gets_swagger_ui_without_caching():
    client, _ = login(make_user("admin"))
    response = client.get("/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "swagger-ui" in response.text and "/openapi.json" in response.text
    for url in ASSET_URLS:
        assert f'"{url}"' in response.text                            # JS і CSS — з backend V2
    assert not re.search(r"(src|href)=[\"']?(https?:)?//", response.text)  # жодних зовнішніх ресурсів (CDN)
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("url,content_type", [(ASSET_URLS[0], "text/javascript"), (ASSET_URLS[1], "text/css")])
def test_admin_gets_local_swagger_assets(url, content_type):
    client, _ = login(make_user("admin"))
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(content_type)
    assert response.headers["cache-control"] == "no-store"
    assert hashlib.sha256(response.content).hexdigest() == VENDORED_SHA256[url.rsplit("/", 1)[1]]


@pytest.mark.parametrize("name", ["LICENSE", "NOTICE", "index.html", "oauth2-redirect.html", "..%2F..%2Fapi_docs.py",
                                  "swagger-ui-bundle.js.map", "swagger-initializer.js"])
def test_only_listed_swagger_assets_are_served(name):
    client, _ = login(make_user("admin"))
    assert client.get(f"/docs/swagger-ui/{name}").status_code == 404


def test_vendored_swagger_files_are_unmodified():
    assert {path.name for path in ASSETS_DIR.iterdir()} == set(VENDORED_SHA256)
    for name, digest in VENDORED_SHA256.items():
        assert hashlib.sha256((ASSETS_DIR / name).read_bytes()).hexdigest() == digest, name


def test_admin_gets_openapi_with_csrf_scheme():
    client, _ = login(make_user("admin"))
    response = client.get("/openapi.json")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    schema = response.json()
    scheme = schema["components"]["securitySchemes"]["csrfToken"]
    assert scheme == {**scheme, "type": "apiKey", "in": "header", "name": "X-CSRF-Token"}
    assert "/docs" not in schema["paths"] and "/openapi.json" not in schema["paths"]
    assert not any(path.startswith("/docs/") for path in schema["paths"])
    assert "security" not in schema                                   # глобальної вимоги немає


def test_csrf_in_schema_matches_backend_rules():
    schema = app.openapi()
    actual = {}
    for path, ops in schema["paths"].items():
        for method, op in ops.items():
            if method in {"post", "put", "patch", "delete"}:
                actual[(method.upper(), path)] = op.get("x-csrf")
                assert ("security" in op) == (op.get("x-csrf") is not None), f"{method} {path}"
                if "security" in op:
                    assert op["security"] == [{"csrfToken": []}]
            else:
                assert "security" not in op and "x-csrf" not in op, f"{method} {path}"
    assert actual == EXPECTED_CSRF


@pytest.mark.parametrize("method,path", sorted(op for op, rule in EXPECTED_CSRF.items() if rule))
def test_operations_marked_csrf_really_reject_requests_without_token(method, path):
    # Клієнт, який проходить перевірку ролі, але не надсилає X-CSRF-Token → backend відповідає 403
    if path.startswith("/v2/auth/"):
        client = TestClient(app)
    else:
        client, _ = login(make_user("user" if path.startswith("/v2/user/") else "admin"))
    response = client.request(method, concrete(path), json={})
    assert response.status_code == 403, f"{method} {path} → {response.status_code}"
    assert "CSRF" in response.json()["detail"]


def test_public_anonymous_submission_is_not_blocked_by_csrf():
    response = TestClient(app).post(concrete("/api/assessments/{assessment_id}/submissions"), json={})
    assert response.status_code == 422                                # перевірка даних анкети, а не CSRF


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
