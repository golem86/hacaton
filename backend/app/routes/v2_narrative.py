"""
Чернетки текстів звіту локальною LM (app/services/narrative.py). Підключається до роутера /v2/admin
у routes/v2_admin.py. Усі маршрути — require_v2_role("admin"): сесія з 2FA, точна роль, для POST — CSRF.

  POST /v2/admin/reports/compare/narrative          {"base_assessment_id","target_assessment_id"} → 202
  POST /v2/admin/reports/{assessment_id}/narrative  {"kind": "summary"|"recommendations"}         → 202
       202 {"job_id", "status": "queued"}; 404 — циклу немає; 409 — цикл не закритий;
       422 — некоректне тіло або id; 429 — черга заповнена; 503 — LM не налаштована (V2_LM_URL)
  GET  /v2/admin/lm/jobs/{job_id}   → {status, kind, assessment_ids, text?, verified?, unverified_numbers?,
                                       error?, created_at, finished_at?}; 404 — немає, сплив TTL або чуже
  GET  /v2/admin/lm/status          → {enabled, reachable, model}

Маршрут compare оголошено раніше за /{assessment_id}/narrative, щоб «compare» не потрапляв у параметр id.
Чернетки ніде не зберігаються (зокрема в трекер); у журнал іде лише report.narrative з count.
"""
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .. import audit, settings
from ..database import get_db
from ..request_limits import MAX_ID, BoundedId
from ..services import narrative
from .v2_auth import require_v2_role

router = APIRouter(tags=["Dashboard V2 Admin — Local LM"])
admin = require_v2_role("admin")
BodyId = Annotated[int, Field(ge=1, le=MAX_ID)]
JobId = Annotated[str, Path(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


class NarrativeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["summary", "recommendations"]


class CompareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_assessment_id: BodyId
    target_assessment_id: BodyId


def _require_enabled() -> None:
    if settings.lm_url() is None:
        raise HTTPException(status_code=503, detail=narrative.LM_NOT_CONFIGURED)


def _enqueue(db: Session, request: Request, actor: dict[str, Any], kind: str,
             assessment_ids: list[int], facts: dict) -> dict[str, Any]:
    try:
        job = narrative.JOBS.submit(kind, assessment_ids, facts, owner_id=int(actor["id"]))
    except narrative.QueueFull:
        raise HTTPException(status_code=429, detail="Черга генерації заповнена. Спробуйте пізніше.") from None
    audit.record(db, "admin", "report.narrative", assessment_ids[-1],
                 actor_user_id=audit.actor_user_id(request) or int(actor["id"]), count=len(assessment_ids))
    db.commit()
    return {"job_id": job["job_id"], "status": job["status"]}


@router.post("/reports/compare/narrative", status_code=202)
def compare_narrative(body: CompareBody, request: Request, response: Response,
                      actor: dict[str, Any] = Depends(admin), db: Session = Depends(get_db)):
    _require_enabled()
    if body.base_assessment_id == body.target_assessment_id:
        raise HTTPException(status_code=422, detail="Оберіть два різні цикли")
    facts = narrative.collect_facts(db, "compare", body.target_assessment_id, body.base_assessment_id)
    response.headers["Cache-Control"] = "no-store"
    return _enqueue(db, request, actor, "compare", [body.base_assessment_id, body.target_assessment_id], facts)


@router.post("/reports/{assessment_id}/narrative", status_code=202)
def cycle_narrative(assessment_id: BoundedId, body: NarrativeBody, request: Request, response: Response,
                    actor: dict[str, Any] = Depends(admin), db: Session = Depends(get_db)):
    _require_enabled()
    facts = narrative.collect_facts(db, body.kind, assessment_id)
    response.headers["Cache-Control"] = "no-store"
    return _enqueue(db, request, actor, body.kind, [assessment_id], facts)


@router.get("/lm/jobs/{job_id}")
def lm_job(job_id: JobId, response: Response, actor: dict[str, Any] = Depends(admin)):
    job = narrative.JOBS.get(job_id, owner_id=int(actor["id"]))
    if job is None:
        raise HTTPException(status_code=404, detail="Завдання не знайдено")
    response.headers["Cache-Control"] = "no-store"
    return job


@router.get("/lm/status")
def lm_status(response: Response, _: dict[str, Any] = Depends(admin)):
    response.headers["Cache-Control"] = "no-store"
    return narrative.lm_status()
