"""
Swagger UI і OpenAPI-схема — лише для адміністратора V2.

Стандартні /docs, /redoc і /openapi.json FastAPI вимкнено (main.py). Замість них:
  - GET /openapi.json — схема API; GET /docs — Swagger UI;
  - GET /docs/swagger-ui/<файл> — JS і CSS Swagger UI з репозиторію (без CDN і зовнішніх запитів);
  - усе це доступне лише сесії V2 з пройденою 2FA і роллю admin (require_v2_role("admin"));
    демонстраційний X-Role тут не діє: доступ визначає лише серверна сесія;
  - відповіді не кешуються (Cache-Control: no-store);
  - /redoc і /docs/oauth2-redirect не існують.

Кнопка Execute у Swagger надсилає звичайні HTTP-запити з cookie сесії. Тому:
  - кожен захищений endpoint і далі сам перевіряє сесію й роль — захист не тримається на інтерфейсі;
  - заголовок X-CSRF-Token (кнопка Authorize) у схемі оголошено ЛИШЕ для тих операцій, де backend
    справді його перевіряє. Вимогу визначено з залежностей маршруту, а не з HTTP-методу:
      session — токен сесії (require_session_csrf; require_role / require_v2_role для запитів зміни);
      preauth — токен pre-auth cookie або сесії (require_preauth_csrf: реєстрація, вхід, скидання пароля);
    публічне анонімне подання анкети CSRF не потребує і в схемі позначене без security.
"""
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, routing
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .request_security import CSRF_HEADER, WRITE_METHODS, require_preauth_csrf, require_session_csrf
from .routes.v2_auth import require_v2_role

# Swagger UI з офіційного пакета npm swagger-ui-dist (Apache-2.0; LICENSE і NOTICE поруч).
# Версію зафіксовано, файли не змінювались; SHA-256 звіряють тести.
SWAGGER_UI_VERSION = "5.17.14"
ASSETS_DIR = Path(__file__).parent / "static" / "swagger-ui"
ASSETS_URL = "/docs/swagger-ui"
ASSETS = {
    "swagger-ui-bundle.js": "text/javascript; charset=utf-8",
    "swagger-ui.css": "text/css; charset=utf-8",
}
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"}
CSRF_SCHEME = "csrfToken"
# Внутрішні функції require_role(...) і require_v2_role(...): для запитів зміни вони викликають require_session_csrf
ROLE_GUARDS = ("require_role.<locals>.check", "require_v2_role.<locals>.dependency")
CSRF_DESCRIPTION = {
    "session": "Потрібен X-CSRF-Token поточної сесії (GET /v2/auth/csrf після входу).",
    "preauth": "Потрібен X-CSRF-Token з GET /v2/auth/csrf (pre-auth cookie до входу або токен сесії).",
}

admin_only = Depends(require_v2_role("admin"))
router = APIRouter(include_in_schema=False)


def _calls(dependant) -> list[Callable[..., Any]]:
    found = []
    for sub in dependant.dependencies:
        if sub.call is not None:
            found.append(sub.call)
        found.extend(_calls(sub))
    return found


def api_routes(app: FastAPI) -> list[Any]:
    """Усі маршрути застосунку, включно з підключеними через include_router (FastAPI 0.163 підключає їх ліниво)."""
    contexts = routing.iter_route_contexts(app.routes) if hasattr(routing, "iter_route_contexts") else app.routes
    return [route for route in contexts if getattr(route, "dependant", None) is not None and route.methods]


def csrf_requirement(route: Any, method: str) -> str | None:
    """
    Яку CSRF-перевірку backend фактично виконує для цієї операції: "session", "preauth" або None.
    Визначається з дерева залежностей маршруту (ті самі функції, що працюють під час запиту).
    """
    if method.upper() not in WRITE_METHODS:
        return None
    calls = _calls(route.dependant)
    if require_preauth_csrf in calls:
        return "preauth"
    if require_session_csrf in calls:
        return "session"
    if any(getattr(call, "__qualname__", "") in ROLE_GUARDS for call in calls):
        return "session"            # require_role / require_v2_role перевіряють CSRF сесії для запитів зміни
    return None


def build_openapi(app: FastAPI) -> dict[str, Any]:
    """OpenAPI-схема, у якій X-CSRF-Token позначено рівно там, де його перевіряє backend."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    schema.setdefault("components", {}).setdefault("securitySchemes", {})[CSRF_SCHEME] = {
        "type": "apiKey", "in": "header", "name": CSRF_HEADER,
        "description": "Токен з GET /v2/auth/csrf: після входу — токен сесії; до входу — pre-auth токен. "
                       "Потрібен лише операціям, де це вказано.",
    }
    for route in api_routes(app):
        if not route.include_in_schema:
            continue
        operations = schema["paths"].get(route.path_format, {})
        for method in route.methods:
            operation = operations.get(method.lower())
            if operation is None:
                continue
            requirement = csrf_requirement(route, method)
            if requirement is None:
                continue
            operation["security"] = [{CSRF_SCHEME: []}]
            operation["x-csrf"] = requirement
            note = CSRF_DESCRIPTION[requirement]
            operation["description"] = f"{operation['description']}\n\n{note}" if operation.get("description") else note
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
        swagger_js_url=f"{ASSETS_URL}/swagger-ui-bundle.js",
        swagger_css_url=f"{ASSETS_URL}/swagger-ui.css",
        swagger_favicon_url="data:,",
        swagger_ui_parameters={"persistAuthorization": False, "withCredentials": True},
    )
    page.headers.update(NO_STORE_HEADERS)
    return page


@router.get(ASSETS_URL + "/{name}", dependencies=[admin_only])
def swagger_asset(name: str) -> FileResponse:
    # Лише файли з фіксованого переліку: ім'я з запиту не стає шляхом до файлу
    if name not in ASSETS:
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(ASSETS_DIR / name, media_type=ASSETS[name], headers=NO_STORE_HEADERS)
