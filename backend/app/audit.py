"""
Журнал дій: запис адміністративних операцій і їх перегляд.

Запис додається в ту саму транзакцію, що й сама дія: якщо дія не збереглася,
не збережеться і запис (і навпаки). Невдалі спроби (403, 409, 422) не журналюються,
бо нічого не змінили.

Що можна передавати в details: лише службові числа й статуси (напр. кількість
виданих кодів). Будь-який ключ зі списку FORBIDDEN_KEYS спричинить помилку —
це запобіжник, щоб у журнал випадково не потрапили коди чи відповіді.
"""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .database import get_db
from .models import AuditEvent
from .roles import require_role

FORBIDDEN_KEYS = {"token", "tokens", "answers", "answer", "value", "unit",
                  "respondent_category", "category"}
AUDIT_ROLES = ("admin", "auditor")


def record(db: Session, actor_role: str, action: str, assessment_id: int | None = None,
           **details) -> None:
    """Додає запис у поточну транзакцію. Зберігається разом із db.commit() самої дії."""
    leaked = FORBIDDEN_KEYS & set(details)
    if leaked:
        raise ValueError(f"У журнал не можна записувати чутливі поля: {sorted(leaked)}")
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
