"""
Керування користувачами, ролями й сесіями V2 (docs/V2_HARDENING_CONTRACT.md, розділ 3).

Підключається до роутера /v2/admin у routes/v2_admin.py (той самий префікс), тому окремого
include_router у main.py не потрібно. Усі маршрути — require_v2_role("admin"): сесія з 2FA,
точна роль із v2_users, для запитів зміни — CSRF сесії й перевірка Origin.

  GET  /v2/admin/users                         — до 500 записів: id, name, role, email_masked, created_at
  POST /v2/admin/users/lookup                  — {"email"} → один запис із повним email або 404
                                                 (email у тілі, а не в URL: query потрапляє в журнали й історію)
  POST /v2/admin/users/{user_id}/role          — {"expected_role", "new_role"}; 403 self_change, 404, 409;
                                                 лише user ↔ data_officer: роль admin (призначення чи зняття)
                                                 → 403 admin_role_server_only без жодних змін
  POST /v2/admin/users/{user_id}/revoke-sessions → {"revoked": n}; для іншого admin → 403 admin_role_server_only
  GET  /v2/admin/role-changes                  — до 500 останніх записів append-only журналу v2_role_changes

Зміни ролі й відкликання сесій виконуються однією транзакцією BEGIN IMMEDIATE у V2_AUTH_DB з повторною
перевіркою актора; подія основного журналу (user.role_change, user.sessions_revoke) пишеться після коміту
лише з роллю й id актора. Зайнята БД → 503 (AuthRoute); id поза 1..2^63-1 → 422.

Роль адміністратора призначає й знімає лише власник сервера командою на сервері
(python -m app.v2_role_cli set-role …; installer/windows-v2/ops/Set-V2UserRole.ps1).
"""
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ..request_limits import BoundedId
from ..request_security import delete_cookie
from ..v2_auth import (RoleChangeError, change_user_role, find_user_by_email, list_role_changes, list_users,
                       revoke_user_sessions, session_cookie_name)
from .v2_auth import AuthRoute, record_auth_event, require_v2_role

LIST_LIMIT = 500
RoleName = Literal["user", "admin", "data_officer"]

# Без власного префікса: маршрути отримують /v2/admin від роутера v2_admin, до якого підключаються.
router = APIRouter(tags=["Dashboard V2 Admin — Users"], route_class=AuthRoute)
admin = require_v2_role("admin")

_ERRORS = {
    "self_change": (403, "self_change"),
    "actor_unauthorized": (403, "Недостатньо прав"),
    "not_found": (404, "user_not_found"),
    "conflict": (409, "role_conflict"),
    "invalid_role": (422, "invalid_role"),
    "admin_role_server_only": (403, "admin_role_server_only"),
}


class RoleChangeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_role: RoleName
    new_role: RoleName


class LookupBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)


def _http_error(error: RoleChangeError) -> HTTPException:
    status, detail = _ERRORS.get(error.code, (409, error.code))
    return HTTPException(status_code=status, detail=detail)


@router.get("/users")
def users(response: Response, _: dict[str, Any] = Depends(admin)) -> list[dict[str, Any]]:
    """Без повних email; будь-які параметри запиту (зокрема email) ігноруються."""
    response.headers["Cache-Control"] = "no-store"
    return list_users(LIST_LIMIT)


@router.post("/users/lookup")
def lookup_user(body: LookupBody, response: Response, _: dict[str, Any] = Depends(admin)) -> dict[str, Any]:
    """Точний (без урахування регістру) email → повний запис; часткових збігів і пошуку немає."""
    response.headers["Cache-Control"] = "no-store"
    user = find_user_by_email(body.email)
    if user is None:
        raise HTTPException(status_code=404, detail="user_not_found")
    return user


@router.post("/users/{user_id}/role")
def change_role(user_id: BoundedId, body: RoleChangeBody, request: Request,
                actor: dict[str, Any] = Depends(admin)) -> dict[str, Any]:
    if user_id == actor["id"]:
        raise HTTPException(status_code=403, detail="self_change")
    if "admin" in (body.expected_role, body.new_role):       # роль цілі admin — ще й у транзакції change_user_role
        raise HTTPException(status_code=403, detail="admin_role_server_only")
    try:
        result = change_user_role(actor["id"], request.cookies.get(session_cookie_name()), user_id,
                                  body.expected_role, body.new_role)
    except RoleChangeError as error:
        raise _http_error(error) from error
    record_auth_event("admin", "user.role_change", actor["id"])
    return result


@router.post("/users/{user_id}/revoke-sessions")
def revoke_sessions(user_id: BoundedId, request: Request, response: Response,
                    actor: dict[str, Any] = Depends(admin)) -> dict[str, int]:
    try:
        revoked = revoke_user_sessions(actor["id"], request.cookies.get(session_cookie_name()), user_id)
    except RoleChangeError as error:
        raise _http_error(error) from error
    if user_id == actor["id"]:
        delete_cookie(response, session_cookie_name())
    record_auth_event("admin", "user.sessions_revoke", actor["id"], count=revoked)
    return {"revoked": revoked}


@router.get("/role-changes")
def role_changes(response: Response, limit: int = Query(default=LIST_LIMIT, ge=1, le=LIST_LIMIT),
                 _: dict[str, Any] = Depends(admin)) -> list[dict[str, Any]]:
    response.headers["Cache-Control"] = "no-store"
    return list_role_changes(limit)
