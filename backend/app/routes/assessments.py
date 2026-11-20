"""
Адреси API для оцінювань (Assessment Manager + Digital Questionnaire).
Шляхи відповідають docs/API_CONTRACT.md: префікс /api, «assessment» = цикл оцінювання.

У базі цикл зберігається в таблиці `cycles` (модель Cycle); в API він називається assessment.
"""
import secrets
import json
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, StrictInt, ValidationError, model_validator
from sqlalchemy import func, update, exists, select
from sqlalchemy.orm import Session

from .. import audit
from ..anonymity import visible_groups
from ..database import get_db
from ..models import (AccessToken, AccessTokenPolicy, Answer, Component, Cycle, CycleConfig, Question,
                      ResponseSet, Unit, hash_access_code)
from ..questionnaire_contract import SAFE_INTEGER, Questionnaire
from ..request_limits import BoundedId
from ..roles import require_role, resolve_principal

router = APIRouter(prefix="/api", tags=["Оцінювання"])

RespondentCategory = Literal["mgmt", "npp", "cadets", "staff"]
DEMO_VERSION = "demo-v1"
# Ролі (docs/V2_HARDENING_CONTRACT.md, розділ 1): коди видають admin і data_officer. Рішення власника:
# admin має всі права data_officer, тож атака n−1 (видати коди й бачити результати) доступна будь-якому
# адміністратору — ризик свідомо прийнято. Запобіжники: адмінів призначає лише власник сервера, подія
# журналу tokens.issue з роллю й actor_user_id, журнал v2_role_changes, поріг k (min_group_size).
TOKEN_ISSUER_ROLES = ("admin", "data_officer")
PARTICIPATION_ROLES = ("admin", "data_officer")
OPEN_COUNT_STEP = 5           # у незакритому циклі кількості округлюються вниз до кратного 5 (D7)


def get_assessment(assessment_id: int, db: Session) -> Cycle:
    cycle = db.get(Cycle, assessment_id)
    if cycle is None:
        raise HTTPException(status_code=404, detail="Оцінювання не знайдено")
    return cycle


def sees_drafts(request: Request) -> bool:
    """Чернетки бачить лише admin (сесія; у development — і демо X-Role). 401 тут не піднімається."""
    principal = resolve_principal(request)
    return principal is not None and principal["role"] == "admin"


def get_public_assessment(assessment_id: int, db: Session, request: Request | None = None) -> Cycle:
    """Публічні маршрути: чернетка для всіх, крім admin, виглядає як неіснуючий цикл (404)."""
    cycle = get_assessment(assessment_id, db)
    if cycle.status == "draft" and (request is None or not sees_drafts(request)):
        raise HTTPException(status_code=404, detail="Оцінювання не знайдено")
    return cycle


def assessment_to_dict(c: Cycle, db: Session | None = None) -> dict:
    result = {"id": c.id, "name": c.name, "start_date": c.start_date,
              "status": c.status, "min_group_size": c.min_group_size}
    if db is not None:
        config = db.get(CycleConfig, c.id)
        result.update(description=config.description if config else "",
                      scope=config.scope if config else "",
                      end_date=config.end_date if config else None,
                      categories=json.loads(config.categories_json) if config else ["mgmt", "npp", "cadets", "staff"],
                      questionnaire_version=config.questionnaire_version if config else DEMO_VERSION)
    return result


class CycleIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    description: str = Field(default="", max_length=2000)
    scope: str = Field(default="", max_length=200)
    start_date: date
    end_date: date | None = None
    categories: list[RespondentCategory] = Field(min_length=1, max_length=4)
    min_group_size: StrictInt = Field(ge=5, le=1000)
    questionnaire_version: Literal["demo-v1"] = DEMO_VERSION

    @model_validator(mode="after")
    def valid_config(self):
        if not self.name.strip():
            raise ValueError("Назва циклу не може бути порожньою")
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("Дата завершення передує даті початку")
        if len(self.categories) != len(set(self.categories)):
            raise ValueError("Категорії не можуть повторюватися")
        return self


@router.post("/assessments", status_code=201)
def create_assessment(body: CycleIn, request: Request, role: str = Depends(require_role("admin")),
                      db: Session = Depends(get_db)):
    cycle = Cycle(name=body.name.strip(), start_date=body.start_date,
                  status="draft", min_group_size=body.min_group_size)
    db.add(cycle)
    db.flush()
    db.add(CycleConfig(cycle_id=cycle.id, description=body.description, scope=body.scope,
                       end_date=body.end_date, categories_json=json.dumps(body.categories),
                       questionnaire_version=body.questionnaire_version))
    audit.record(db, role, "assessment.create", cycle.id, actor_user_id=audit.actor_user_id(request))
    db.commit()
    return assessment_to_dict(cycle, db)


@router.post("/assessments/{assessment_id}/activate")
def activate_assessment(assessment_id: BoundedId, request: Request, role: str = Depends(require_role("admin")),
                        db: Session = Depends(get_db)):
    cycle = get_assessment(assessment_id, db)
    if cycle.status != "draft":
        raise HTTPException(409, "Лише чернетку можна активувати")
    cycle.status = "open"
    audit.record(db, role, "assessment.activate", cycle.id, actor_user_id=audit.actor_user_id(request))
    db.commit()
    return assessment_to_dict(cycle, db)


# ---------------------------------------------------------------------------
# Перегляд оцінювань і анкет
# ---------------------------------------------------------------------------

@router.get("/assessments")  # публічний GET (розділ 2.1)
def list_assessments(request: Request, db: Session = Depends(get_db)):
    """
    Цикли оцінювання (для вибору циклу і графіка динаміки).
    Чернетки (з внутрішнім описом) бачить лише admin; анонім і user — ні (D9).
    """
    query = db.query(Cycle)
    if not sees_drafts(request):
        query = query.filter(Cycle.status != "draft")
    return [assessment_to_dict(c, db) for c in query.order_by(Cycle.start_date).all()]


@router.get("/assessments/{assessment_id}")  # публічний GET; чернетка — 404 для всіх, крім admin
def read_assessment(assessment_id: BoundedId, request: Request, db: Session = Depends(get_db)):
    return assessment_to_dict(get_public_assessment(assessment_id, db, request), db)


@router.get("/assessments/{assessment_id}/questionnaires")  # публічний GET; чернетка — 404, крім admin
def read_questionnaire(assessment_id: BoundedId, request: Request, db: Session = Depends(get_db)):
    """
    Анкета: компоненти з вагами та питаннями (методика прозора — ваги видно всім).
    Перед видачею перевіряється контракт (questionnaire_contract.py): шкала 1–10 значень,
    безпечні цілі межі, унікальні id питань. Якщо дані в БД його порушують — це помилка
    налаштування сервера (500), а не клієнта: фронтенд некоректної анкети не отримає.
    """
    get_public_assessment(assessment_id, db, request)
    data = [{"code": c.code, "name": c.name, "weight": c.weight,
             "questions": [{"id": q.id, "text": q.text, "scale": [q.scale_min, q.scale_max]}
                           for q in c.questions if q.kind == "survey"]}
            for c in db.query(Component).order_by(Component.code).all()]
    try:
        Questionnaire.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(status_code=500,
                            detail="Анкета в базі порушує контракт шкали; зверніться до адміністратора") from exc
    return data


@router.get("/units")  # публічний GET
def list_units(db: Session = Depends(get_db)):
    """Довідник підрозділів — для випадного списку в анкеті."""
    return [u.name for u in db.query(Unit).order_by(Unit.name).all()]


# ---------------------------------------------------------------------------
# Анонімне надсилання анкети
# ---------------------------------------------------------------------------

class AnswerIn(BaseModel):
    # Строгі цілі: "4", 4.0, 4.5 чи true відхиляються з 422 (а не перетворюються мовчки)
    question_id: StrictInt = Field(ge=1, le=SAFE_INTEGER)
    value: StrictInt = Field(ge=-SAFE_INTEGER, le=SAFE_INTEGER)


class AnonymousSubmission(BaseModel):
    token: str = Field(min_length=1, max_length=128, description="Одноразовий код доступу")
    questionnaire_version: str | None = Field(default=None, max_length=50)
    respondent_category: RespondentCategory
    unit: str = Field(min_length=1, max_length=100)
    answers: list[AnswerIn] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_questions(self):
        ids = [a.question_id for a in self.answers]
        if len(ids) != len(set(ids)):
            raise ValueError("Кожне питання може мати лише одну відповідь")
        return self


# Анонімний Survey POST: доступ ЛИШЕ за одноразовим кодом. Маршрут не читає cookie сесії
# і не приймає X-Role (наскрізна анонімність, розділ 1.2 контракту).
@router.post("/assessments/{assessment_id}/submissions", status_code=201)
def submit_answers(assessment_id: BoundedId, body: AnonymousSubmission, db: Session = Depends(get_db)):
    """
    Приймає заповнену анкету.

    Як захищено анонімність:
    - код доступу лише позначається «використаним»; зв'язку код ↔ анкета ніде немає;
    - у БД лежить лише SHA-256 коду (schema 5), пошук і погашення — за хешем;
    - в анкеті зберігаються тільки категорія й підрозділ;
    - у відповідь НЕ повертається номер анкети, щоб його не можна було ні з чим зіставити.
    """
    cycle = get_public_assessment(assessment_id, db)      # чернетка — 404 (маршрут не читає сесію)
    if cycle.status != "open":
        raise HTTPException(status_code=409, detail="Оцінювання закрите")
    config = db.get(CycleConfig, assessment_id)
    if config:
        if date.today() < cycle.start_date:
            raise HTTPException(409, "Строк оцінювання ще не розпочався")
        if body.respondent_category not in json.loads(config.categories_json):
            raise HTTPException(403, "Категорія недоступна для цього циклу")
        if body.questionnaire_version != config.questionnaire_version:
            raise HTTPException(409, "Версія анкети не відповідає циклу")
        if config.end_date and date.today() > config.end_date:
            raise HTTPException(409, "Строк оцінювання завершився")

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
    policy_ok = exists(select(AccessTokenPolicy.token_id).where(
        AccessTokenPolicy.token_id == AccessToken.id,
        AccessTokenPolicy.category == body.respondent_category,
        AccessTokenPolicy.expires_at > datetime.now(timezone.utc).replace(tzinfo=None)))
    if not config:
        policy_ok = (~exists(select(AccessTokenPolicy.token_id).where(
            AccessTokenPolicy.token_id == AccessToken.id))) | policy_ok
    redeemed = db.execute(
        update(AccessToken)
        .where(AccessToken.token_hash == hash_access_code(body.token), AccessToken.cycle_id == assessment_id,
               AccessToken.used.is_(False),
               exists(select(Cycle.id).where(Cycle.id == assessment_id, Cycle.status == "open")),
               policy_ok)
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
def issue_tokens(assessment_id: BoundedId, request: Request, count: int = Query(default=10, ge=1, le=500),
                 category: RespondentCategory | None = None,
                 expires_days: int = Query(default=14, ge=1, le=365),
                 role: str = Depends(require_role(*TOKEN_ISSUER_ROLES)), db: Session = Depends(get_db)):
    """
    Видає одноразові коди доступу для учасників. Коди роздаються анонімно (напр. роздруківками).
    admin і data_officer (інші → 403). Ризик n−1 для admin свідомо прийнято власником; кожна видача —
    подія журналу tokens.issue з роллю, actor_user_id і кількістю (без кодів).
    Відкриті коди повертаються ОДИН раз; у БД зберігається лише SHA-256 кожного коду.
    """
    cycle = get_assessment(assessment_id, db)
    if cycle.status != "open":
        raise HTTPException(status_code=409, detail="Оцінювання закрите")
    config = db.get(CycleConfig, assessment_id)
    if config and (category is None or category not in json.loads(config.categories_json)):
        raise HTTPException(422, "Оберіть дозволену категорію для коду")
    # Повторна перевірка `open` у транзакції запису: умовний UPDATE бере блокування запису SQLite
    # і перевіряє статус атомарно. Якщо цикл закрили після першого читання — жодного коду й аудиту.
    still_open = db.execute(
        update(Cycle).where(Cycle.id == assessment_id, Cycle.status == "open").values(status="open")
    ).rowcount
    if still_open != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Оцінювання закрите")
    tokens = [secrets.token_hex(16) for _ in range(count)]
    rows = [AccessToken(cycle_id=assessment_id, token_hash=hash_access_code(t), used=False) for t in tokens]
    db.add_all(rows)
    db.flush()
    if config:
        expiry = (datetime.now(timezone.utc) + timedelta(days=expires_days)).replace(tzinfo=None)
        db.add_all(AccessTokenPolicy(token_id=row.id, category=category, expires_at=expiry) for row in rows)
    audit.record(db, role, "tokens.issue", assessment_id, count=count,   # лише кількість, не коди
                 actor_user_id=audit.actor_user_id(request))
    db.commit()
    return {"tokens": tokens}


@router.post("/assessments/{assessment_id}/close")
def close_assessment(assessment_id: BoundedId, request: Request, role: str = Depends(require_role("admin")),
                     db: Session = Depends(get_db)):
    """
    Завершує оцінювання: нові анкети більше не приймаються, а результати й розбивка
    стають доступними (до закриття їх не показуємо — захист анонімності).
    """
    cycle = get_assessment(assessment_id, db)
    if cycle.status != "open":
        raise HTTPException(status_code=409, detail="Оцінювання вже закрите")
    cycle.status = "closed"
    audit.record(db, role, "assessment.close", assessment_id, actor_user_id=audit.actor_user_id(request))
    db.commit()
    return assessment_to_dict(cycle, db)


def _floor_step(value: int) -> int:
    return value - value % OPEN_COUNT_STEP


@router.get("/assessments/{assessment_id}/participation",
            dependencies=[Depends(require_role(*PARTICIPATION_ROLES))])
def participation(assessment_id: BoundedId, by_unit: bool = False, db: Session = Depends(get_db)):
    """
    Статистика участі. Доступ: admin і data_officer.

    Політика агрегації (захист від відновлення прихованих груп):
    - поки оцінювання НЕ закрите, кількості неточні (D7): responses_total і tokens_unused
      округлюються вниз до кратного 5 і показуються, лише якщо ≥ k, `counts_exact: false`;
      відсоток рахується з округленого числа. Інакше, опитуючи участь після кожного подання,
      можна було б дізнатися час кожної анкети. Розбивки немає (`groups: null`);
    - після закриття значення точні (`counts_exact: true`), а розбивка по категоріях
      (by_unit=true — категорія × підрозділ) проходить первинне і вторинне приховування;
    - приховані групи НЕ перелічуються взагалі (D4): немає ні назви категорії, ні підрозділу.
      `suppressed: true` — у розрізі щось приховано або розбивки немає зовсім.
      Різниця «підсумок − видимі» = сума всіх прихованих груп, яка за anonymity.py ≥ k;
    - у розбивці по підрозділах — лише клітинки видимих категорій, з окремим
      вторинним приховуванням у межах кожної категорії (підсумок — її кількість);
    - загальна кількість показується, лише якщо вона ≥ k.
    """
    cycle = get_assessment(assessment_id, db)
    k = cycle.min_group_size

    total = db.query(ResponseSet).filter(ResponseSet.cycle_id == assessment_id).count()
    issued = db.query(AccessToken).filter(AccessToken.cycle_id == assessment_id).count()
    unused = db.query(AccessToken).filter_by(cycle_id=assessment_id, used=False).count()
    # Відкриття `unused` до k розкриває used = issued - unused, а в реальному
    # циклі used дорівнює кількості анкет. Видано кодів показувати безпечно;
    # невикористані коди й відсоток відкриваємо лише разом із видимим total.
    visible = total >= k
    exact = cycle.status == "closed"
    if exact:
        shown_total = total if visible else None
        shown_unused = unused if visible else None
    else:
        shown_total = _floor_step(total) if visible and _floor_step(total) >= k else None
        shown_unused = _floor_step(unused) if visible and _floor_step(unused) >= k else None
    result = {"status": cycle.status, "tokens_issued": issued, "tokens_unused": shown_unused,
              "participation_percent": round(100 * shown_total / issued, 1)
              if issued and shown_total is not None else None,
              "responses_total": shown_total, "counts_exact": exact, "groups": None, "suppressed": True}
    # Навіть назва категорії в закритому циклі з < k анкетами підтвердила б,
    # що хтось із дуже малої групи взяв участь. У цьому випадку немає розбивки.
    if not exact or not visible:
        return result

    # 1. Розбивка по категоріях — підсумок для неї: загальна кількість анкет
    cat_rows = (db.query(ResponseSet.respondent_category, func.count(ResponseSet.id))
                .filter(ResponseSet.cycle_id == assessment_id)
                .group_by(ResponseSet.respondent_category)
                .order_by(ResponseSet.respondent_category).all())
    categories, suppressed = visible_groups([{"category": c, "responses": n} for c, n in cat_rows], k)
    if not by_unit:
        result.update(groups=categories, suppressed=suppressed)
        return result

    # 2. Категорія × підрозділ — лише для видимих категорій; підсумок кожної — її кількість.
    #    Клітинки прихованих категорій не повертаються (їх не можна «зібрати» з підрозділів).
    unit_rows = (db.query(ResponseSet.respondent_category, ResponseSet.unit, func.count(ResponseSet.id))
                 .filter(ResponseSet.cycle_id == assessment_id)
                 .group_by(ResponseSet.respondent_category, ResponseSet.unit)
                 .order_by(ResponseSet.respondent_category, ResponseSet.unit).all())
    groups = []
    for category in (g["category"] for g in categories):
        cells = [{"category": c, "unit": u, "responses": n} for c, u, n in unit_rows if c == category]
        shown, cells_suppressed = visible_groups(cells, k)
        groups += shown
        suppressed = suppressed or cells_suppressed
    result.update(groups=groups, suppressed=suppressed)
    return result
