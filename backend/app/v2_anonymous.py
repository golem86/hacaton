"""Окреме локальне сховище для анонімних відповідей V2."""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ANONYMOUS_DB_PATH = Path(os.environ.get("V2_ANONYMOUS_DB", Path(__file__).resolve().parent.parent / "v2-anonymous-local.db"))


def _connect() -> sqlite3.Connection:
    ANONYMOUS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(ANONYMOUS_DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def init_anonymous_db() -> None:
    with _connect() as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS v2_anonymous_submissions (
                submission_id TEXT PRIMARY KEY,
                survey_id TEXT NOT NULL,
                answers_json TEXT NOT NULL,
                submitted_at TEXT NOT NULL
            )"""
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_v2_anonymous_survey ON v2_anonymous_submissions(survey_id)")


def create_submission(survey_id: str, answers: dict[str, int], submission_id: str | None = None) -> str:
    submission_id = submission_id or secrets.token_urlsafe(18)
    with _connect() as db:
        try:
            db.execute(
                "INSERT INTO v2_anonymous_submissions(submission_id, survey_id, answers_json, submitted_at) VALUES (?, ?, ?, ?)",
                (submission_id, survey_id, json.dumps(answers, separators=(",", ":")), datetime.now(timezone.utc).isoformat()),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("Цю анонімну спробу вже відправлено") from error
    return submission_id


def aggregate_submissions(survey_id: str, question_ids: list[str], min_group_size: int) -> dict[str, Any]:
    with _connect() as db:
        rows = db.execute("SELECT answers_json FROM v2_anonymous_submissions WHERE survey_id = ?", (survey_id,)).fetchall()
    total = len(rows)
    hidden = total < min_group_size
    by_question: dict[str, dict[str, Any]] = {}
    for question_id in question_ids:
        values = [json.loads(row["answers_json"]).get(question_id) for row in rows]
        values = [value for value in values if isinstance(value, int)]
        by_question[question_id] = {
            "score": None if hidden or not values else sum(values) / len(values),
            "hidden": hidden,
        }
    return {"survey_id": survey_id, "responses_total": None if hidden else total, "min_group_size": min_group_size, "questions": by_question}
