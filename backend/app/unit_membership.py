"""
Належність користувача V2 до підрозділу (для екрана «Результати підрозділу», GET /v2/user/unit-results).

Довірене джерело — лише власник сервера через консоль (python -m app.v2_unit_cli, ops\\Set-V2UserUnit.ps1).
Користувач і веб-адміністратор підрозділ не призначають; клієнт ніколи не передає unit_id як підставу доступу.

Зберігання без зміни схеми: таблиця instance_meta БД integrity, по рядку на користувача:
  key   = "unit_member:<id користувача V2_AUTH_DB>"
  value = "<units.id>"
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import InstanceMeta, Unit

KEY_PREFIX = "unit_member:"


def membership_key(user_id: int) -> str:
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
        raise ValueError("user_id має бути додатним цілим")
    return f"{KEY_PREFIX}{user_id}"


def get_user_unit_id(db: Session, user_id: int) -> int | None:
    """id підрозділу користувача або None (немає призначення, некоректне значення, підрозділ видалено)."""
    row = db.get(InstanceMeta, membership_key(user_id))
    if row is None:
        return None
    try:
        unit_id = int(row.value)
    except (TypeError, ValueError):
        return None
    if unit_id <= 0 or db.get(Unit, unit_id) is None:
        return None
    return unit_id


def set_user_unit_id(db: Session, user_id: int, unit_id: int | None) -> None:
    """Призначає (або з unit_id=None знімає) підрозділ. Без commit — його робить викликач."""
    key = membership_key(user_id)
    row = db.get(InstanceMeta, key)
    if unit_id is None:
        if row is not None:
            db.delete(row)
        return
    if not isinstance(unit_id, int) or isinstance(unit_id, bool) or unit_id <= 0 or db.get(Unit, unit_id) is None:
        raise ValueError("Невідомий підрозділ")
    if row is None:
        db.add(InstanceMeta(key=key, value=str(unit_id)))
    else:
        row.value = str(unit_id)
