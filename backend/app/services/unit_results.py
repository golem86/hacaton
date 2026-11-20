"""
Узагальнені результати підрозділу для звичайного користувача V2 (екран «Результати підрозділу»).

Контракт: docs/USER_UNIT_RESULTS_API_PROPOSAL.md. Що віддаємо: середній бал (0–100) кожного
компонента C1–C7 по всіх анкетах підрозділу користувача за закритий цикл. Чого НЕ віддаємо:
окремих анкет, відповідей, розрізу за категоріями респондентів, розмірів інших підрозділів.

Звідки відомо, який це підрозділ: лише з таблиці user_units, яку заповнює власник сервера
(python -m app.v2_unit_cli). Клієнт не передає підрозділ — тож переглянути чужий не можна,
а один користувач завжди бачить один і той самий зріз (немає фільтрів для «перебору»).

Анонімність (k = min_group_size циклу). Результат показується лише якщо ОДНОЧАСНО:
  1. у підрозділі користувача щонайменше k анкет;
  2. у ВСЬОМУ циклі кожна непорожня клітинка «категорія × підрозділ» має щонайменше k анкет.
Чому правило 2 про весь цикл, а не лише про свій підрозділ: бали підрозділів (їх бачать різні
користувачі), бали категорій (/results, бачить керівництво) і загальний бал — це суми по клітинках
однієї таблиці «категорія × підрозділ». Віднімання між ними (зокрема змова кількох користувачів із
різних підрозділів чи один користувач, якого перевели в інший підрозділ) дає лише суму кількох цілих
клітинок. Якщо кожна непорожня клітинка ≥ k, будь-який такий результат — середнє щонайменше k людей.
Якщо хоч одна клітинка має 1…k−1 анкет, жоден підрозділ цього циклу не показується.
Додатково:
  - кількість анкет округлюється вниз до кратного 5 (точне число разом із розбивкою участі
    дозволяло б дізнатися, чи всі в підрозділі подали анкету);
  - порожній і малий підрозділ дають однакову відповідь;
  - чернетка циклу не відрізняється від неіснуючого (404).
Залишковий ризик: k−1 учасників підрозділу у змові, віднявши власні відповіді, отримують відповіді
останнього — так само, як і для будь-якого агрегата з порогом k (docs/anonymity.md).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Answer, Component, Cycle, Question, ResponseSet, UserUnit

METHODOLOGY_VERSION = "unit-mean-0-100-v1"
COUNT_STEP = 5            # кількість анкет показується з кроком 5 (вниз)


class UnitResultsUnavailable(Exception):
    """code: not_found (циклу немає) або not_closed (цикл ще не закрито)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _round(x: float | None) -> float | None:
    return None if x is None else round(float(x), 1)


def unit_results(db: Session, assessment_id: int, user_id: int) -> dict[str, Any]:
    cycle = db.get(Cycle, assessment_id)
    if cycle is None or cycle.status not in ("open", "closed"):   # чернетка = «немає» (без оракула)
        raise UnitResultsUnavailable("not_found")
    if cycle.status != "closed":
        raise UnitResultsUnavailable("not_closed")
    k = cycle.min_group_size
    components = db.query(Component).order_by(Component.code).all()
    membership = db.get(UserUnit, user_id)

    def empty(privacy_status: str, unit: str | None) -> dict[str, Any]:
        return {
            "assessment": {"id": cycle.id, "name": cycle.name, "status": cycle.status},
            "unit": unit,
            "methodology_version": METHODOLOGY_VERSION,
            "min_group_size": k,
            "privacy_status": privacy_status,
            "responses": None,
            "components": [{"code": c.code, "name": c.name, "score": None, "status": "suppressed"}
                           for c in components],
        }

    if membership is None:
        return empty("no_unit", None)

    cells = (db.query(ResponseSet.respondent_category, ResponseSet.unit, func.count(ResponseSet.id))
             .filter(ResponseSet.cycle_id == assessment_id)
             .group_by(ResponseSet.respondent_category, ResponseSet.unit).all())
    unit_count = sum(n for _, unit, n in cells if unit == membership.unit)
    small_cell = any(0 < n < k for _, _, n in cells)
    if unit_count < k or small_cell:
        return empty("suppressed", membership.unit)

    # Та сама формула, що й у /api/assessments/{id}/results: (відповідь − мін) / (макс − мін) × 100
    score = func.avg((Answer.value - Question.scale_min) * 100.0
                     / func.nullif(Question.scale_max - Question.scale_min, 0))
    scores = dict(db.query(Question.component_id, score)
                  .join(Answer, Answer.question_id == Question.id)
                  .join(ResponseSet, ResponseSet.id == Answer.response_set_id)
                  .filter(ResponseSet.cycle_id == assessment_id, ResponseSet.unit == membership.unit,
                          Question.kind == "survey")
                  .group_by(Question.component_id).all())
    result = empty("available", membership.unit)
    result["responses"] = unit_count // COUNT_STEP * COUNT_STEP
    result["components"] = [
        {"code": c.code, "name": c.name, "score": _round(scores.get(c.id)),
         "status": "available" if scores.get(c.id) is not None else "insufficient_data"}
        for c in components]
    return result


def assign_unit(db: Session, user_id: int, unit: str | None) -> None:
    """Призначає (або знімає, unit=None) підрозділ. Викликає лише серверна команда."""
    current = db.get(UserUnit, user_id)
    if unit is None:
        if current is not None:
            db.delete(current)
        return
    if current is None:
        db.add(UserUnit(user_id=user_id, unit=unit, assigned_at=datetime.now(timezone.utc)))
    else:
        current.unit = unit
        current.assigned_at = datetime.now(timezone.utc)
