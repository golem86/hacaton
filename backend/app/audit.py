"""
Журнал дій: запис адміністративних операцій і їх перегляд.

Запис додається в ту саму транзакцію, що й сама дія: якщо дія не збереглася,
не збережеться і запис (і навпаки). Невдалі спроби (403, 409, 422) не журналюються,
бо нічого не змінили.

Що можна передавати в details: ЛИШЕ поля зі списку дозволених (ALLOWED_DETAILS)
і лише значення дозволеного типу (числа). Будь-яке інше поле, рядок, список чи
вкладений об'єкт спричинить помилку. Це allowlist, а не список заборон: так коди
чи відповіді не потраплять у журнал ні під іншою назвою, ні у вкладеному полі.
"""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .database import get_db
from .models import AuditEvent
from .roles import require_role

# Дозволені службові поля details і їхній тип. Нове поле додається сюди свідомо, з рев'ю.
ALLOWED_DETAILS: dict[str, type] = {"count": int}
# Дозволені дії журналу
ALLOWED_ACTIONS = {"tokens.issue", "assessment.close",
                   "auth.login",          # успішний вхід після 2FA: лише роль, без email і пароля
                   "user.create_admin"}   # створення адміністратора CLI-командою
# Роль auditor не вводиться до рішення №5 — журнал бачить лише admin (S12)
AUDIT_ROLES = ("admin",)


def _validate(action: str, details: dict) -> None:
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"Невідома дія журналу: {action}")
    for key, value in details.items():
        expected = ALLOWED_DETAILS.get(key)
        if expected is None:
            raise ValueError(f"Поле '{key}' не дозволене в журналі")
        # bool — підтип int у Python, тому виключаємо його явно
        if type(value) is not expected:
            raise ValueError(f"Поле '{key}' має бути типу {expected.__name__}")


def record(db: Session, actor_role: str, action: str, assessment_id: int | None = None,
           **details) -> None:
    """Додає запис у поточну транзакцію. Зберігається разом із db.commit() самої дії."""
    _validate(action, details)
    db.add(AuditEvent(created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                      actor_role=actor_role, action=action, assessment_id=assessment_id,
                      details=json.dumps(details, ensure_ascii=False)))


router = APIRouter(prefix="/api", tags=["Журнал дій"])


@router.get("/audit-events", dependencies=[Depends(require_role(*AUDIT_ROLES))])
def list_audit_events(assessment_id: int | None = None,
                      limit: int = Query(default=100, ge=1, le=500),
                      db: Session = Depends(get_db)):
    """Останні записи журналу (найновіші першими). Доступ: admin, auditor."""
    query = db.query(AuditEvent)
    if assessment_id is not None:
        query = query.filter(AuditEvent.assessment_id == assessment_id)
    events = query.order_by(AuditEvent.id.desc()).limit(limit).all()
    return [{"id": e.id, "created_at": e.created_at.isoformat() + "Z", "actor_role": e.actor_role,
             "action": e.action, "assessment_id": e.assessment_id,
             "details": json.loads(e.details)} for e in events]
