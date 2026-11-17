import os
import secrets
import sqlite3
from typing import Any

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
import re

from pydantic import BaseModel, Field

from ..v2_auth import (
    CSRF_COOKIE,
    AUTH_DB_PATH,
    SESSION_COOKIE,
    authenticate,
    clear_rate_limit,
    consume_rate_limit,
    create_session,
    create_user,
    delete_session,
    issue_challenge,
    init_auth_db,
    latest_dev_mail,
    SECURE_COOKIE,
    update_password,
    user_for_session,
    verify_challenge,
    verify_session_2fa,
)

router = APIRouter(prefix="/v2/auth", tags=["Dashboard V2 Auth"])
init_auth_db()


class RegisterBody(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=10, max_length=200)
    password_confirmation: str = Field(min_length=10, max_length=200)


class LoginBody(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class CodeBody(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class ResetRequestBody(BaseModel):
    email: str = Field(min_length=5, max_length=320)


class ResetConfirmBody(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    code: str = Field(min_length=6, max_length=6)
    password: str = Field(min_length=10, max_length=200)
    password_confirmation: str = Field(min_length=10, max_length=200)


def require_csrf(request: Request, x_csrf_token: str | None = Header(default=None)) -> None:
    cookie = request.cookies.get(CSRF_COOKIE)
    if not cookie or not x_csrf_token or not secrets.compare_digest(cookie, x_csrf_token):
        raise HTTPException(status_code=403, detail="Некоректний CSRF-токен")


def validate_email(email: str) -> str:
    normalized = email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
        raise HTTPException(status_code=422, detail="Вкажіть коректний email")
    return normalized


def current_user(v2_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    user = user_for_session(v2_session)
    if user is None:
        raise HTTPException(status_code=401, detail="Потрібен вхід до системи")
    if not user.get("two_factor_verified"):
        raise HTTPException(status_code=401, detail="Потрібне підтвердження двофакторного входу")
    return user


def pending_or_current_user(v2_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    user = user_for_session(v2_session)
    if user is None:
        raise HTTPException(status_code=401, detail="Потрібен вхід до системи")
    return user


def require_role(role: str):
    def dependency(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        if user["role"] != role:
            raise HTTPException(status_code=403, detail="Недостатньо прав")
        return user
    return dependency


@router.get("/csrf")
def csrf(response: Response) -> dict[str, str]:
    token = secrets.token_urlsafe(32)
    response.set_cookie(CSRF_COOKIE, token, httponly=False, secure=SECURE_COOKIE, samesite="lax", max_age=7200)
    return {"csrf_token": token}


@router.post("/register", status_code=201)
def register(body: RegisterBody, response: Response, _: None = Depends(require_csrf)) -> dict[str, Any]:
    if body.password != body.password_confirmation:
        raise HTTPException(status_code=422, detail="Паролі не збігаються")
    try:
        return create_user(body.name, validate_email(body.email), body.password, role="user")
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/login")
def login(body: LoginBody, response: Response, _: None = Depends(require_csrf)) -> dict[str, Any]:
    email = validate_email(body.email)
    if not consume_rate_limit("login", email, limit=5, window_minutes=15):
        raise HTTPException(status_code=429, detail="Забагато невдалих спроб. Спробуйте пізніше")
    user = authenticate(email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Неправильний email або пароль")
    clear_rate_limit("login", email)
    token, expires = create_session(user["id"])
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=SECURE_COOKIE, samesite="lax", expires=expires, max_age=12 * 3600)
    if not consume_rate_limit("2fa_issue", str(user["id"]), limit=3, window_minutes=10):
        delete_session(token)
        response.delete_cookie(SESSION_COOKIE, secure=SECURE_COOKIE, samesite="lax")
        raise HTTPException(status_code=429, detail="Забагато кодів підтвердження. Спробуйте пізніше")
    issue_challenge(user["id"], "login_2fa", user["email"])
    return {"requires_2fa": True, "user": user}


@router.post("/2fa/verify")
def verify_2fa(body: CodeBody, v2_session: str | None = Cookie(default=None), _: None = Depends(require_csrf)) -> dict[str, Any]:
    user = pending_or_current_user(v2_session)
    if not verify_challenge(user["id"], "login_2fa", body.code):
        raise HTTPException(status_code=401, detail="Неправильний або прострочений код підтвердження")
    verify_session_2fa(v2_session)
    clear_rate_limit("2fa_issue", str(user["id"]))
    user["two_factor_verified"] = True
    return user


@router.post("/2fa/resend")
def resend_2fa(v2_session: str | None = Cookie(default=None), _: None = Depends(require_csrf)) -> dict[str, str]:
    user = pending_or_current_user(v2_session)
    if not consume_rate_limit("2fa_issue", str(user["id"]), limit=3, window_minutes=10):
        raise HTTPException(status_code=429, detail="Забагато кодів підтвердження. Спробуйте пізніше")
    issue_challenge(user["id"], "login_2fa", user["email"])
    return {"status": "sent"}


@router.post("/password-reset/request")
def request_password_reset(body: ResetRequestBody, _: None = Depends(require_csrf)) -> dict[str, str]:
    email = validate_email(body.email)
    # Do not reveal whether the address exists. Look up only through the local auth store.
    with sqlite3.connect(AUTH_DB_PATH) as db:
        row = db.execute("SELECT id, email FROM v2_users WHERE email = ?", (email,)).fetchone()
    if row and consume_rate_limit("password_reset", email, limit=3, window_minutes=15):
        issue_challenge(int(row[0]), "password_reset", row[1])
    return {"status": "sent_if_account_exists"}


@router.post("/password-reset/confirm")
def confirm_password_reset(body: ResetConfirmBody, _: None = Depends(require_csrf)) -> dict[str, str]:
    if body.password != body.password_confirmation:
        raise HTTPException(status_code=422, detail="Паролі не збігаються")
    email = validate_email(body.email)
    with sqlite3.connect(AUTH_DB_PATH) as db:
        row = db.execute("SELECT id FROM v2_users WHERE email = ?", (email,)).fetchone()
    if not row or not verify_challenge(int(row[0]), "password_reset", body.code):
        raise HTTPException(status_code=401, detail="Неправильний або прострочений код скидання")
    update_password(int(row[0]), body.password)
    clear_rate_limit("password_reset", email)
    return {"status": "password_updated"}


@router.get("/dev-mail/latest")
def dev_mail_latest() -> dict[str, Any]:
    if os.environ.get("V2_AUTH_DEV_MAIL", "0") != "1":
        raise HTTPException(status_code=404, detail="Not found")
    mail = latest_dev_mail()
    return mail or {"status": "empty"}


@router.post("/logout")
def logout(response: Response, v2_session: str | None = Cookie(default=None), _: None = Depends(require_csrf)) -> dict[str, str]:
    delete_session(v2_session)
    response.delete_cookie(SESSION_COOKIE, secure=SECURE_COOKIE, samesite="lax")
    return {"status": "logged_out"}


@router.get("/me")
def me(user: dict[str, Any] = Depends(pending_or_current_user)) -> dict[str, Any]:
    if not user.get("two_factor_verified"):
        return {"requires_2fa": True, "user": {key: value for key, value in user.items() if key != "two_factor_verified"}}
    return {"requires_2fa": False, "user": user}
