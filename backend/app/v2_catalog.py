"""Локальний каталог V2-тестувань.

Каталог ізольований від командних /api-контрактів і містить лише синтетичні
питання для локального прототипу. У production він має надходити з погодженого
версіонованого Survey API.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

PERSONAL_QUESTIONS: list[dict[str, str]] = [
    {"id": "q1", "component": "C1", "prompt": "Я розумію, як у підрозділі приймаються доброчесні рішення.", "hint": "Організаційні орієнтири"},
    {"id": "q2", "component": "C2", "prompt": "Керівники послідовно демонструють нульову толерантність до зловживань.", "hint": "Лідерство та приклад"},
    {"id": "q3", "component": "C3", "prompt": "Я знаю, куди безпечно повідомити про потенційне порушення.", "hint": "Канали повідомлень"},
    {"id": "q4", "component": "C4", "prompt": "Рішення щодо ризиків пояснюються прозоро та своєчасно.", "hint": "Прозорість"},
    {"id": "q5", "component": "C5", "prompt": "Навчання допомагає мені діяти відповідно до політик доброчесності.", "hint": "Компетентності"},
    {"id": "q6", "component": "C6", "prompt": "Контрольні процедури вбудовані у щоденну роботу.", "hint": "Контроль і моніторинг"},
    {"id": "q7", "component": "C7", "prompt": "Після оцінювання команда має зрозумілий план покращень.", "hint": "Покращення"},
]

PERSONAL_ASSESSMENTS: list[dict[str, Any]] = [
    {
        "id": "personal-2026-q4",
        "name": "Особисте самооцінювання · Q4 2026",
        "duration": "7 питань · близько 5 хв",
        "opens_at": "2026-11-17T00:00:00+00:00",
        "closes_at": "2026-11-24T23:59:59+00:00",
    },
    {
        "id": "personal-2027-q1",
        "name": "Особисте самооцінювання · Q1 2027",
        "duration": "Підготовка · доступне з 2027-01-01",
        "opens_at": "2027-01-01T00:00:00+00:00",
        "closes_at": "2027-01-08T23:59:59+00:00",
    },
]

ANONYMOUS_SURVEYS: list[dict[str, Any]] = [
    {
        "id": "anonymous-integrity-2026",
        "name": "Анонімне опитування доброчесності",
        "questions": [
            {"id": "a1", "prompt": "Наскільки зрозумілими є правила доброчесності у вашій організації?"},
            {"id": "a2", "prompt": "Наскільки безпечно повідомляти про потенційні порушення?"},
            {"id": "a3", "prompt": "Наскільки послідовно керівництво реагує на ризики?"},
        ],
    },
]


def get_personal_assessment(assessment_id: str) -> dict[str, Any] | None:
    for assessment in PERSONAL_ASSESSMENTS:
        if assessment["id"] == assessment_id:
            return assessment
    return None


def is_open(assessment: dict[str, Any], now: datetime | None = None) -> bool:
    configured_now = os.environ.get("V2_CATALOG_NOW")
    current = now or (datetime.fromisoformat(configured_now) if configured_now else datetime.now(timezone.utc))
    start = datetime.fromisoformat(assessment["opens_at"])
    end = datetime.fromisoformat(assessment["closes_at"])
    return start <= current <= end


def public_assessment(assessment: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    return {
        **assessment,
        "status": "open" if is_open(assessment, now) else "unavailable",
        "questions": PERSONAL_QUESTIONS,
    }


def get_anonymous_survey(survey_id: str) -> dict[str, Any] | None:
    for survey in ANONYMOUS_SURVEYS:
        if survey["id"] == survey_id:
            return survey
    return None
