"""
Swagger UI і OpenAPI-схема — лише для адміністратора V2.

Стандартні /docs, /redoc і /openapi.json FastAPI вимкнено (main.py). Замість них:
  - GET /openapi.json — схема API; GET /docs — Swagger UI;
  - обидва доступні лише сесії V2 з пройденою 2FA і роллю admin (require_v2_role("admin"));
    демонстраційний X-Role тут не діє: доступ визначає лише серверна сесія;
  - відповіді не кешуються (Cache-Control: no-store);
  - /redoc і /docs/oauth2-redirect не існують.

Кнопка Execute у Swagger надсилає звичайні HTTP-запити з cookie сесії. Тому:
  - кожен захищений endpoint і далі сам перевіряє сесію й роль — захист не тримається на інтерфейсі;
  - для запитів, що змінюють стан, у схемі оголошено заголовок X-CSRF-Token (кнопка Authorize):
    без чинного CSRF-токена сесії (GET /v2/auth/csrf) backend відповідає 403.
"""
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse

from .request_security import CSRF_HEADER
from .routes.v2_auth import require_v2_role

# Версію Swagger UI зафіксовано (не «@5»), щоб інтерфейс не змінювався без рішення команди
SWAGGER_UI_VERSION = "5.17.14"
SWAGGER_JS_URL = f"https://cdn.jsdelivr.net/npm/swagger-ui-dist@{SWAGGER_UI_VERSION}/swagger-ui-bundle.js"
SWAGGER_CSS_URL = f"https://cdn.jsdelivr.net/npm/swagger-ui-dist@{SWAGGER_UI_VERSION}/swagger-ui.css"
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"}
WRITE_OPERATIONS = {"post", "put", "patch", "delete"}

admin_only = Depends(require_v2_role("admin"))
router = APIRouter(include_in_schema=False)


def build_openapi(app: FastAPI) -> dict[str, Any]:
    """OpenAPI-схема з оголошеним заголовком X-CSRF-Token для операцій, що змінюють стан."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["csrfToken"] = {
        "type": "apiKey", "in": "header", "name": CSRF_HEADER,
        "description": "CSRF-токен поточної сесії: GET /v2/auth/csrf. Сесія — cookie після входу з 2FA.",
    }
    for operations in schema.get("paths", {}).values():
        for method, operation in operations.items():
            if method in WRITE_OPERATIONS:
                operation["security"] = [{"csrfToken": []}]
    app.openapi_schema = schema
    return schema


def install(app: FastAPI) -> None:
    app.openapi = lambda: build_openapi(app)          # type: ignore[method-assign]
    app.include_router(router)


@router.get("/openapi.json", dependencies=[admin_only])
def openapi_schema(request: Request) -> JSONResponse:
    return JSONResponse(request.app.openapi(), headers=NO_STORE_HEADERS)


@router.get("/docs", dependencies=[admin_only])
def swagger_ui() -> HTMLResponse:
    page = get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="Integrity Dashboard API — адміністратор",
        swagger_js_url=SWAGGER_JS_URL,
        swagger_css_url=SWAGGER_CSS_URL,
        swagger_favicon_url="data:,",
        swagger_ui_parameters={"persistAuthorization": False, "withCredentials": True},
    )
    page.headers.update(NO_STORE_HEADERS)
    return page
