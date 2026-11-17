from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..v2_auth import complete_attempt, create_attempt, get_attempt, list_attempts
from ..v2_catalog import PERSONAL_ASSESSMENTS, PERSONAL_QUESTIONS, get_personal_assessment, is_open, public_assessment
from .v2_auth import require_role

router = APIRouter(prefix="/v2/user", tags=["Dashboard V2 User"])


class AttemptBody(BaseModel):
    id: str | None = Field(default=None, min_length=1, max_length=100)
    assessment_id: str = Field(default="legacy", min_length=1, max_length=100)
    assessment_name: str | None = Field(default=None, max_length=200)
    status: Literal["draft", "completed"] = "draft"
    answers: dict[str, int] = Field(default_factory=dict)
    started_at: str | None = None
    completed_at: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_answers(answers: dict[str, int], require_complete: bool = False) -> None:
    allowed = {question["id"] for question in PERSONAL_QUESTIONS}
    if set(answers) - allowed:
        raise HTTPException(status_code=422, detail="Містить невідоме питання")
    if any(not isinstance(value, int) or value < 1 or value > 5 for value in answers.values()):
        raise HTTPException(status_code=422, detail="Відповіді мають бути числами від 1 до 5")
    if require_complete and set(answers) != allowed:
        raise HTTPException(status_code=422, detail="Потрібно відповісти на всі питання")


def _assessment_or_legacy(assessment_id: str, assessment_name: str | None) -> tuple[str, str, dict[str, Any] | None]:
    assessment = get_personal_assessment(assessment_id)
    if assessment:
        return assessment["id"], assessment["name"], assessment
    if assessment_id == "legacy" and assessment_name:
        return assessment_id, assessment_name, None
    raise HTTPException(status_code=404, detail="Тестування не знайдено")


def _public_attempt(row: dict[str, Any]) -> dict[str, Any]:
    result = {**row}
    result["answers"] = json.loads(result.pop("answers_json"))
    return result


@router.get("/profile")
def profile(user: dict[str, Any] = Depends(require_role("user"))):
    return user


@router.get("/assessments")
def available_assessments(_: dict[str, Any] = Depends(require_role("user"))):
    return [public_assessment(assessment) for assessment in PERSONAL_ASSESSMENTS]


@router.get("/assessments/{assessment_id}")
def available_assessment(assessment_id: str, _: dict[str, Any] = Depends(require_role("user"))):
    assessment = get_personal_assessment(assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail="Тестування не знайдено")
    return public_assessment(assessment)


@router.get("/attempts")
def attempts(user: dict[str, Any] = Depends(require_role("user"))):
    return [_public_attempt(row) for row in list_attempts(user["id"])]


@router.get("/attempts/{attempt_id}")
def attempt(attempt_id: str, user: dict[str, Any] = Depends(require_role("user"))):
    row = get_attempt(user["id"], attempt_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Спробу не знайдено")
    return _public_attempt(row)


@router.post("/attempts", status_code=201)
def save_attempt(body: AttemptBody, user: dict[str, Any] = Depends(require_role("user"))):
    _validate_answers(body.answers, require_complete=body.status == "completed")
    assessment_id, assessment_name, assessment = _assessment_or_legacy(body.assessment_id, body.assessment_name)
    if assessment and not is_open(assessment):
        raise HTTPException(status_code=409, detail="Період тестування завершено або ще не розпочався")
    attempt_id = body.id or f"attempt-{uuid4().hex}"
    try:
        create_attempt(
            user["id"],
            attempt_id,
            assessment_name,
            body.status,
            json.dumps(body.answers, separators=(",", ":")),
            body.started_at or _now(),
            body.completed_at if body.status == "completed" else None,
            assessment_id,
        )
    except PermissionError as error:
        raise HTTPException(status_code=404, detail="Спробу не знайдено") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    row = get_attempt(user["id"], attempt_id)
    assert row is not None
    return _public_attempt(row)


@router.patch("/attempts/{attempt_id}")
def save_draft(attempt_id: str, body: AttemptBody, user: dict[str, Any] = Depends(require_role("user"))):
    existing = get_attempt(user["id"], attempt_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Спробу не знайдено")
    if existing["status"] == "completed":
        raise HTTPException(status_code=409, detail="Завершену спробу не можна змінити")
    _validate_answers(body.answers)
    assessment_id = body.assessment_id if body.assessment_id != "legacy" else existing.get("assessment_id", "legacy")
    assessment_id, assessment_name, assessment = _assessment_or_legacy(assessment_id, body.assessment_name or existing["assessment_name"])
    if assessment and not is_open(assessment):
        raise HTTPException(status_code=409, detail="Період тестування завершено або ще не розпочався")
    try:
        create_attempt(user["id"], attempt_id, assessment_name, "draft", json.dumps(body.answers, separators=(",", ":")), existing["started_at"], None, assessment_id)
    except (PermissionError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    row = get_attempt(user["id"], attempt_id)
    assert row is not None
    return _public_attempt(row)


@router.post("/attempts/{attempt_id}/complete")
def finish_attempt(attempt_id: str, body: AttemptBody | None = None, user: dict[str, Any] = Depends(require_role("user"))):
    existing = get_attempt(user["id"], attempt_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Спробу не знайдено")
    if existing["status"] == "completed":
        raise HTTPException(status_code=409, detail="Тестування вже завершено")
    answers = body.answers if body is not None else json.loads(existing["answers_json"])
    _validate_answers(answers, require_complete=True)
    assessment = get_personal_assessment(existing.get("assessment_id", "legacy"))
    if assessment and not is_open(assessment):
        raise HTTPException(status_code=409, detail="Період тестування завершено або ще не розпочався")
    try:
        return _public_attempt(complete_attempt(
            user["id"],
            attempt_id,
            (body.completed_at if body else None) or _now(),
            json.dumps(answers, separators=(",", ":")),
        ))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/history")
def history(user: dict[str, Any] = Depends(require_role("user"))):
    return [_public_attempt(row) for row in list_attempts(user["id"]) if row["status"] == "completed"]


@router.get("/results")
def personal_results(user: dict[str, Any] = Depends(require_role("user"))):
    completed = [_public_attempt(row) for row in list_attempts(user["id"]) if row["status"] == "completed"]
    return {"completed": completed, "methodology": None, "official_index": None}


@router.get("/stats")
def personal_stats(user: dict[str, Any] = Depends(require_role("user"))):
    completed = [_public_attempt(row) for row in list_attempts(user["id"]) if row["status"] == "completed"]
    values = [value for attempt in completed for value in attempt["answers"].values()]
    return {
        "completed_tests": len(completed),
        "responses_total": len(values),
        "average_response": (sum(values) / len(values)) if values else None,
        "official_index": None,
    }
