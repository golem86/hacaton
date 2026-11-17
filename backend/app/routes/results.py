"""
Агреговані результати оцінювання — «сировина» для Integrity Index (№3/№4) і Dashboard.

Що віддаємо: бал кожного компонента (0–100) загалом і по категоріях респондентів,
плюс об'єктивні показники циклу для зіставлення.

Чого НЕ віддаємо: окремих анкет і відповідей — лише середні по групах.

Захист анонімності:
- результати доступні лише після ЗАКРИТТЯ оцінювання (інакше порівняння «до/після»
  чиєїсь анкети розкрило б її відповіді);
- категорії, менші за k, приховуються; додатково приховується ще одна, якщо інакше
  із загального бала можна було б вирахувати бал малої групи (див. anonymity.py).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..anonymity import hidden_flags
from ..database import get_db
from ..models import Answer, Component, Cycle, ObjectiveIndicator, Question, ResponseSet
from ..roles import ANALYTICS_ROLES, require_role

router = APIRouter(prefix="/api", tags=["Результати"])


def _round(x: float | None) -> float | None:
    return None if x is None else round(x, 1)


@router.get("/assessments/{assessment_id}/results",
            dependencies=[Depends(require_role(*ANALYTICS_ROLES))])
def assessment_results(assessment_id: int, db: Session = Depends(get_db)):
    """
    Бал компонента = середнє відповідей, переведених у 0–100:
        (відповідь − мінімум шкали) / (максимум − мінімум) × 100.
    Напр. за шкалою 1–5: 1 → 0, 3 → 50, 5 → 100.
    """
    cycle = db.get(Cycle, assessment_id)
    if cycle is None:
        raise HTTPException(status_code=404, detail="Оцінювання не знайдено")
    if cycle.status != "closed":
        raise HTTPException(status_code=409, detail="Результати доступні після закриття оцінювання")
    k = cycle.min_group_size

    # 1. Скільки анкет у кожній категорії → що приховувати
    sizes = dict(db.query(ResponseSet.respondent_category, func.count(ResponseSet.id))
                 .filter(ResponseSet.cycle_id == assessment_id)
                 .group_by(ResponseSet.respondent_category).all())
    categories = sorted(sizes)
    flags = dict(zip(categories, hidden_flags([sizes[c] for c in categories], k)))
    total = sum(sizes.values())

    # 2. Середній бал (0–100) по компоненту × категорії і по компоненту загалом
    # NULLIF: шкала з одним значенням (min == max) дає NULL замість ділення на нуль,
    # а AVG пропускає NULL — тож такі питання не впливають на бал компонента.
    score = func.avg((Answer.value - Question.scale_min) * 100.0
                     / func.nullif(Question.scale_max - Question.scale_min, 0))
    base = (db.query(Question.component_id).join(Answer, Answer.question_id == Question.id)
            .join(ResponseSet, ResponseSet.id == Answer.response_set_id)
            .filter(ResponseSet.cycle_id == assessment_id, Question.kind == "survey"))
    by_cat = {(cid, cat): s for cid, cat, s in
              base.add_columns(ResponseSet.respondent_category, score)
              .group_by(Question.component_id, ResponseSet.respondent_category).all()}
    overall = dict(base.add_columns(score).group_by(Question.component_id).all())

    # 3. Об'єктивні показники циклу
    objective: dict[int, list] = {}
    for ind in db.query(ObjectiveIndicator).filter_by(cycle_id=assessment_id).order_by(ObjectiveIndicator.id):
        objective.setdefault(ind.component_id, []).append(
            {"name": ind.name, "value": ind.value, "confirmed": ind.confirmed})

    overall_visible = total >= k
    components = []
    for comp in db.query(Component).order_by(Component.code):
        components.append({
            "code": comp.code, "name": comp.name, "weight": comp.weight,
            "score": _round(overall.get(comp.id)) if overall_visible else None,
            "by_category": [{"category": c,
                             "score": None if flags[c] else _round(by_cat.get((comp.id, c))),
                             "hidden": flags[c]} for c in categories],
            "objective_indicators": objective.get(comp.id, []),
        })

    return {
        "assessment": {"id": cycle.id, "name": cycle.name, "status": cycle.status},
        "min_group_size": k,
        "responses_total": total if overall_visible else None,
        "categories": [{"category": c, "responses": None if flags[c] else sizes[c], "hidden": flags[c]}
                       for c in categories],
        "components": components,
    }
