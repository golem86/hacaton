"""
Зрілість за Додатком В: анонімні анкети, експертна оцінка, чек-лист (Додаток Б), об'єктивні показники
і розрахунок зрілості (services/maturity.py). Контракт — docs/API_CONTRACT.md, розділ «Зрілість за Додатком В».

Маршрути:
  POST /api/assessments/{id}/annex-v/responses        — ПУБЛІЧНИЙ, анонімно за одноразовим кодом циклу;
  POST /api/assessments/{id}/annex-v/expert           — admin (сесія + CSRF), експерт — посада, не ПІБ;
  GET  /api/assessments/{id}/checklist                 — admin, data_officer, ролі аналітики;
  PUT  /api/assessments/{id}/checklist/{code}          — data_officer або admin (CSRF), скидає підтвердження;
  POST /api/assessments/{id}/checklist/{code}/confirm  — admin (CSRF), не той самий користувач, що вніс;
  GET  /api/assessments/{id}/objective-indicators      — admin, data_officer, ролі аналітики;
  POST /api/assessments/{id}/objective-indicators      — data_officer або admin (CSRF);
  POST /api/objective-indicators/{indicator_id}/confirm — admin (CSRF), не той самий користувач;
  GET  /api/assessments/{id}/maturity                  — ролі аналітики, закритий цикл, INTEGRITY_ANALYTICS_DEMO=1.

Анонімність анкет Додатка В — як у POST /submissions: маршрут не читає сесію, код лише гаситься
(без зв'язку з анкетою), в анкеті тільки категорія, форма й версія — без часу подання.
Подання не журналюються (audit) і не потрапляють у журнал доступу uvicorn (main.py).
"""
import json
import re
from datetime import date, datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StringConstraints, model_validator
from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session

from .. import audit
from ..annex_v import (ANNEX_V_VERSION, CHECKLIST, CHECKLIST_BY_CODE, CHECKLIST_SOURCE, FORMS, INDEX_CRITERIA,
                       criterion_levels, validate_answers)
from ..database import get_db
from ..models import (AccessToken, AccessTokenPolicy, AnnexVAnswer, AnnexVExpertAssessment, AnnexVResponse,
                      ChecklistEntry, Cycle, CycleConfig, MaturityIndicator, hash_access_code)
from ..request_limits import BoundedId
from ..roles import ANALYTICS_ROLES, require_role
from ..services import maturity
from .analytics import demo_enabled
from .assessments import RespondentCategory, get_assessment, get_public_assessment

router = APIRouter(prefix="/api", tags=["Зрілість за Додатком В"])

ENTRY_ROLES = ("data_officer", "admin")               # вносять чек-лист і показники
CONFIRM_ROLES = ("admin",)                            # підтверджує інший користувач
READ_ROLES = tuple(dict.fromkeys(("admin", "data_officer", *ANALYTICS_ROLES)))
LABEL_MIN, LABEL_MAX = 3, 120
EVIDENCE_MAX = 1000
UNIT = "%"

QuestionId = Annotated[str, StringConstraints(min_length=1, max_length=40)]
OptionId = Annotated[str, StringConstraints(min_length=1, max_length=40)]
Answers = Annotated[dict[QuestionId, OptionId], Field(min_length=1, max_length=50)]
Criterion = Literal["leadership", "ethics", "education", "openness", "officer", "strategy",
                    "risks", "checks", "whistleblowers", "audit"]
assert set(Criterion.__args__) == set(INDEX_CRITERIA)          # той самий перелік, що в каталозі

_UPPER = "А-ЯІЇЄҐA-Z"
_INITIALS = re.compile(rf"[{_UPPER}]\.\s*[{_UPPER}]\.")
_NAME_WITH_PATRONYMIC = re.compile(
    rf"[{_UPPER}][а-яіїєґ'’]+\s+[{_UPPER}][а-яіїєґ'’]*(?:ович|евич|євич|івна|ївна|овна)\b")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat(timespec="seconds") + "Z"


def _same_author(entered_role: str, entered_uid: int | None, role: str, uid: int | None) -> bool:
    """Той самий користувач? Сесії V2 порівнюються за id; демо X-Role (без id) — за роллю."""
    if entered_uid is not None or uid is not None:
        return entered_uid == uid
    return entered_role == role


# ---------------------------------------------------------------------------
# 1. Анонімна анкета Додатка В (публічно, за одноразовим кодом)
# ---------------------------------------------------------------------------

class AnnexVSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str = Field(min_length=1, max_length=128, description="Одноразовий код доступу циклу")
    category: RespondentCategory
    form: Literal[1, 2]
    version: str = Field(min_length=1, max_length=20)
    answers: Answers


# Маршрут не читає cookie сесії і не приймає X-Role (наскрізна анонімність, як /submissions).
@router.post("/assessments/{assessment_id}/annex-v/responses", status_code=201)
def submit_annex_v(assessment_id: BoundedId, body: AnnexVSubmission, db: Session = Depends(get_db)):
    """
    Приймає анонімну анкету Додатка В. Код доступу — той самий одноразовий код циклу (видає
    data_officer), категорія коду має збігатися; після подання код використаний.
    201 {"status": "accepted"}; 409 — цикл не відкритий або код недійсний/використаний; 422 — некоректні дані.
    """
    cycle = get_public_assessment(assessment_id, db)       # чернетка — 404
    if cycle.status != "open":
        raise HTTPException(409, "Оцінювання закрите")
    config = db.get(CycleConfig, assessment_id)
    if config:
        if date.today() < cycle.start_date:
            raise HTTPException(409, "Строк оцінювання ще не розпочався")
        if config.end_date and date.today() > config.end_date:
            raise HTTPException(409, "Строк оцінювання завершився")
        if body.category not in json.loads(config.categories_json):
            raise HTTPException(422, "Категорія недоступна для цього циклу")
    if body.version != ANNEX_V_VERSION:
        raise HTTPException(422, f"Підтримується лише версія шаблонів {ANNEX_V_VERSION}")
    problem = validate_answers(body.form, body.answers)
    if problem:
        raise HTTPException(422, problem)

    # Атомарне погашення коду (як POST /submissions): існує, цей цикл, не використаний, категорія збігається.
    # Одне повідомлення для всіх випадків — щоб перебором не дізнатися, які коди існують.
    policy_ok = exists(select(AccessTokenPolicy.token_id).where(
        AccessTokenPolicy.token_id == AccessToken.id,
        AccessTokenPolicy.category == body.category,
        AccessTokenPolicy.expires_at > _now()))
    if not config:
        policy_ok = (~exists(select(AccessTokenPolicy.token_id).where(
            AccessTokenPolicy.token_id == AccessToken.id))) | policy_ok
    redeemed = db.execute(
        update(AccessToken)
        .where(AccessToken.token_hash == hash_access_code(body.access_token), AccessToken.cycle_id == assessment_id,
               AccessToken.used.is_(False),
               exists(select(Cycle.id).where(Cycle.id == assessment_id, Cycle.status == "open")),
               policy_ok)
        .values(used=True)
    ).rowcount
    if redeemed != 1:
        db.rollback()
        raise HTTPException(409, "Недійсний або вже використаний код доступу")

    response = AnnexVResponse(cycle_id=assessment_id, respondent_category=body.category,
                              form=body.form, version=body.version)
    response.answers = [AnnexVAnswer(question_id=q, option_id=o) for q, o in sorted(body.answers.items())]
    db.add(response)
    db.commit()            # код і анкета разом: або обидва, або нічого. Номер анкети не повертається.
    return {"status": "accepted"}


# ---------------------------------------------------------------------------
# 2. Експертна оцінка (форма 1, вносить admin)
# ---------------------------------------------------------------------------

class ExpertIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expert_label: str = Field(min_length=1, max_length=500, description="Посада або роль експерта, не ПІБ")
    form: Literal[1]
    version: str = Field(min_length=1, max_length=20)
    answers: Answers


def _clean_label(value: str) -> str:
    label = " ".join(value.split())
    if not LABEL_MIN <= len(label) <= LABEL_MAX:
        raise HTTPException(422, f"Експерт — посада або роль, від {LABEL_MIN} до {LABEL_MAX} символів")
    if ("@" in label or sum(ch.isdigit() for ch in label) >= 7
            or _INITIALS.search(label) or _NAME_WITH_PATRONYMIC.search(label)):
        raise HTTPException(422, "Вкажіть посаду або роль експерта, а не ПІБ чи контактні дані")
    return label


@router.post("/assessments/{assessment_id}/annex-v/expert", status_code=201)
def create_expert_assessment(assessment_id: BoundedId, body: ExpertIn, request: Request,
                             role: str = Depends(require_role("admin")), db: Session = Depends(get_db)):
    cycle = get_assessment(assessment_id, db)
    if cycle.status == "draft":
        raise HTTPException(409, "Експертну оцінку вносять для активного або закритого циклу")
    label = _clean_label(body.expert_label)
    if body.version != ANNEX_V_VERSION:
        raise HTTPException(422, f"Підтримується лише версія шаблонів {ANNEX_V_VERSION}")
    problem = validate_answers(body.form, body.answers)
    if problem:
        raise HTTPException(422, problem)
    uid = audit.actor_user_id(request)
    row = AnnexVExpertAssessment(cycle_id=assessment_id, expert_label=label, form=body.form, version=body.version,
                                 answers_json=json.dumps(dict(sorted(body.answers.items()))),
                                 entered_role=role, entered_by_user_id=uid, created_at=_now())
    db.add(row)
    audit.record(db, role, "annex_v.expert_create", assessment_id, actor_user_id=uid)
    db.commit()
    return {"id": row.id}


# ---------------------------------------------------------------------------
# 3. Чек-лист (Додаток Б, адаптовано)
# ---------------------------------------------------------------------------

def checklist_item(item: dict, entry: ChecklistEntry | None) -> dict:
    return {"code": item["code"], "criterion": item["criterion"], "text": item["text"],
            "source": CHECKLIST_SOURCE, "source_item": item["source_item"],
            "status": entry.status if entry else None,
            "evidence": entry.evidence if entry else None,
            "entered_role": entry.entered_role if entry else None,
            "entered_at": _iso(entry.entered_at) if entry else None,
            "confirmed": bool(entry and entry.confirmed),
            "confirmed_role": entry.confirmed_role if entry else None,
            "confirmed_at": _iso(entry.confirmed_at) if entry else None}


def _catalog_item(code: str) -> dict:
    item = CHECKLIST_BY_CODE.get(code)
    if item is None:
        raise HTTPException(404, "Пункт чек-листа не знайдено")
    return item


def _entry(db: Session, assessment_id: int, code: str) -> ChecklistEntry | None:
    return db.query(ChecklistEntry).filter_by(cycle_id=assessment_id, code=code).one_or_none()


@router.get("/assessments/{assessment_id}/checklist", dependencies=[Depends(require_role(*READ_ROLES))])
def read_checklist(assessment_id: BoundedId, db: Session = Depends(get_db)):
    get_assessment(assessment_id, db)
    entries = {e.code: e for e in db.query(ChecklistEntry).filter_by(cycle_id=assessment_id)}
    return {"items": [checklist_item(item, entries.get(item["code"])) for item in CHECKLIST]}


class ChecklistIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["yes", "partial", "no"]
    evidence: str | None = Field(default=None, max_length=EVIDENCE_MAX)


@router.put("/assessments/{assessment_id}/checklist/{code}")
def update_checklist(assessment_id: BoundedId, code: str, body: ChecklistIn, request: Request,
                     role: str = Depends(require_role(*ENTRY_ROLES)), db: Session = Depends(get_db)):
    """Вносить стан пункту; будь-яка зміна скидає підтвердження (confirmed=false)."""
    get_assessment(assessment_id, db)
    item = _catalog_item(code)
    evidence = " ".join((body.evidence or "").split()) or None
    uid = audit.actor_user_id(request)
    entry = _entry(db, assessment_id, code)
    if entry is None:
        entry = ChecklistEntry(cycle_id=assessment_id, code=code)
        db.add(entry)
    entry.status, entry.evidence = body.status, evidence
    entry.entered_role, entry.entered_by_user_id, entry.entered_at = role, uid, _now()
    entry.confirmed, entry.confirmed_role, entry.confirmed_by_user_id, entry.confirmed_at = False, None, None, None
    audit.record(db, role, "checklist.update", assessment_id, actor_user_id=uid)
    db.commit()
    return checklist_item(item, entry)


@router.post("/assessments/{assessment_id}/checklist/{code}/confirm")
def confirm_checklist(assessment_id: BoundedId, code: str, request: Request,
                      role: str = Depends(require_role(*CONFIRM_ROLES)), db: Session = Depends(get_db)):
    get_assessment(assessment_id, db)
    item = _catalog_item(code)
    entry = _entry(db, assessment_id, code)
    if entry is None:
        raise HTTPException(409, "Пункт ще не заповнено")
    if entry.confirmed:
        raise HTTPException(409, "Пункт уже підтверджено")
    uid = audit.actor_user_id(request)
    if _same_author(entry.entered_role, entry.entered_by_user_id, role, uid):
        raise HTTPException(409, "Підтверджує інший користувач, а не той, хто вніс запис")
    entry.confirmed, entry.confirmed_role, entry.confirmed_by_user_id, entry.confirmed_at = True, role, uid, _now()
    audit.record(db, role, "checklist.confirm", assessment_id, actor_user_id=uid)
    db.commit()
    return checklist_item(item, entry)


# ---------------------------------------------------------------------------
# 4. Об'єктивні показники критеріїв
# ---------------------------------------------------------------------------

def indicator_item(row: MaturityIndicator) -> dict:
    return {"id": row.id, "criterion": row.criterion, "name": row.name, "unit": UNIT,
            "value": row.value, "target": row.target, "period": row.period,
            "entered_role": row.entered_role, "entered_at": _iso(row.entered_at),
            "confirmed": row.confirmed, "confirmed_role": row.confirmed_role,
            "confirmed_at": _iso(row.confirmed_at)}


class IndicatorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion: Criterion
    name: str = Field(min_length=1, max_length=200)
    value: StrictInt | StrictFloat
    target: StrictInt | StrictFloat
    period: str = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def valid(self):
        if not 3 <= len(self.name.strip()) <= 200:
            raise ValueError("Назва показника — від 3 до 200 символів")
        if not self.period.strip():
            raise ValueError("Вкажіть період")
        for number in (self.value, self.target):
            if not 0 <= number <= 100:                  # NaN і нескінченність теж не проходять
                raise ValueError("Значення і ціль — відсотки від 0 до 100")
        return self


@router.get("/assessments/{assessment_id}/objective-indicators",
            dependencies=[Depends(require_role(*READ_ROLES))])
def read_indicators(assessment_id: BoundedId, db: Session = Depends(get_db)):
    get_assessment(assessment_id, db)
    rows = db.query(MaturityIndicator).filter_by(cycle_id=assessment_id).order_by(MaturityIndicator.id)
    return {"items": [indicator_item(row) for row in rows]}


@router.post("/assessments/{assessment_id}/objective-indicators", status_code=201)
def create_indicator(assessment_id: BoundedId, body: IndicatorIn, request: Request,
                     role: str = Depends(require_role(*ENTRY_ROLES)), db: Session = Depends(get_db)):
    get_assessment(assessment_id, db)
    uid = audit.actor_user_id(request)
    row = MaturityIndicator(cycle_id=assessment_id, criterion=body.criterion, name=" ".join(body.name.split()),
                            value=float(body.value), target=float(body.target), period=body.period.strip(),
                            entered_role=role, entered_by_user_id=uid, entered_at=_now(), confirmed=False)
    db.add(row)
    audit.record(db, role, "objective.create", assessment_id, actor_user_id=uid)
    db.commit()
    return indicator_item(row)


@router.post("/objective-indicators/{indicator_id}/confirm")
def confirm_indicator(indicator_id: BoundedId, request: Request,
                      role: str = Depends(require_role(*CONFIRM_ROLES)), db: Session = Depends(get_db)):
    row = db.get(MaturityIndicator, indicator_id)
    if row is None:
        raise HTTPException(404, "Показник не знайдено")
    if row.confirmed:
        raise HTTPException(409, "Показник уже підтверджено")
    uid = audit.actor_user_id(request)
    if _same_author(row.entered_role, row.entered_by_user_id, role, uid):
        raise HTTPException(409, "Підтверджує інший користувач, а не той, хто вніс показник")
    row.confirmed, row.confirmed_role, row.confirmed_by_user_id, row.confirmed_at = True, role, uid, _now()
    audit.record(db, role, "objective.confirm", row.cycle_id, actor_user_id=uid)
    db.commit()
    return indicator_item(row)


# ---------------------------------------------------------------------------
# 5. Розрахунок зрілості
# ---------------------------------------------------------------------------

def maturity_inputs(db: Session, assessment_id: int) -> tuple[list, list, list, list]:
    """Дані циклу для services/maturity.calculate. Окремі анкети з функції не виходять."""
    responses = []
    for row in db.query(AnnexVResponse).filter_by(cycle_id=assessment_id).order_by(AnnexVResponse.id):
        answers = {a.question_id: a.option_id for a in row.answers}
        if row.version != ANNEX_V_VERSION or row.form not in FORMS or validate_answers(row.form, answers):
            continue                                 # анкета іншої версії каталогу не змішується з 2.0.0
        responses.append((row.respondent_category, criterion_levels(row.form, answers)))
    experts = []
    for row in db.query(AnnexVExpertAssessment).filter_by(cycle_id=assessment_id).order_by(AnnexVExpertAssessment.id):
        answers = json.loads(row.answers_json)
        if row.version == ANNEX_V_VERSION and row.form in FORMS and not validate_answers(row.form, answers):
            experts.append(criterion_levels(row.form, answers))
    checklist = [{"code": e.code, "status": e.status, "confirmed": e.confirmed}
                 for e in db.query(ChecklistEntry).filter_by(cycle_id=assessment_id)]
    indicators = [{"criterion": r.criterion, "name": r.name, "value": r.value, "target": r.target,
                   "confirmed": r.confirmed}
                  for r in db.query(MaturityIndicator).filter_by(cycle_id=assessment_id).order_by(MaturityIndicator.id)]
    return responses, experts, checklist, indicators


@router.get("/assessments/{assessment_id}/maturity",
            dependencies=[Depends(require_role(*ANALYTICS_ROLES)), Depends(demo_enabled)])
def read_maturity(assessment_id: BoundedId, db: Session = Depends(get_db)):
    """Зрілість за Додатком В для ЗАКРИТОГО циклу (до закриття — 409, як /results)."""
    cycle = get_assessment(assessment_id, db)
    if cycle.status != "closed":
        raise HTTPException(409, "Зрілість доступна після закриття оцінювання")
    responses, experts, checklist, indicators = maturity_inputs(db, assessment_id)
    return maturity.calculate({"id": cycle.id, "name": cycle.name, "status": cycle.status},
                              cycle.min_group_size, responses, experts, checklist, indicators)
