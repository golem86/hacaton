"""
Адреси API для оцінювань (Assessment Manager + Digital Questionnaire).
Шляхи відповідають docs/API_CONTRACT.md: префікс /api, «assessment» = цикл оцінювання.

У базі цикл зберігається в таблиці `cycles` (модель Cycle); в API він називається assessment.
"""
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from .. import audit
from ..anonymity import suppress_small_groups
from ..database import get_db
from ..models import AccessToken, Answer, Component, Cycle, Question, ResponseSet, Unit
from ..roles import ALL_ROLES, ANALYTICS_ROLES, require_role

router = APIRouter(prefix="/api", tags=["Оцінювання"])

RespondentCategory = Literal["mgmt", "npp", "cadets", "staff"]


def get_assessment(assessment_id: int, db: Session) -> Cycle:
    cycle = db.get(Cycle, assessment_id)
    if cycle is None:
        raise HTTPException(status_code=404, detail="Оцінювання не знайдено")
    return cycle


def assessment_to_dict(c: Cycle) -> dict:
    return {"id": c.id, "name": c.name, "start_date": c.start_date,
            "status": c.status, "min_group_size": c.min_group_size}


# ---------------------------------------------------------------------------
# Перегляд оцінювань і анкет
# ---------------------------------------------------------------------------

@router.get("/assessments", dependencies=[Depends(require_role(*ALL_ROLES))])
def list_assessments(db: Session = Depends(get_db)):
    """Усі цикли оцінювання (для вибору циклу і графіка динаміки)."""
    return [assessment_to_dict(c) for c in db.query(Cycle).order_by(Cycle.start_date).all()]


@router.get("/assessments/{assessment_id}", dependencies=[Depends(require_role(*ALL_ROLES))])
def read_assessment(assessment_id: int, db: Session = Depends(get_db)):
    return assessment_to_dict(get_assessment(assessment_id, db))


@router.get("/assessments/{assessment_id}/questionnaires",
            dependencies=[Depends(require_role(*ALL_ROLES))])
def read_questionnaire(assessment_id: int, db: Session = Depends(get_db)):
    """Анкета: компоненти з вагами та питаннями (методика прозора — ваги видно всім)."""
    get_assessment(assessment_id, db)
    return [{"code": c.code, "name": c.name, "weight": c.weight,
             "questions": [{"id": q.id, "text": q.text, "scale": [q.scale_min, q.scale_max]}
                           for q in c.questions if q.kind == "survey"]}
            for c in db.query(Component).order_by(Component.code).all()]


@router.get("/units", dependencies=[Depends(require_role(*ALL_ROLES))])
def list_units(db: Session = Depends(get_db)):
    """Довідник підрозділів — для випадного списку в анкеті."""
    return [u.name for u in db.query(Unit).order_by(Unit.name).all()]


# ---------------------------------------------------------------------------
# Анонімне надсилання анкети
# ---------------------------------------------------------------------------

class AnswerIn(BaseModel):
    question_id: int
    value: int


class AnonymousSubmission(BaseModel):
    token: str = Field(description="Одноразовий код доступу")
    respondent_category: RespondentCategory
    unit: str = Field(min_length=1, max_length=100)
    answers: list[AnswerIn]


@router.post("/assessments/{assessment_id}/submissions", status_code=201,
             dependencies=[Depends(require_role("respondent"))])
def submit_answers(assessment_id: int, body: AnonymousSubmission, db: Session = Depends(get_db)):
    """
    Приймає заповнену анкету.

    Як захищено анонімність:
    - код доступу лише позначається «використаним»; зв'язку код ↔ анкета ніде немає;
    - в анкеті зберігаються тільки категорія й підрозділ;
    - у відповідь НЕ повертається номер анкети, щоб його не можна було ні з чим зіставити.
    """
    cycle = get_assessment(assessment_id, db)
    if cycle.status != "open":
        raise HTTPException(status_code=409, detail="Оцінювання закрите")

    # Підрозділ — лише з довідника: довільний текст (прізвище, кімната) у базу не потрапить
    if db.query(Unit).filter_by(name=body.unit).first() is None:
        raise HTTPException(status_code=422, detail="Підрозділ не з довідника (див. GET /api/units)")

    # Перевірка відповідей: на кожне питання анкети рівно одна відповідь у межах шкали
    questions = {q.id: q for q in db.query(Question).filter(Question.kind == "survey").all()}
    given = [a.question_id for a in body.answers]
    if sorted(given) != sorted(questions):
        raise HTTPException(status_code=422, detail="Потрібна рівно одна відповідь на кожне питання анкети")
    for a in body.answers:
        q = questions[a.question_id]
        if not q.scale_min <= a.value <= q.scale_max:
            raise HTTPException(status_code=422,
                                detail=f"Відповідь на питання {q.id} має бути від {q.scale_min} до {q.scale_max}")

    # «Погасити» код атомарно: спрацює лише якщо код існує, належить цьому циклу і ще не використаний.
    # Одне повідомлення для всіх випадків — щоб не можна було перебором дізнатися, які коди існують.
    redeemed = db.execute(
        update(AccessToken)
        .where(AccessToken.token == body.token, AccessToken.cycle_id == assessment_id,
               AccessToken.used.is_(False))
        .values(used=True)
    ).rowcount
    if redeemed != 1:
        db.rollback()
        raise HTTPException(status_code=403, detail="Недійсний або вже використаний код доступу")

    rs = ResponseSet(cycle_id=assessment_id, respondent_category=body.respondent_category, unit=body.unit)
    rs.answers = [Answer(question_id=a.question_id, value=a.value) for a in body.answers]
    db.add(rs)
    db.commit()  # код і анкета зберігаються разом: або обидва, або нічого
    return {"status": "accepted"}


# ---------------------------------------------------------------------------
# Керування оцінюванням
# ---------------------------------------------------------------------------

@router.post("/assessments/{assessment_id}/tokens", status_code=201)
def issue_tokens(assessment_id: int, count: int = Query(default=10, ge=1, le=500),
                 role: str = Depends(require_role("admin")), db: Session = Depends(get_db)):
    """Видає одноразові коди доступу для учасників. Коди роздаються анонімно (напр. роздруківками)."""
    cycle = get_assessment(assessment_id, db)
    if cycle.status != "open":
        raise HTTPException(status_code=409, detail="Оцінювання закрите")
    tokens = [secrets.token_hex(16) for _ in range(count)]
    db.add_all(AccessToken(cycle_id=assessment_id, token=t, used=False) for t in tokens)
    audit.record(db, role, "tokens.issue", assessment_id, count=count)  # лише кількість, не коди
    db.commit()
    return {"tokens": tokens}


@router.post("/assessments/{assessment_id}/close")
def close_assessment(assessment_id: int, role: str = Depends(require_role("admin")),
                     db: Session = Depends(get_db)):
    """
    Завершує оцінювання: нові анкети більше не приймаються, а результати й розбивка
    стають доступними (до закриття їх не показуємо — захист анонімності).
    """
    cycle = get_assessment(assessment_id, db)
    if cycle.status != "open":
        raise HTTPException(status_code=409, detail="Оцінювання вже закрите")
    cycle.status = "closed"
    audit.record(db, role, "assessment.close", assessment_id)
    db.commit()
    return assessment_to_dict(cycle)


@router.get("/assessments/{assessment_id}/participation",
            dependencies=[Depends(require_role(*ANALYTICS_ROLES))])
def participation(assessment_id: int, by_unit: bool = False, db: Session = Depends(get_db)):
    """
    Статистика участі.

    Політика агрегації (захист від відновлення прихованих груп):
    - поки оцінювання ВІДКРИТЕ, показується лише загальна кількість анкет — без розбивки,
      інакше, порівнюючи дві відповіді до і після чиєїсь анкети, можна дізнатися її категорію;
    - після закриття: розбивка по категоріях (by_unit=true — категорія × підрозділ)
      з первинним і вторинним приховуванням, щоб «підсумок − видимі» не давав розмір малої групи;
    - категорії, приховані в загальній розбивці, приховуються і в розбивці по підрозділах;
    - загальна кількість показується, лише якщо вона ≥ k.
    """
    cycle = get_assessment(assessment_id, db)
    k = cycle.min_group_size

    total = db.query(ResponseSet).filter(ResponseSet.cycle_id == assessment_id).count()
    issued = db.query(AccessToken).filter(AccessToken.cycle_id == assessment_id).count()
    result = {"status": cycle.status, "tokens_issued": issued,
              "responses_total": total if total >= k else None, "groups": None}
    if cycle.status == "open":
        return result

    # 1. Розбивка по категоріях — підсумок для неї: загальна кількість анкет
    cat_rows = (db.query(ResponseSet.respondent_category, func.count(ResponseSet.id))
                .filter(ResponseSet.cycle_id == assessment_id)
                .group_by(ResponseSet.respondent_category)
                .order_by(ResponseSet.respondent_category).all())
    categories = suppress_small_groups([{"category": c, "responses": n} for c, n in cat_rows],
                                       k, keep_keys=("category",))
    if not by_unit:
        result["groups"] = categories
        return result

    # 2. Категорія × підрозділ — для кожної категорії свій підсумок (її кількість)
    category_hidden = {g["category"]: g["hidden"] for g in categories}
    unit_rows = (db.query(ResponseSet.respondent_category, ResponseSet.unit, func.count(ResponseSet.id))
                 .filter(ResponseSet.cycle_id == assessment_id)
                 .group_by(ResponseSet.respondent_category, ResponseSet.unit)
                 .order_by(ResponseSet.respondent_category, ResponseSet.unit).all())
    groups = []
    for category, hidden in category_hidden.items():
        cells = [{"category": c, "unit": u, "responses": n} for c, u, n in unit_rows if c == category]
        groups += suppress_small_groups(cells, k, keep_keys=("category", "unit"),
                                        force_hidden=[hidden] * len(cells))
    result["groups"] = groups
    return result
