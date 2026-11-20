"""
Рольова модель доступу (V2 Integration Contract, розділ 2; docs/V2_HARDENING_CONTRACT.md, розділ 1).

Роль визначає ЛИШЕ перевірена серверна сесія (verified principal): cookie сесії V2 після 2FA.
Ролі сесії V2 (v2_users.role, читається на кожен запит):
  - user — самореєстрація, лише власний кабінет /v2/user/*;
  - admin — цикли, результати, аналітика, журнал, звіти, /docs, керування ролями й сесіями;
  - data_officer — лише призначення admin: видача кодів доступу і перегляд участі.
Маршрут сам перелічує дозволені ролі: require_role("data_officer"), require_role("admin", "data_officer").
Анонімний респондент акаунта не має — його маршрут доступний за одноразовим кодом.

Заголовок X-Role НЕ є автентифікацією. Він обробляється лише в режимі development з явним
прапорцем INTEGRITY_DEMO_XROLE=1 (для регресійних тестів V1); у release сервер з цим прапорцем
не стартує (settings.validate_release_config). Якщо є сесія, X-Role ігнорується повністю.

Для запитів зміни стану з cookie-сесією тут же перевіряється CSRF (розділ 3.0).
"""
from typing import Any

from fastapi import HTTPException, Request

from . import settings
from .request_security import WRITE_METHODS, require_session_csrf
from .v2_auth import AuthDatabaseBusy, session_cookie_name, user_for_session

# Ролі V1 — лише для демо-режиму X-Role (development + INTEGRITY_DEMO_XROLE=1)
ROLES = {
    "admin": "Адміністратор оцінювання",
    "respondent": "Респондент",
    "expert": "Експерт",
    "data_officer": "Відповідальний за дані",
    "manager": "Керівник",
    "anticorruption": "Уповноважений з антикорупції",
    "auditor": "Аудитор / внутрішній контроль",
}
ALL_ROLES = tuple(ROLES)
# Ролі сесії V2 (v2_users.role)
SESSION_ROLES = ("user", "admin", "data_officer")
# Сесійна роль admin входить у кожен набір аналітики; ролі V1 діють лише в демо-режимі.
# data_officer сюди НЕ входить: той, хто видає коди, не бачить результатів (атака n−1).
ANALYTICS_ROLES = ("admin", "manager", "anticorruption", "auditor")


def session_user(request: Request) -> dict[str, Any] | None:
    """Користувач з cookie сесії (у т.ч. pending до 2FA) або None. Зайнята V2_AUTH_DB → 503."""
    try:
        return user_for_session(request.cookies.get(session_cookie_name()))
    except AuthDatabaseBusy as error:
        raise HTTPException(status_code=503, detail="Сервіс тимчасово зайнятий. Спробуйте ще раз",
                            headers={"Retry-After": "1"}) from error


def resolve_principal(request: Request) -> dict[str, Any] | None:
    user = session_user(request)
    if user is not None:
        # Є сесія → лише вона визначає роль; X-Role ігнорується
        if not user["two_factor_verified"]:
            return None
        return {"role": user["role"], "source": "session", "user": user}
    if settings.demo_xrole_enabled():
        role = request.headers.get("x-role")
        if role in ROLES:
            return {"role": role, "source": "demo-x-role", "user": None}
    return None


def require_role(*allowed: str):
    """
    Перевірка доступу для захищених маршрутів:
        @router.get(..., dependencies=[Depends(require_role("admin"))])
        @router.post(..., dependencies=[Depends(require_role("data_officer"))])
    401 — немає перевіреної сесії; 403 — немає прав або CSRF не пройдено.
    """
    def check(request: Request) -> str:
        principal = resolve_principal(request)
        if principal is None:
            raise HTTPException(status_code=401, detail="Потрібен вхід до системи")
        if principal["role"] not in allowed:
            raise HTTPException(status_code=403, detail="Недостатньо прав для цієї дії")
        if principal["source"] == "session" and request.method in WRITE_METHODS:
            require_session_csrf(request)
        request.state.principal = principal
        return principal["role"]

    return check
