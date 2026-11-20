"""
Маршрути автентифікації Dashboard V2 (V2 Integration Contract, розділи 2, 3.0, 3.5; docs/V2_HARDENING_CONTRACT.md).

  - CSRF: до входу — підписаний pre-auth токен; із сесією — токен, прив'язаний до сесії (3.0);
  - pending-сесія до 2FA живе 15 хв; після 2FA — новий токен на 12 год, старий недійсний (S7);
  - 2FA verify — одна транзакція: код споживається один раз, не більше 5 перевірок на код,
    сесія ротується лише якщо pending-сесія ще існує;
  - 10 невдалих кодів 2FA за 24 год → 429 на verify, resend і на видачу коду під час входу;
  - ліміти спроб за (email, IP) і за IP; IP лише через довірений reverse proxy (S6);
  - реєстрація і вхід не розкривають існування email ні відповіддю, ні часом (S9, фіктивний scrypt);
  - скидання пароля: ліміти на акаунт, атомарне підтвердження, однакова й однаково швидка відповідь на запит
    (лист — у фоновій черзі);
  - dev-mail реєструється лише в development (S3, див. dev_router);
  - вхід, вихід, скидання пароля і блокування 2FA журналюються лише з роллю та id (S12).
  - V2_AUTH_DB зайнята довше за busy_timeout → 503 (AuthRoute), а не 500.
"""
import logging
import os
import re
from functools import partial
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from .. import audit, v2_mail_queue
from ..database import SessionLocal
from ..request_security import (client_ip, delete_cookie, ensure_preauth, require_preauth_csrf,
                                require_session_csrf, session_csrf_token, set_cookie)
from ..roles import session_user
from ..v2_auth import (ACCOUNT_WINDOW_MINUTES, PENDING_SESSION_TTL_MINUTES, RESET_ISSUE_LIMIT, SESSION_TTL_HOURS,
                       AuthDatabaseBusy, MailDeliveryError, MailNotConfigured, TwoFactorLocked, authenticate,
                       clear_rate_limit, complete_two_factor, consume_rate_limit, create_session, delete_session,
                       find_user_id, is_busy_error, is_rate_limited, issue_challenge, latest_dev_mail, logout_all,
                       register_user, reset_password_with_code, session_cookie_name, two_factor_locked)

log = logging.getLogger("app.v2_mail")

BUSY_DETAIL ="Сервіс тимчасово зайнятий. Спробуйте ще раз"


class AuthRoute(APIRoute):
    """Маршрути над V2_AUTH_DB: SQLite зайнята довше за busy_timeout → 503 з Retry-After, а не 500."""

    def get_route_handler(self) -> Callable:
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            try:
                return await handler(request)
            except Exception as error:
                if isinstance(error, AuthDatabaseBusy) or is_busy_error(error):
                    return JSONResponse({"detail": BUSY_DETAIL}, status_code=503, headers={"Retry-After": "1"})
                raise

        return guarded


router = APIRouter(prefix="/v2/auth", tags=["Dashboard V2 Auth"], route_class=AuthRoute)
dev_router = APIRouter(prefix="/v2/auth", tags=["Dashboard V2 Auth (лише development)"])

SESSION_MAX_AGE = SESSION_TTL_HOURS * 3600
PENDING_MAX_AGE = PENDING_SESSION_TTL_MINUTES * 60
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
TOO_MANY_CODES = "Забагато невдалих кодів підтвердження. Спробуйте пізніше"


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


def record_auth_event(actor_role: str, action: str, actor_user_id: int, **details: int) -> None:
    """Подія основного журналу після коміту дії: лише роль, id і дозволені числові деталі (без email, IP, кодів)."""
    with SessionLocal() as db:
        audit.record(db, actor_role, action, actor_user_id=actor_user_id, **details)
        db.commit()


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


def require_v2_role(*roles: str):
    """Для /v2/*: сесія з 2FA і точна роль із v2_users (user, admin або data_officer); для запитів зміни — CSRF."""
    allowed = frozenset(roles)

    def dependency(request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        if user["role"] not in allowed:
            raise HTTPException(status_code=403, detail="Недостатньо прав")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            require_session_csrf(request)
        return user
    return dependency


def _send_challenge(user_id: int, purpose: str, email: str) -> None:
    try:
        issue_challenge(user_id, purpose, email)
    except TwoFactorLocked as error:
        raise HTTPException(status_code=429, detail=TOO_MANY_CODES) from error
    except (MailNotConfigured, MailDeliveryError) as error:
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
    """S9/A6: однакові відповідь і обсяг роботи (scrypt + запис) для нового й існуючого email. Роль завжди user."""
    if body.password != body.password_confirmation:
        raise HTTPException(status_code=422, detail="Паролі не збігаються")
    email = validate_email(body.email)
    if not consume_rate_limit("register_ip", client_ip(request), limit=10, window_minutes=15):
        raise HTTPException(status_code=429, detail="Забагато спроб. Спробуйте пізніше")
    register_user(body.name, email, body.password)
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
    user = authenticate(email, body.password)        # A6: фіктивний scrypt для невідомого email
    if user is None:
        consume_rate_limit("login_ip", ip, limit=30, window_minutes=15)
        consume_rate_limit("login", subject, limit=5, window_minutes=15)
        raise HTTPException(status_code=401, detail="Неправильний email або пароль")
    clear_rate_limit("login", subject)
    if two_factor_locked(user["id"]):                # A5: блокування 2FA перевіряється після пароля
        raise HTTPException(status_code=429, detail=TOO_MANY_CODES)
    if not consume_rate_limit("2fa_issue", str(user["id"]), limit=3, window_minutes=10):
        raise HTTPException(status_code=429, detail="Забагато кодів підтвердження. Спробуйте пізніше")
    _send_challenge(user["id"], "login_2fa", user["email"])
    token, _ = create_session(user["id"])            # pending-сесія: 15 хвилин
    set_cookie(response, session_cookie_name(), token, max_age=PENDING_MAX_AGE)
    return {"requires_2fa": True, "csrf_token": session_csrf_token(token),
            "user": {"name": user["name"], "role": user["role"]}}


@router.post("/2fa/verify", dependencies=[Depends(require_session_csrf)])
def verify_2fa(body: CodeBody, request: Request, response: Response) -> dict[str, Any]:
    pending_or_current_user(request)
    result = complete_two_factor(_session_token(request), body.code)    # A1/A2: одна транзакція
    if result.locked_now:
        record_auth_event(result.user["role"], "auth.2fa_lockout", result.user["id"])
    if result.status == "locked":
        raise HTTPException(status_code=429, detail=TOO_MANY_CODES)
    if result.status != "ok":
        raise HTTPException(status_code=401, detail="Неправильний або прострочений код підтвердження")
    set_cookie(response, session_cookie_name(), result.token, max_age=SESSION_MAX_AGE)   # S7
    record_auth_event(result.user["role"], "auth.login", result.user["id"])
    return {**result.user, "two_factor_verified": True, "csrf_token": session_csrf_token(result.token)}


@router.post("/2fa/resend", dependencies=[Depends(require_session_csrf)])
def resend_2fa(request: Request) -> dict[str, str]:
    user = pending_or_current_user(request)
    if two_factor_locked(user["id"]):
        raise HTTPException(status_code=429, detail=TOO_MANY_CODES)
    if not consume_rate_limit("2fa_issue", str(user["id"]), limit=3, window_minutes=10):
        raise HTTPException(status_code=429, detail="Забагато кодів підтвердження. Спробуйте пізніше")
    _send_challenge(user["id"], "login_2fa", user["email"])
    return {"status": "sent"}


@router.post("/password-reset/request", dependencies=[Depends(require_preauth_csrf)])
def request_password_reset(body: ResetRequestBody, request: Request) -> dict[str, str]:
    """
    Не розкриває існування акаунта ні відповіддю, ні часом: запит лише ставить завдання у фонову чергу листів
    (app/v2_mail_queue.py) і одразу відповідає однаково для будь-якого email. Пошук акаунта, ліміти й видача
    коду виконуються у воркері. Переповнена черга відкидає завдання без зміни відповіді.
    """
    email = validate_email(body.email)
    v2_mail_queue.mail_queue.submit(partial(_issue_reset_code, email, client_ip(request)))
    return {"status": "sent_if_account_exists"}


def _issue_reset_code(email: str, ip: str) -> None:
    """
    Фонове завдання. Код видається, лише якщо акаунт існує й пройдено обидва ліміти: 3 за 15 хв на (email, IP)
    і RESET_ISSUE_LIMIT за 24 год на акаунт (незалежно від кількості IP). Код зберігається лише після листа.
    Помилки пошти лише логуються (без email і подробиць SMTP).
    """
    user_id = find_user_id(email)
    if user_id is not None \
            and consume_rate_limit("password_reset", f"{email}|{ip}", limit=3, window_minutes=15) \
            and consume_rate_limit("password_reset_account", str(user_id), limit=RESET_ISSUE_LIMIT,
                                   window_minutes=ACCOUNT_WINDOW_MINUTES):
        try:
            issue_challenge(user_id, "password_reset", email)
        except (MailNotConfigured, MailDeliveryError) as error:
            log.error("Лист скидання пароля не надіслано: %s", type(error).__name__)


@router.post("/password-reset/confirm", dependencies=[Depends(require_preauth_csrf)])
def confirm_password_reset(body: ResetConfirmBody) -> dict[str, str]:
    """A4: код, новий пароль, видалення всіх сесій і гасіння інших кодів — одна транзакція."""
    if body.password != body.password_confirmation:
        raise HTTPException(status_code=422, detail="Паролі не збігаються")
    email = validate_email(body.email)
    result = reset_password_with_code(email, body.code, body.password)
    if result.status == "locked":
        raise HTTPException(status_code=429, detail="Забагато невдалих спроб. Спробуйте пізніше")
    if result.status != "ok":
        raise HTTPException(status_code=401, detail="Неправильний або прострочений код скидання")
    record_auth_event(result.role, "auth.password_reset", result.user_id)
    return {"status": "password_updated"}


@router.post("/logout", dependencies=[Depends(require_session_csrf)])
def logout(request: Request, response: Response) -> dict[str, str]:
    deleted = delete_session(_session_token(request))
    delete_cookie(response, session_cookie_name())
    if deleted and deleted["two_factor_verified"]:
        record_auth_event(deleted["role"], "auth.logout", deleted["id"])
    return {"status": "logged_out"}


@router.post("/logout-all", dependencies=[Depends(require_session_csrf)])
def logout_everywhere(request: Request, response: Response,
                      _: dict[str, Any] = Depends(current_user)) -> dict[str, str]:
    """A14: усі сесії поточного користувача (включно з цією і pending) — одна транзакція."""
    result = logout_all(_session_token(request))
    if result is None:
        raise HTTPException(status_code=401, detail="Потрібен вхід до системи")
    delete_cookie(response, session_cookie_name())
    record_auth_event(result["role"], "auth.logout_all", result["id"], count=result["revoked"])
    return {"status": "logged_out_all"}


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
