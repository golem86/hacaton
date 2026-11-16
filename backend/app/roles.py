"""
Рольова модель доступу.

Хто що може робити, перевіряє СЕРВЕР, а не лише інтерфейс: навіть якщо хтось
надішле запит напряму, без потрібної ролі він отримає відмову (403).

ДЕМО-РЕЖИМ: роль передається в заголовку запиту `X-Role`, напр. `X-Role: manager`.
Паролів і облікових записів у прототипі немає навмисно — у реальному розгортанні
роль надходить із відомчої системи автентифікації (єдиний вхід), а цей файл
лише замінить спосіб, у який роль визначається. Правила доступу лишаються ті самі.
"""
from fastapi import Header, HTTPException

# Ролі з брифу продукту
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
# Хто бачить агреговані результати й статистику участі
ANALYTICS_ROLES = ("admin", "manager", "anticorruption", "auditor")


def require_role(*allowed: str):
    """
    Створює перевірку для адреси API. Використання:
        @router.get(..., dependencies=[Depends(require_role("admin", "manager"))])
    """
    def check(x_role: str | None = Header(default=None, description="Роль користувача (демо)")) -> str:
        if x_role is None:
            raise HTTPException(status_code=401, detail="Не вказано роль (заголовок X-Role)")
        if x_role not in ROLES:
            raise HTTPException(status_code=401, detail=f"Невідома роль: {x_role}")
        if x_role not in allowed:
            raise HTTPException(status_code=403, detail="Недостатньо прав для цієї дії")
        return x_role

    return check
