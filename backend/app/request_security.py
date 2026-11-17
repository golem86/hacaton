"""
Захист запитів: CSRF (V2 Integration Contract, розділ 3.0) і IP клієнта для rate limiting (S6).

CSRF:
  - для автентифікованих операцій токен ПРИВ'ЯЗАНИЙ ДО СЕСІЇ: HMAC(секрет, хеш токена сесії).
    Токен іншої чи старої сесії не підходить; після ротації сесії (вхід, 2FA, вихід) він інший;
  - до входу (реєстрація, вхід, скидання пароля) — ПІДПИСАНИЙ токен, прив'язаний до pre-auth cookie;
  - для кожного запиту зміни стану перевіряється походження (Origin, а без нього — Referer)
    за allowlist frontend-доменів; у release запит без обох заголовків відхиляється;
  - SameSite=Lax лишається, але не вважається самостійним захистом.

IP клієнта:
  - X-Forwarded-For враховується ЛИШЕ якщо з'єднання прийшло від довіреного reverse proxy
    (TRUSTED_PROXIES); інакше береться адреса з'єднання, тож підробка заголовка не обходить ліміт.
"""
import hashlib
import hmac
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response

from . import settings
from .v2_auth import preauth_cookie_name, session_cookie_name, token_hash

CSRF_HEADER = "X-CSRF-Token"
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _sign(message: str) -> str:
    return hmac.new(settings.secret_key().encode(), message.encode(), hashlib.sha256).hexdigest()


def session_csrf_token(session_token: str) -> str:
    return _sign("session:" + token_hash(session_token))


def preauth_csrf_token(preauth_id: str) -> str:
    return _sign("preauth:" + preauth_id)


def set_cookie(response: Response, name: str, value: str, max_age: int, httponly: bool = True) -> None:
    """Усі cookie V2: Path=/, без Domain, SameSite=Lax; у Secure-режимі — Secure і префікс __Host-."""
    response.set_cookie(name, value, max_age=max_age, path="/", httponly=httponly,
                        secure=settings.secure_cookies(), samesite="lax")


def delete_cookie(response: Response, name: str) -> None:
    response.delete_cookie(name, path="/", secure=settings.secure_cookies(), samesite="lax")


def ensure_preauth(request: Request, response: Response) -> str:
    """Повертає pre-auth токен; за потреби встановлює нову pre-auth cookie."""
    preauth_id = request.cookies.get(preauth_cookie_name())
    if not preauth_id:
        preauth_id = secrets.token_urlsafe(24)
        set_cookie(response, preauth_cookie_name(), preauth_id, max_age=7200)
    return preauth_csrf_token(preauth_id)


def _origin_of(request: Request) -> str | None:
    origin = request.headers.get("origin")
    if origin:
        return origin.rstrip("/")
    referer = request.headers.get("referer")
    if referer:
        parts = urlsplit(referer)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
    return None


def check_origin(request: Request) -> None:
    if request.method not in WRITE_METHODS:
        return
    origin = _origin_of(request)
    if origin is None:
        if settings.is_release():
            raise HTTPException(status_code=403, detail="Запит без Origin/Referer відхилено")
        return
    allowed = settings.frontend_origins() | {f"{request.url.scheme}://{request.headers.get('host', '')}"}
    if origin not in allowed:
        raise HTTPException(status_code=403, detail="Недозволене походження запиту")


def _header_matches(request: Request, expected: str) -> bool:
    supplied = request.headers.get(CSRF_HEADER, "")
    return bool(supplied) and hmac.compare_digest(supplied, expected)


def require_session_csrf(request: Request) -> None:
    """Для операцій з cookie сесії (у т.ч. pending до 2FA): токен прив'язаний до цієї сесії."""
    check_origin(request)
    session_token = request.cookies.get(session_cookie_name())
    if not session_token or not _header_matches(request, session_csrf_token(session_token)):
        raise HTTPException(status_code=403, detail="Некоректний CSRF-токен")


def require_preauth_csrf(request: Request) -> None:
    """Для дій до входу: підписаний токен pre-auth cookie або токен поточної сесії."""
    check_origin(request)
    preauth_id = request.cookies.get(preauth_cookie_name())
    if preauth_id and _header_matches(request, preauth_csrf_token(preauth_id)):
        return
    session_token = request.cookies.get(session_cookie_name())
    if session_token and _header_matches(request, session_csrf_token(session_token)):
        return
    raise HTTPException(status_code=403, detail="Некоректний CSRF-токен")


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    trusted = settings.trusted_proxies()
    if peer not in trusted:
        return peer
    forwarded = [item.strip() for item in request.headers.get("x-forwarded-for", "").split(",") if item.strip()]
    for address in reversed(forwarded):        # справа наліво: перша недовірена адреса — клієнт
        if address not in trusted:
            return address
    return peer
