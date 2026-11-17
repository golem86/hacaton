"""
Маршрути автентифікації Dashboard V2 (V2 Integration Contract, розділи 2, 3.0, 3.5).

  - CSRF: до входу — підписаний pre-auth токен; із сесією — токен, прив'язаний до сесії (3.0);
  - сесія ротується після 2FA, старий токен недійсний (S7);
  - ліміти спроб за (email, IP) і за IP; IP лише через довірений reverse proxy (S6);
  - реєстрація не розкриває існування email (S9);
  - dev-mail реєструється лише в development (S3, див. dev_router);
  - успішний вхід записується в Audit Trail без email і паролів (S12).
"""
import os
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import audit
from ..database import SessionLocal
from ..request_security import (client_ip, delete_cookie, ensure_preauth, require_preauth_csrf,
                                require_session_csrf, session_csrf_token, set_cookie)
from ..roles import session_user
from ..v2_auth import (SESSION_TTL_HOURS, MailNotConfigured, authenticate, clear_rate_limit,
                       consume_rate_limit, create_session, create_user, delete_session, find_user_id,
                       is_rate_limited,
                       issue_challenge, latest_dev_mail, rotate_session_after_2fa, session_cookie_name,
                       update_password, user_exists, verify_challenge)

router = APIRouter(prefix="/v2/auth", tags=["Dashboard V2 Auth"])
dev_router = APIRouter(prefix="/v2/auth", tags=["Dashboard V2 Auth (лише development)"])

SESSION_MAX_AGE = SESSION_TTL_HOURS * 3600
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


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


def validate_email(email: str) -> str:
    normalized = email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
        raise HTTPException(status_code=422, detail="Вкажіть коректний email")
    return normalized


def _session_token(request: Request) -> str | None:
    return request.cookies.get(session_cookie_name())


def pending_or_current_user(request: Request) -> dict[str, Any]:
    user = session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Потрібен вхід до системи")
    return user


def current_user(request: Request) -> dict[str, Any]:
    user = pending_or_current_user(request)
    if not user.get("two_factor_verified"):
        raise HTTPException(status_code=401, detail="Потрібне підтвердження двофакторного входу")
    return user


def require_v2_role(role: str):
    """Для /v2/*: сесія з 2FA і точна роль; для запитів зміни стану — CSRF сесії."""
    def dependency(request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        if user["role"] != role:
            raise HTTPException(status_code=403, detail="Недостатньо прав")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            require_session_csrf(request)
        return user
    return dependency


def _send_challenge(user_id: int, purpose: str, email: str) -> None:
    try:
        issue_challenge(user_id, purpose, email)
    except MailNotConfigured as error:
        raise HTTPException(status_code=503, detail="Надсилання кодів тимчасово недоступне") from error


@router.get("/csrf")
def csrf(request: Request, response: Response) -> dict[str, str]:
    """Із сесією — токен, прив'язаний до сесії; без неї — підписаний pre-auth токен."""
    session_token = _session_token(request)
    if session_token and session_user(request) is not None:
        return {"csrf_token": session_csrf_token(session_token)}
    return {"csrf_token": ensure_preauth(request, response)}


@router.post("/register", status_code=202, dependencies=[Depends(require_preauth_csrf)])
def register(body: RegisterBody, request: Request) -> dict[str, str]:
    """S9: однакова відповідь для нового й існуючого email. Роль завжди user."""
    if body.password != body.password_confirmation:
        raise HTTPException(status_code=422, detail="Паролі не збігаються")
    email = validate_email(body.email)
    if not consume_rate_limit("register_ip", client_ip(request), limit=10, window_minutes=15):
        raise HTTPException(status_code=429, detail="Забагато спроб. Спробуйте пізніше")
    if not user_exists(email):
        try:
            create_user(body.name, email, body.password, role="user")
        except ValueError:
            pass   # одночасна реєстрація того самого email — відповідь та сама
    return {"status": "accepted"}


@router.post("/login", dependencies=[Depends(require_preauth_csrf)])
def login(body: LoginBody, request: Request, response: Response) -> dict[str, Any]:
    email = validate_email(body.email)
    ip = client_ip(request)
    subject = f"{email}|{ip}"
    # S6: рахуються лише НЕВДАЛІ спроби — за (email, IP) і за IP. Чужі спроби з іншого IP не блокують
    # власника, а успішні входи працівників за спільною адресою закладу не вичерпують ліміт.
    if is_rate_limited("login_ip", ip, limit=30, window_minutes=15) or \
            is_rate_limited("login", subject, limit=5, window_minutes=15):
        raise HTTPException(status_code=429, detail="Забагато невдалих спроб. Спробуйте пізніше")
    user = authenticate(email, body.password)
    if user is None:
        consume_rate_limit("login_ip", ip, limit=30, window_minutes=15)
        consume_rate_limit("login", subject, limit=5, window_minutes=15)
        raise HTTPException(status_code=401, detail="Неправильний email або пароль")
    clear_rate_limit("login", subject)
    if not consume_rate_limit("2fa_issue", str(user["id"]), limit=3, window_minutes=10):
        raise HTTPException(status_code=429, detail="Забагато кодів підтвердження. Спробуйте пізніше")
    _send_challenge(user["id"], "login_2fa", user["email"])
    token, _ = create_session(user["id"])
    set_cookie(response, session_cookie_name(), token, max_age=SESSION_MAX_AGE)
    return {"requires_2fa": True, "csrf_token": session_csrf_token(token),
            "user": {"name": user["name"], "role": user["role"]}}


@router.post("/2fa/verify", dependencies=[Depends(require_session_csrf)])
def verify_2fa(body: CodeBody, request: Request, response: Response) -> dict[str, Any]:
    user = pending_or_current_user(request)
    if not verify_challenge(user["id"], "login_2fa", body.code):
        raise HTTPException(status_code=401, detail="Неправильний або прострочений код підтвердження")
    new_token, _ = rotate_session_after_2fa(_session_token(request), user["id"])   # S7
    set_cookie(response, session_cookie_name(), new_token, max_age=SESSION_MAX_AGE)
    clear_rate_limit("2fa_issue", str(user["id"]))
    with SessionLocal() as db:
        audit.record(db, user["role"], "auth.login")
        db.commit()
    user["two_factor_verified"] = True
    return {**user, "csrf_token": session_csrf_token(new_token)}


@router.post("/2fa/resend", dependencies=[Depends(require_session_csrf)])
def resend_2fa(request: Request) -> dict[str, str]:
    user = pending_or_current_user(request)
    if not consume_rate_limit("2fa_issue", str(user["id"]), limit=3, window_minutes=10):
        raise HTTPException(status_code=429, detail="Забагато кодів підтвердження. Спробуйте пізніше")
    _send_challenge(user["id"], "login_2fa", user["email"])
    return {"status": "sent"}


@router.post("/password-reset/request", dependencies=[Depends(require_preauth_csrf)])
def request_password_reset(body: ResetRequestBody, request: Request) -> dict[str, str]:
    """Не розкриває існування акаунта: відповідь однакова."""
    email = validate_email(body.email)
    user_id = find_user_id(email)
    if user_id is not None and consume_rate_limit("password_reset", f"{email}|{client_ip(request)}",
                                                  limit=3, window_minutes=15):
        try:
            issue_challenge(user_id, "password_reset", email)
        except MailNotConfigured:
            pass   # відповідь та сама — не розкриваємо стан пошти й акаунта
    return {"status": "sent_if_account_exists"}


@router.post("/password-reset/confirm", dependencies=[Depends(require_preauth_csrf)])
def confirm_password_reset(body: ResetConfirmBody) -> dict[str, str]:
    if body.password != body.password_confirmation:
        raise HTTPException(status_code=422, detail="Паролі не збігаються")
    email = validate_email(body.email)
    user_id = find_user_id(email)
    if user_id is None or not verify_challenge(user_id, "password_reset", body.code):
        raise HTTPException(status_code=401, detail="Неправильний або прострочений код скидання")
    update_password(user_id, body.password)
    return {"status": "password_updated"}


@router.post("/logout", dependencies=[Depends(require_session_csrf)])
def logout(request: Request, response: Response) -> dict[str, str]:
    delete_session(_session_token(request))
    delete_cookie(response, session_cookie_name())
    return {"status": "logged_out"}


@router.get("/me")
def me(user: dict[str, Any] = Depends(pending_or_current_user)) -> dict[str, Any]:
    if not user.get("two_factor_verified"):
        return {"requires_2fa": True, "user": {k: v for k, v in user.items() if k != "two_factor_verified"}}
    return {"requires_2fa": False, "user": user}


@dev_router.get("/dev-mail/latest")
def dev_mail_latest(request: Request) -> dict[str, Any]:
    """S3: існує лише в development з V2_AUTH_DEV_MAIL=1 і відповідає лише локальним запитам."""
    if request.client is None or request.client.host not in LOCAL_HOSTS:
        raise HTTPException(status_code=404, detail="Not found")
    mail = latest_dev_mail(os.environ.get("V2_DEV_MAIL_RECIPIENT") or None)
    return mail or {"status": "empty"}
