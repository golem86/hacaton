"""
«Результати підрозділу» для користувача V2: GET /v2/user/unit-results?assessment_id={id}.

Доступ — верифікована V2-сесія після 2FA (current_user), будь-яка роль; без сесії 401.
Підрозділ визначає ЛИШЕ сервер (unit_membership.get_user_unit_id); параметр unit_id від клієнта
не читається. Показуються лише закриті цикли (open/draft → 409, неіснуючий → 404).

Бали C1–C7 — та сама формула, що й в адмінських /api/assessments/{id}/results (routes/results.py):
середнє відповідей анкети персоналу, переведених у 0–100, округлення до 1 знака.

Приватність (anonymity.py): підрозділ — це група всередині підсумку циклу, тож до розмірів
підрозділів циклу застосовується первинне (< k) і вторинне приховування. Прихований підрозділ →
status "insufficient_data" без respondents і components. Компонент, на який у підрозділі відповіли
менше k анкет (або прихований вторинно серед підрозділів), → score null, status "suppressed".
Ніяких розрізів за категорією, індивідуальних відповідей, кодів чи часу; інші підрозділи не згадуються.
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..anonymity import hidden_flags, visible_groups
from ..database import get_db
from ..models import Answer, Component, Cycle, Question, ResponseSet, Unit
from ..request_limits import OptionalIdQuery
from ..services.scoring import VERSION
from ..unit_membership import get_user_unit_id
from .results import _round
from .v2_auth import current_user

router = APIRouter(prefix="/v2/user", tags=["Dashboard V2 User"])

DEFAULT_MIN_GROUP_SIZE = 5   # Cycle.min_group_size за замовчуванням — коли закритого циклу немає


def _closed_cycles(db: Session) -> list[Cycle]:
    """Закриті цикли, новіші першими."""
    return (db.query(Cycle).filter(Cycle.status == "closed")
            .order_by(Cycle.start_date.desc(), Cycle.id.desc()).all())


def _unit_hidden(sizes: dict[str, int], unit_name: str, k: int) -> bool:
    """Первинне і вторинне приховування серед підрозділів одного підсумку (anonymity.hidden_flags)."""
    names = sorted(sizes)
    if unit_name not in sizes:
        return True
    flags = hidden_flags([sizes[name] for name in names], k)
    return flags[names.index(unit_name)]


def _visible_participation_cells(db: Session, cycle_id: int, unit_name: str, k: int) -> int:
    """
    Скільки анкет підрозділу видно в адмінській participation?by_unit=true (assessments.py):
    ті самі правила — visible_groups за категоріями, потім за клітинками «категорія × підрозділ».
    """
    rows = (db.query(ResponseSet.respondent_category, ResponseSet.unit, func.count(ResponseSet.id))
            .filter(ResponseSet.cycle_id == cycle_id)
            .group_by(ResponseSet.respondent_category, ResponseSet.unit).all())
    by_category: dict[str, int] = {}
    for category, _unit, n in rows:
        by_category[category] = by_category.get(category, 0) + n
    categories, _ = visible_groups([{"category": c, "responses": by_category[c]} for c in sorted(by_category)], k)
    visible = 0
    for category in (g["category"] for g in categories):
        cells = [{"category": c, "unit": u, "responses": n} for c, u, n in sorted(rows) if c == category]
        shown, _ = visible_groups(cells, k)
        visible += sum(cell["responses"] for cell in shown if cell["unit"] == unit_name)
    return visible


def _unit_components(db: Session, cycle: Cycle, unit_name: str) -> list[dict[str, Any]]:
    k = cycle.min_group_size
    # Та сама формула, що в routes/results.py; NULLIF — шкала з одним значенням не впливає на бал
    score = func.avg((Answer.value - Question.scale_min) * 100.0
                     / func.nullif(Question.scale_max - Question.scale_min, 0))
    base = (db.query(Question.component_id).join(Answer, Answer.question_id == Question.id)
            .join(ResponseSet, ResponseSet.id == Answer.response_set_id)
            .filter(ResponseSet.cycle_id == cycle.id, Question.kind == "survey"))
    scores = dict(base.add_columns(score).filter(ResponseSet.unit == unit_name)
                  .group_by(Question.component_id).all())
    # Скільки анкет кожного підрозділу відповіли на компонент — для приховування по компоненту
    counts: dict[int, dict[str, int]] = {}
    for component_id, unit, n in (base.add_columns(ResponseSet.unit, func.count(func.distinct(ResponseSet.id)))
                                  .group_by(Question.component_id, ResponseSet.unit).all()):
        counts.setdefault(component_id, {})[unit] = n

    components = []
    for comp in db.query(Component).order_by(Component.code):
        sizes = counts.get(comp.id, {})
        if sizes.get(unit_name, 0) < k or _unit_hidden(sizes, unit_name, k):
            value, status = None, "suppressed"
        else:
            value = _round(scores.get(comp.id))
            status = "available" if value is not None else "insufficient_data"
        components.append({"code": comp.code, "name": comp.name, "score": value, "status": status})
    return components


@router.get("/unit-results")
def unit_results(response: Response, assessment_id: OptionalIdQuery = None,
                 user: dict[str, Any] = Depends(current_user), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    closed = _closed_cycles(db)
    if assessment_id is not None:
        cycle = db.get(Cycle, assessment_id)
        # Чернетка для всіх, крім admin, виглядає як неіснуючий цикл (як get_public_assessment)
        if cycle is None or (cycle.status == "draft" and user["role"] != "admin"):
            raise HTTPException(status_code=404, detail="Оцінювання не знайдено")
        if cycle.status != "closed":
            raise HTTPException(status_code=409, detail="Результати доступні після закриття оцінювання")
    else:
        cycle = closed[0] if closed else None

    unit_id = get_user_unit_id(db, int(user["id"]))
    unit = db.get(Unit, unit_id) if unit_id is not None else None

    result: dict[str, Any] = {
        "status": "available",
        "assessment": {"id": cycle.id, "name": cycle.name, "status": cycle.status} if cycle else None,
        "unit": {"id": unit.id, "name": unit.name} if unit else None,
        "min_group_size": cycle.min_group_size if cycle else DEFAULT_MIN_GROUP_SIZE,
        "respondents": None,
        "components": [],
        "available_assessments": [{"id": c.id, "name": c.name} for c in closed],
        "methodology_version": VERSION,
    }
    if unit is None:
        result["status"] = "no_unit"
        return result
    if cycle is None:
        result["status"] = "no_closed_cycle"
        return result

    k = cycle.min_group_size
    sizes = dict(db.query(ResponseSet.unit, func.count(ResponseSet.id))
                 .filter(ResponseSet.cycle_id == cycle.id).group_by(ResponseSet.unit).all())
    if sizes.get(unit.name, 0) < k or _unit_hidden(sizes, unit.name, k):
        result["status"] = "insufficient_data"
        return result

    hidden_rest = sizes[unit.name] - _visible_participation_cells(db, cycle.id, unit.name, k)
    # Разом з participation?by_unit=true кількість дала б суму прихованих клітинок підрозділу
    result["respondents"] = None if 0 < hidden_rest < k else sizes[unit.name]
    result["components"] = _unit_components(db, cycle, unit.name)
    return result
