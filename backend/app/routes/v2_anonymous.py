from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..v2_anonymous import aggregate_submissions, create_submission, init_anonymous_db
from ..v2_catalog import get_anonymous_survey
from .v2_auth import require_role

router = APIRouter(prefix="/v2/anonymous", tags=["Dashboard V2 Anonymous"])
init_anonymous_db()


class AnonymousResponseBody(BaseModel):
    submission_id: str | None = Field(default=None, min_length=8, max_length=100)
    answers: dict[str, int]


def _survey_or_404(survey_id: str) -> dict[str, Any]:
    survey = get_anonymous_survey(survey_id)
    if survey is None:
        raise HTTPException(status_code=404, detail="Анонімне опитування не знайдено")
    return survey


@router.get("/assessments")
def anonymous_assessments():
    return [{"id": survey["id"], "name": survey["name"], "questions": survey["questions"], "status": "open"} for survey in [_survey_or_404("anonymous-integrity-2026")]]


@router.get("/assessments/{survey_id}")
def anonymous_assessment(survey_id: str):
    survey = _survey_or_404(survey_id)
    return {"id": survey["id"], "name": survey["name"], "questions": survey["questions"], "status": "open"}


@router.post("/assessments/{survey_id}/responses", status_code=201)
def submit_anonymous(survey_id: str, body: AnonymousResponseBody):
    survey = _survey_or_404(survey_id)
    question_ids = {question["id"] for question in survey["questions"]}
    if set(body.answers) != question_ids:
        raise HTTPException(status_code=422, detail="Потрібно відповісти на всі анонімні питання")
    if any(not isinstance(value, int) or value < 1 or value > 5 for value in body.answers.values()):
        raise HTTPException(status_code=422, detail="Відповіді мають бути числами від 1 до 5")
    try:
        submission_id = create_submission(survey_id, body.answers, body.submission_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"status": "submitted", "submission_id": submission_id}


@router.get("/assessments/{survey_id}/results")
def anonymous_results(survey_id: str, _: dict[str, Any] = Depends(require_role("admin"))):
    survey = _survey_or_404(survey_id)
    min_group_size = max(2, int(os.environ.get("V2_ANONYMOUS_MIN_GROUP_SIZE", "5")))
    return aggregate_submissions(survey_id, [question["id"] for question in survey["questions"]], min_group_size)
