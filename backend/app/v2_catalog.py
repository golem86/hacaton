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

PERSONAL_DURATION = "7 питань · близько 5 хв"

# Синтетичний каталог особистих самооцінювань (без персональних даних).
# Порядок перших двох записів і їхні id незмінні: на них посилаються тести та збережені спроби.
# created_at — момент публікації в каталозі (ISO 8601 з поясом), завжди не пізніше opens_at.
PERSONAL_ASSESSMENTS: list[dict[str, Any]] = [
    {
        "id": "personal-2026-q4",
        "name": "Особисте самооцінювання · Q4 2026",
        "duration": PERSONAL_DURATION,
        "created_at": "2026-11-03T09:00:00+00:00",
        "opens_at": "2026-11-17T00:00:00+00:00",
        "closes_at": "2026-11-24T23:59:59+00:00",
    },
    {
        "id": "personal-2027-q1",
        "name": "Особисте самооцінювання · Q1 2027",
        "duration": "Підготовка · доступне з 2027-01-01",
        "created_at": "2026-11-10T10:30:00+00:00",
        "opens_at": "2027-01-01T00:00:00+00:00",
        "closes_at": "2027-01-08T23:59:59+00:00",
    },
    {
        "id": "personal-2025-q1",
        "name": "Особисте самооцінювання · Q1 2025",
        "duration": PERSONAL_DURATION,
        "created_at": "2025-01-08T09:00:00+00:00",
        "opens_at": "2025-01-15T00:00:00+00:00",
        "closes_at": "2025-01-31T23:59:59+00:00",
    },
    {
        "id": "personal-2025-q2",
        "name": "Особисте самооцінювання · Q2 2025",
        "duration": PERSONAL_DURATION,
        "created_at": "2025-04-01T09:00:00+00:00",
        "opens_at": "2025-04-07T00:00:00+00:00",
        "closes_at": "2025-04-25T23:59:59+00:00",
    },
    {
        "id": "personal-2025-q3",
        "name": "Особисте самооцінювання · Q3 2025",
        "duration": PERSONAL_DURATION,
        "created_at": "2025-07-01T09:00:00+00:00",
        "opens_at": "2025-07-07T00:00:00+00:00",
        "closes_at": "2025-07-25T23:59:59+00:00",
    },
    {
        "id": "personal-2025-q4",
        "name": "Особисте самооцінювання · Q4 2025",
        "duration": PERSONAL_DURATION,
        "created_at": "2025-09-30T09:00:00+00:00",
        "opens_at": "2025-10-06T00:00:00+00:00",
        "closes_at": "2025-10-24T23:59:59+00:00",
    },
    {
        "id": "personal-2026-q1",
        "name": "Особисте самооцінювання · Q1 2026",
        "duration": PERSONAL_DURATION,
        "created_at": "2026-01-05T09:00:00+00:00",
        "opens_at": "2026-01-12T00:00:00+00:00",
        "closes_at": "2026-01-30T23:59:59+00:00",
    },
    {
        "id": "personal-2026-q2",
        "name": "Особисте самооцінювання · Q2 2026",
        "duration": PERSONAL_DURATION,
        "created_at": "2026-03-31T09:00:00+00:00",
        "opens_at": "2026-04-06T00:00:00+00:00",
        "closes_at": "2026-04-24T23:59:59+00:00",
    },
    {
        "id": "personal-2026-q3",
        "name": "Особисте самооцінювання · Q3 2026",
        "duration": PERSONAL_DURATION,
        "created_at": "2026-06-30T09:00:00+00:00",
        "opens_at": "2026-07-06T00:00:00+00:00",
        "closes_at": "2026-07-24T23:59:59+00:00",
    },
    {
        "id": "thematic-2026-gifts",
        "name": "Тематичне самооцінювання: подарунки та гостинність",
        "duration": PERSONAL_DURATION,
        "created_at": "2026-08-18T11:00:00+00:00",
        "opens_at": "2026-09-01T00:00:00+00:00",
        "closes_at": "2026-09-30T23:59:59+00:00",
    },
    {
        "id": "thematic-2026-reporting-channels",
        "name": "Тематичне самооцінювання: канали повідомлень",
        "duration": PERSONAL_DURATION,
        "created_at": "2026-10-20T08:15:00+00:00",
        "opens_at": "2026-11-02T00:00:00+00:00",
        "closes_at": "2026-11-30T23:59:59+00:00",
    },
    {
        "id": "thematic-2026-conflict-of-interest",
        "name": "Тематичне самооцінювання: конфлікт інтересів",
        "duration": PERSONAL_DURATION,
        "created_at": "2026-10-27T13:40:00+00:00",
        "opens_at": "2026-11-09T00:00:00+00:00",
        "closes_at": "2026-12-11T23:59:59+00:00",
    },
    {
        "id": "training-2026-integrity",
        "name": "Самооцінювання після навчання з доброчесності",
        "duration": PERSONAL_DURATION,
        "created_at": "2026-11-12T07:30:00+00:00",
        "opens_at": "2026-11-16T00:00:00+00:00",
        "closes_at": "2026-12-04T23:59:59+00:00",
    },
    {
        "id": "thematic-2026-leadership",
        "name": "Тематичне самооцінювання: приклад керівництва",
        "duration": PERSONAL_DURATION,
        "created_at": "2026-11-14T10:00:00+00:00",
        "opens_at": "2026-12-01T00:00:00+00:00",
        "closes_at": "2026-12-18T23:59:59+00:00",
    },
    {
        "id": "training-2027-onboarding",
        "name": "Самооцінювання після вступного інструктажу",
        "duration": PERSONAL_DURATION,
        "created_at": "2026-11-16T12:00:00+00:00",
        "opens_at": "2027-02-01T00:00:00+00:00",
        "closes_at": "2027-02-15T23:59:59+00:00",
    },
    {
        "id": "thematic-2027-transparency",
        "name": "Тематичне самооцінювання: прозорість рішень",
        "duration": PERSONAL_DURATION,
        "created_at": "2026-11-17T09:20:00+00:00",
        "opens_at": "2027-03-01T00:00:00+00:00",
        "closes_at": "2027-03-19T23:59:59+00:00",
    },
    {
        "id": "personal-2027-q2",
        "name": "Особисте самооцінювання · Q2 2027",
        "duration": PERSONAL_DURATION,
        "created_at": "2026-11-18T08:00:00+00:00",
        "opens_at": "2027-04-05T00:00:00+00:00",
        "closes_at": "2027-04-23T23:59:59+00:00",
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


def _aware_utc(moment: datetime) -> datetime:
    """Наївний час (без поясу) трактується як UTC; інакше порівняння з aware-датами — TypeError/500."""
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def is_open(assessment: dict[str, Any], now: datetime | None = None) -> bool:
    # V2_CATALOG_NOW — лише для локальних тестів; у release його забороняє settings.validate_release_config
    configured_now = os.environ.get("V2_CATALOG_NOW")
    current = now or (datetime.fromisoformat(configured_now) if configured_now else datetime.now(timezone.utc))
    start = _aware_utc(datetime.fromisoformat(assessment["opens_at"]))
    end = _aware_utc(datetime.fromisoformat(assessment["closes_at"]))
    return start <= _aware_utc(current) <= end


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
