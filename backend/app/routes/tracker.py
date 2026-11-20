"""
Recommendations Tracker: рішення посадової особи щодо рекомендацій і контроль виконання.

Маршрути:
  GET  /api/assessments/{assessment_id}/tracker            — рішення і заходи циклу;
  POST /api/assessments/{assessment_id}/tracker/decisions  — прийняти або відхилити пропозицію;
  POST /api/tracker/{action_id}/transition                 — змінити статус прийнятого заходу.

Правила:
  - пропозиції не зберігаються: сервер щоразу заново формує їх для закритого циклу
    (services/recommendations.py) і шукає recommendation_id серед них. Текст, правило й
    компонент беруться лише з серверної пропозиції, ніколи з тіла запиту;
  - рішення ухвалює людина: зміни робить лише сесія admin (require_role перевіряє сесію
    з 2FA і CSRF). Система нічого не приймає сама. Кожна зміна записується в Audit Trail
    у тій самій транзакції;
  - переходи статусів задає доменний автомат services/tracker.py:
    proposed → accepted | rejected; accepted → in_progress; in_progress → completed;
    completed → verified | in_progress;
  - прийняття вимагає відповідального (посада чи підрозділ, не ПІБ) і строку (не раніше
    за сьогодні). Статуси «виконано» і «перевірено» вимагають посилань на докази;
  - «перевірено» посилається на ПІЗНІШЕ закрите оцінювання (дата початку після циклу заходу)
    з тією самою версією анкети: результат перевіряє наступне оцінювання;
  - персональних даних немає: в історії роль, а не ім'я; у журналі лише дія, роль і цикл.
"""
import json
import re
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..models import Cycle, CycleConfig, RecommendationAction
from ..roles import ANALYTICS_ROLES, require_role
from ..services.recommendations import generate_recommendations
from ..services.tracker import TRANSITIONS, is_overdue, transition
from .analytics import demo_enabled, results
from .assessments import DEMO_VERSION, get_assessment

router = APIRouter(prefix="/api", tags=["Трекер рекомендацій"])

OWNER_MIN, OWNER_MAX = 3, 120
REASON_MAX = 1000
EVIDENCE_MAX_ITEMS, EVIDENCE_MAX = 10, 200
MAX_DUE_DAYS = 5 * 366
STATUS_LABELS = {"proposed": "запропоновано", "accepted": "прийнято", "rejected": "відхилено",
                 "in_progress": "в роботі", "completed": "виконано", "verified": "перевірено"}

# Ознаки ПІБ і контактів у полі «відповідальний»: ініціали («І. І.»), ім'я з по батькові
# («Іван Іванович»), email. Це запобіжник, а не гарантія; інтерфейс пояснює правило.
_UPPER = "А-ЯІЇЄҐA-Z"
_INITIALS = re.compile(rf"[{_UPPER}]\.\s*[{_UPPER}]\.")
_NAME_WITH_PATRONYMIC = re.compile(
    rf"[{_UPPER}][а-яіїєґ'’]+\s+[{_UPPER}][а-яіїєґ'’]*(?:ович|евич|євич|івна|ївна|овна)\b")

_DOMAIN_ERRORS = {
    "A decision reason is required": "Вкажіть обґрунтування рішення",
    "Acceptance requires owner_id and due_date": "Для прийняття вкажіть відповідального і строк",
    "Due date precedes acceptance": "Строк не може бути раніше за дату рішення",
    "Assign owner and deadline when accepting": "Відповідального і строк призначають лише під час прийняття",
    "Completion/verification requires evidence references":
        "Для статусів «виконано» і «перевірено» додайте посилання на докази",
    "Verification requires a different assessment ID": "Результат перевіряє інше, пізніше оцінювання",
    "History cannot go backwards": "Дата зміни не може передувати попередній зміні",
}


class DecisionIn(BaseModel):
    """Рішення посадової особи. Текст пропозиції не приймається: його бере сервер."""
    model_config = ConfigDict(extra="forbid")

    recommendation_id: str = Field(min_length=1, max_length=64, pattern=r"^[0-9a-f]+$")
    decision: Literal["accepted", "rejected"]
    owner: str | None = Field(default=None, max_length=500,
                              description="Посада або підрозділ (3–120 символів), не ПІБ")
    due_date: str | None = Field(default=None, max_length=10, description="РРРР-ММ-ДД, не раніше за сьогодні")
    reason: str = Field(min_length=1, max_length=REASON_MAX)


class TransitionIn(BaseModel):
    """Зміна статусу прийнятого заходу за автоматом services/tracker.py."""
    model_config = ConfigDict(extra="forbid")

    status: Literal["in_progress", "completed", "verified"]
    reason: str = Field(min_length=1, max_length=REASON_MAX)
    evidence_refs: list[str] = Field(default_factory=list, max_length=EVIDENCE_MAX_ITEMS)
    verified_in_assessment_id: StrictInt | None = Field(default=None, ge=1)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds") + "Z"


def _clean_reason(value: str) -> str:
    reason = value.strip()
    if not reason:
        raise HTTPException(422, "Вкажіть обґрунтування рішення")
    return reason


def _clean_owner(value: str | None) -> str:
    owner = " ".join((value or "").split())
    if not OWNER_MIN <= len(owner) <= OWNER_MAX:
        raise HTTPException(422, f"Відповідальний — посада або підрозділ, від {OWNER_MIN} до {OWNER_MAX} символів")
    if ("@" in owner or sum(ch.isdigit() for ch in owner) >= 7
            or _INITIALS.search(owner) or _NAME_WITH_PATRONYMIC.search(owner)):
        raise HTTPException(422, "Вкажіть посаду або підрозділ, а не ПІБ чи контактні дані")
    return owner


def _clean_due_date(value: str | None, today: date) -> str:
    if value is None:
        raise HTTPException(422, "Для прийняття вкажіть строк виконання")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        parsed = None
    if parsed is None or parsed.isoformat() != value:
        raise HTTPException(422, "Строк має формат РРРР-ММ-ДД")
    if parsed < today:
        raise HTTPException(422, "Строк не може бути раніше за сьогодні")
    if (parsed - today).days > MAX_DUE_DAYS:
        raise HTTPException(422, "Строк не може бути далі ніж за 5 років")
    return value


def _clean_evidence(items: list[str]) -> list[str]:
    cleaned: list[str] = []
    for item in items:
        ref = " ".join(item.split())
        if not ref or len(ref) > EVIDENCE_MAX:
            raise HTTPException(422, f"Посилання на доказ — від 1 до {EVIDENCE_MAX} символів")
        if ref not in cleaned:
            cleaned.append(ref)
    return cleaned


def _domain_error(exc: ValueError) -> HTTPException:
    return HTTPException(422, _DOMAIN_ERRORS.get(str(exc), "Дані рішення не пройшли перевірку"))


def _questionnaire_version(db: Session, cycle_id: int) -> str:
    config = db.get(CycleConfig, cycle_id)
    return config.questionnaire_version if config else DEMO_VERSION


def _check_verifying_assessment(db: Session, source_id: int, target_id: int | None) -> None:
    """Результат перевіряє наступне оцінювання: пізніше за датою, закрите, з тією самою анкетою."""
    if target_id is None:
        raise HTTPException(422, "Для перевірки оберіть пізніше закрите оцінювання")
    source = db.get(Cycle, source_id)
    target = db.get(Cycle, target_id)
    if (target is None or source is None or target.id == source.id or target.status != "closed"
            or target.start_date <= source.start_date):
        raise HTTPException(422, "Результат перевіряє пізніше закрите оцінювання (дата початку після циклу заходу)")
    if _questionnaire_version(db, target.id) != _questionnaire_version(db, source.id):
        raise HTTPException(422, "Оцінювання для перевірки має ту саму версію анкети, що й цикл заходу")


def _history_entry(step: dict, at: datetime) -> dict:
    """Запис історії з результату доменного переходу: роль замість імені, без персональних даних."""
    entry = {"from_status": step["from_status"], "to_status": step["to_status"],
             "on_date": step["on_date"], "at": _iso(at), "actor_role": step["actor_id"],
             "reason": step["reason"], "evidence_refs": list(step["evidence_refs"])}
    if step["to_status"] == "accepted":
        entry.update(owner=step["owner_id"], due_date=step["due_date"])
    if step["to_status"] == "verified":
        entry["verified_in_assessment_id"] = int(step["next_assessment_id"])
    return entry


def _action_dict(row: RecommendationAction, today: date) -> dict:
    due = row.due_date.isoformat() if row.due_date else None
    return {
        "id": row.id, "assessment_id": row.assessment_id, "recommendation_id": row.recommendation_id,
        "rule_id": row.rule_id, "component_code": row.component_code, "text": row.text,
        "methodology_version": row.methodology_version, "status": row.status,
        "owner": row.owner, "due_date": due, "decision_reason": row.decision_reason,
        "evidence_refs": json.loads(row.evidence_refs_json),
        "verified_in_assessment_id": row.verified_in_assessment_id,
        # Похідна ознака, не статус: строк минув, а захід ще не виконано (день строку — не прострочення)
        "overdue": is_overdue({"status": row.status, "due_date": due}, as_of=today.isoformat()),
        "allowed_transitions": sorted(TRANSITIONS.get(row.status, set())),
        "history": json.loads(row.history_json),
        "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at),
    }


def _summary(actions: list[dict]) -> dict:
    def count(status: str) -> int:
        return sum(action["status"] == status for action in actions)
    return {"accepted_total": sum(action["status"] != "rejected" for action in actions),
            "accepted": count("accepted"), "in_progress": count("in_progress"),
            "completed": count("completed"), "verified": count("verified"),
            "rejected": count("rejected"), "overdue": sum(action["overdue"] for action in actions)}


@router.get("/assessments/{assessment_id}/tracker", dependencies=[Depends(require_role(*ANALYTICS_ROLES))])
def read_tracker(assessment_id: int, db: Session = Depends(get_db)):
    """Рішення і заходи циклу; «прострочено» — похідна ознака на дату `as_of`, а не статус."""
    cycle = get_assessment(assessment_id, db)
    today = date.today()
    rows = (db.query(RecommendationAction).filter_by(assessment_id=assessment_id)
            .order_by(RecommendationAction.id).all())
    actions = [_action_dict(row, today) for row in rows]
    return {"assessment": {"id": cycle.id, "name": cycle.name, "status": cycle.status},
            "as_of": today.isoformat(), "actions": actions, "summary": _summary(actions)}


@router.post("/assessments/{assessment_id}/tracker/decisions", status_code=201)
def decide_recommendation(assessment_id: int, body: DecisionIn,
                          role: str = Depends(require_role("admin")),
                          _demo: None = Depends(demo_enabled),
                          db: Session = Depends(get_db)):
    """
    Посадова особа приймає або відхиляє пропозицію закритого циклу. Сервер заново формує
    пропозиції й шукає серед них recommendation_id (404, якщо немає). Одне рішення на
    пропозицію в циклі (409). Прийняття — з відповідальним і строком; рішення — з обґрунтуванням (422).
    """
    report = generate_recommendations(results(assessment_id, db))
    proposal = next((p for p in report["proposals"] if p["id"] == body.recommendation_id), None)
    if proposal is None:
        raise HTTPException(404, "Пропозицію не знайдено серед рекомендацій цього циклу")
    if db.query(RecommendationAction).filter_by(assessment_id=assessment_id,
                                                recommendation_id=proposal["id"]).first() is not None:
        raise HTTPException(409, "Рішення щодо цієї пропозиції вже ухвалено")

    today = date.today()
    reason = _clean_reason(body.reason)
    owner = due = None
    if body.decision == "accepted":
        owner = _clean_owner(body.owner)
        due = _clean_due_date(body.due_date, today)
    elif body.owner is not None or body.due_date is not None:
        raise HTTPException(422, "Відповідального і строк призначають лише під час прийняття")
    try:
        decided = transition(proposal, body.decision, actor_id=role, human_decision=True,
                             on_date=today.isoformat(), reason=reason, owner_id=owner, due_date=due)
    except ValueError as exc:
        raise _domain_error(exc) from exc

    now = _now()
    row = RecommendationAction(
        assessment_id=assessment_id, recommendation_id=proposal["id"], rule_id=proposal["rule_id"],
        component_code=proposal["component_code"], text=proposal["text"],
        methodology_version=report["methodology_version"], status=decided["status"],
        owner=owner, due_date=date.fromisoformat(due) if due else None, decision_reason=reason,
        evidence_refs_json="[]",
        history_json=json.dumps([_history_entry(decided["history"][-1], now)], ensure_ascii=False),
        created_at=now, updated_at=now)
    db.add(row)
    audit.record(db, role, f"tracker.{decided['status']}", assessment_id)
    try:
        db.commit()
    except IntegrityError as exc:          # паралельне рішення щодо тієї самої пропозиції
        db.rollback()
        raise HTTPException(409, "Рішення щодо цієї пропозиції вже ухвалено") from exc
    return _action_dict(row, today)


@router.post("/tracker/{action_id}/transition")
def transition_action(action_id: int, body: TransitionIn,
                      role: str = Depends(require_role("admin")), db: Session = Depends(get_db)):
    """
    Змінює статус прийнятого заходу: недозволений перехід — 409; без обґрунтування, без доказів
    для «виконано»/«перевірено» чи без пізнішого закритого оцінювання для «перевірено» — 422.
    """
    row = db.get(RecommendationAction, action_id)
    if row is None:
        raise HTTPException(404, "Захід не знайдено")
    if body.status not in TRANSITIONS.get(row.status, set()):
        raise HTTPException(409, f"Перехід «{STATUS_LABELS.get(row.status, row.status)}» → "
                                 f"«{STATUS_LABELS[body.status]}» не дозволено")
    today = date.today()
    reason = _clean_reason(body.reason)
    evidence = _clean_evidence(body.evidence_refs)
    next_assessment_id = None
    if body.status == "verified":
        _check_verifying_assessment(db, row.assessment_id, body.verified_in_assessment_id)
        next_assessment_id = str(body.verified_in_assessment_id)
    elif body.verified_in_assessment_id is not None:
        raise HTTPException(422, "Оцінювання для перевірки вказують лише для статусу «перевірено»")

    history = json.loads(row.history_json)
    current = {"assessment_id": row.assessment_id, "status": row.status, "owner_id": row.owner,
               "due_date": row.due_date.isoformat() if row.due_date else None, "history": history}
    try:
        updated = transition(current, body.status, actor_id=role, human_decision=True,
                             on_date=today.isoformat(), reason=reason, evidence_refs=tuple(evidence),
                             next_assessment_id=next_assessment_id)
    except ValueError as exc:
        raise _domain_error(exc) from exc

    now = _now()
    history.append(_history_entry(updated["history"][-1], now))
    refs = json.loads(row.evidence_refs_json)
    refs += [ref for ref in evidence if ref not in refs]
    values = {"status": updated["status"], "updated_at": now,
              "history_json": json.dumps(history, ensure_ascii=False),
              "evidence_refs_json": json.dumps(refs, ensure_ascii=False)}
    if body.status == "verified":
        values["verified_in_assessment_id"] = body.verified_in_assessment_id
    # Умовне оновлення: паралельна зміна того самого заходу не перезапише цю (як погашення коду доступу)
    changed = db.execute(
        update(RecommendationAction)
        .where(RecommendationAction.id == row.id, RecommendationAction.status == row.status,
               RecommendationAction.updated_at == row.updated_at)
        .values(**values)).rowcount
    if changed != 1:
        db.rollback()
        raise HTTPException(409, "Захід щойно змінено іншим запитом. Оновіть дані й повторіть дію")
    audit.record(db, role, f"tracker.{body.status}", row.assessment_id)
    db.commit()
    return _action_dict(db.get(RecommendationAction, action_id), today)
