"""Відтворюваний генератор синтетичного демо-циклу оцінювання (≈150 анонімних анкет вигаданих учасників).

Навіщо: щоб на синтетичному екземплярі був один закритий цикл із «живими» різними результатами, за яким
локальна LM (services/narrative.py) пише резюме, рекомендації й порівняння з попереднім циклом.

Запуск з каталогу backend:

  python -m app.demo_cycle --responses 150 --seed 2026                     # лише план, БД не змінюється
  python -m app.demo_cycle --responses 150 --seed 2026 --confirm           # створити цикл
  python -m app.demo_cycle --responses 150 --seed 2026 --name "Демо 2026" --confirm
  python -m app.demo_cycle --responses 150 --name "Демо: підрозділи" --no-small-groups --confirm
                                    # кожна клітинка «категорія × підрозділ» ≥ k + 1 (екран «Результати підрозділу»)

На сервері Windows — обгортка installer/windows-v2/ops/New-V2DemoCycle.ps1 ([-Apply]). Опис — docs/DEMO_DATA.md.

Що створюється (в ОДНІЙ транзакції): цикл зі статусом closed і датами в минулому (k = 5, як у seed),
cycle_config (усі чотири категорії, опис «Демонстраційні синтетичні дані»), N анкет з відповідями на ВСІ
питання анкети (kind = survey) у межах шкали кожного питання, коди доступу (у БД лише SHA-256 випадкових
кодів, які ніде не зберігаються і не виводяться): N використаних + ≈20 % невикористаних, політики кодів
(категорія, строк уже минув), одна подія журналу `demo.cycle_generated` (actor_role = "server", details лише count).

Розподіл: більшість — курсанти/студенти, менше НПП, мало керівництва й персоналу. Керівництво (4) і персонал (3)
менші за поріг k = 5 і приховуються; разом їх 7 ≥ k, тож вторинне приховування не зачіпає НПП і курсантів.
Профілі відповідей за категоріями різні (C6 «Повідомлення про порушення» помітно слабший, у курсантів — найнижчий;
керівництво оцінює вище; C5 і C2 — найсильніші), плюс індивідуальний зсув учасника і шум відповіді.
Усе детерміновано від --seed: random.Random(seed), глобальний random не використовується.

Запобіжники:
  - лише БД з позначкою instance_meta('dataset', 'synthetic') (її ставить seed або v2_db_tool mark-synthetic);
    інакше відмова — синтетичні анкети не змішуються з реальними;
  - цикл із такою самою назвою вже є → відмова, нічого не змінено (повторний запуск безпечний);
  - схема лише перевіряється (check_schema), БД не мігрує і не створюється;
  - не потребує V2_SECRET_KEY; зі змінних середовища читає лише INTEGRITY_DB (у release обов'язкова) і APP_ENV.

Коди виходу: 0 — виконано або показано план; 2 — відмова; 1 — помилка (схема, файл БД, інше).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import secrets
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Callable

from . import settings

EXIT_OK, EXIT_ERROR, EXIT_REFUSED = 0, 1, 2

DEFAULT_NAME = "Демо-цикл (синтетичні дані)"
DESCRIPTION = "Демонстраційні синтетичні дані"
SCOPE = "Демонстраційний цикл: вигадані учасники"
QUESTIONNAIRE_VERSION = "demo-v1"
MIN_GROUP_SIZE = 5                      # як у seed (Cycle.min_group_size за замовчуванням)
MIN_RESPONSES, MAX_RESPONSES = 30, 2000
MAX_NAME_CHARS = 50                     # Cycle.name String(50), як у POST /api/assessments
START_DAYS_AGO, END_DAYS_AGO = 60, 14   # дати циклу в минулому відносно сьогодні
UNUSED_SHARE = 0.2                      # частка невикористаних кодів відносно поданих анкет

CATEGORIES = ("mgmt", "npp", "cadets", "staff")
# Малі групи: обидві < k (приховуються), разом ≥ k (вторинне приховування не чіпає основні групи)
SMALL_GROUPS = {"mgmt": 4, "staff": 3}
NPP_SHARE = 0.3                         # решта: 30 % НПП, 70 % курсанти/студенти

# «Справжній» рівень компонента (0–100) для категорії; C6 слабкий скрізь, у курсантів — найнижчий.
PROFILE = {             # C1  C2  C3  C4  C5  C6  C7
    "mgmt":   dict(zip(("C1", "C2", "C3", "C4", "C5", "C6", "C7"), (84, 80, 73, 77, 82, 72, 70))),
    "npp":    dict(zip(("C1", "C2", "C3", "C4", "C5", "C6", "C7"), (63, 72, 54, 60, 75, 44, 59))),
    "cadets": dict(zip(("C1", "C2", "C3", "C4", "C5", "C6", "C7"), (57, 67, 50, 47, 73, 31, 60))),
    "staff":  dict(zip(("C1", "C2", "C3", "C4", "C5", "C6", "C7"), (61, 69, 52, 57, 71, 43, 61))),
}
DEFAULT_LEVEL = 60                      # компонент поза профілем (інша анкета на сервері)
PERSON_SD = 8.0                         # індивідуальний зсув учасника: оптимісти й критики
ANSWER_SD = 11.0                        # шум окремої відповіді

# Підрозділи seed; невідомі назви отримують рівну вагу 1/кількість
UNIT_WEIGHTS = {
    "cadets": {"Факультет 1": 0.5, "Факультет 2": 0.44, "Кафедра загальних дисциплін": 0.06},
    "npp":    {"Факультет 1": 0.35, "Факультет 2": 0.3, "Кафедра загальних дисциплін": 0.35},
    "mgmt":   {"Факультет 1": 0.4, "Факультет 2": 0.4, "Кафедра загальних дисциплін": 0.2},
    "staff":  {"Факультет 1": 0.34, "Факультет 2": 0.33, "Кафедра загальних дисциплін": 0.33},
}


class DemoRefused(Exception):
    """Генерацію відхилено; БД не змінена."""


@dataclass(frozen=True)
class QuestionSpec:
    id: int
    component: str
    scale_min: int
    scale_max: int


@dataclass
class DemoPlan:
    name: str
    seed: int
    start_date: date
    end_date: date
    responses: list[tuple[str, str, dict[int, int]]]        # (категорія, підрозділ, {id питання: відповідь})
    unused_categories: list[str]
    category_counts: dict[str, int] = field(default_factory=dict)
    unit_counts: dict[str, int] = field(default_factory=dict)
    component_scores: dict[str, float] = field(default_factory=dict)
    hidden_categories: list[str] = field(default_factory=list)


def category_counts(total: int) -> dict[str, int]:
    small = sum(SMALL_GROUPS.values())
    rest = total - small
    npp = round(rest * NPP_SHARE)
    return {"mgmt": SMALL_GROUPS["mgmt"], "npp": npp, "cadets": rest - npp, "staff": SMALL_GROUPS["staff"]}


UNIT_SAFE_CELL = {"mgmt": 6, "staff": 6}   # --no-small-groups: керівництво й персонал — по 6 у кожному підрозділі


def unit_safe_cells(total: int, units: list[str]) -> dict[tuple[str, str], int]:
    """--no-small-groups: таблиця «(категорія, підрозділ) → кількість», де кожна клітинка ≥ k + 1.

    Для екрана «Результати підрозділу»: він показує дані лише тоді, коли в усьому циклі немає клітинок
    з 1…k−1 анкет. НПП і курсанти розподіляються за UNIT_WEIGHTS, але не менше k + 1 у кожному підрозділі."""
    floor = MIN_GROUP_SIZE + 1
    cells = {(c, u): n for c, n in UNIT_SAFE_CELL.items() for u in units}
    rest = total - sum(cells.values())
    if rest < 2 * floor * len(units):
        raise DemoRefused(f"--no-small-groups: замало анкет; потрібно щонайменше "
                          f"{sum(cells.values()) + 2 * floor * len(units)} для {len(units)} підрозділів.")
    npp = round(rest * NPP_SHARE)
    for category, amount in (("npp", npp), ("cadets", rest - npp)):
        weights = [UNIT_WEIGHTS[category].get(u, 1 / len(units)) for u in units]
        share = [max(floor, int(amount * w / sum(weights))) for w in weights]
        share[share.index(max(share))] += amount - sum(share)      # залишок — найбільшому підрозділу
        if min(share) < floor:
            raise DemoRefused("--no-small-groups: не вдалося розкласти анкети без малих клітинок.")
        cells.update({(category, u): n for u, n in zip(units, share)})
    return cells


def _answer(rng: random.Random, level: float, question: QuestionSpec) -> int:
    span = question.scale_max - question.scale_min
    fraction = min(100.0, max(0.0, level + rng.gauss(0, ANSWER_SD))) / 100
    return max(question.scale_min, min(question.scale_max, round(question.scale_min + fraction * span)))


def build_plan(*, name: str, seed: int, total: int, questions: list[QuestionSpec], units: list[str],
               today: date, unit_safe: bool = False) -> DemoPlan:
    """Детермінований план: однакові seed, кількість, питання й підрозділи → однакові анкети."""
    rng = random.Random(seed)
    questions = sorted(questions, key=lambda q: q.id)
    units = sorted(units)
    if unit_safe:
        cells = unit_safe_cells(total, units)
        counts = {c: sum(n for (cat, _), n in cells.items() if cat == c) for c in CATEGORIES}
        order = [(c, u) for (c, u), n in sorted(cells.items()) for _ in range(n)]
    else:
        counts = category_counts(total)
        order = [(category, None) for category in CATEGORIES for _ in range(counts[category])]
    rng.shuffle(order)                     # анкети в БД не йдуть блоками за категоріями
    responses = []
    for category, fixed_unit in order:
        weights = [UNIT_WEIGHTS[category].get(unit, 1 / len(units)) for unit in units]
        unit = fixed_unit or rng.choices(units, weights=weights)[0]
        person = rng.gauss(0, PERSON_SD)
        answers = {q.id: _answer(rng, PROFILE[category].get(q.component, DEFAULT_LEVEL) + person, q)
                   for q in questions}
        responses.append((category, unit, answers))
    unused = rng.choices(list(CATEGORIES), weights=[counts[c] for c in CATEGORIES],
                         k=round(total * UNUSED_SHARE))

    from .anonymity import hidden_flags
    categories = sorted(counts)
    flags = hidden_flags([counts[c] for c in categories], MIN_GROUP_SIZE)
    sums: dict[str, list[float]] = {}
    for _, _, answers in responses:
        for q in questions:
            sums.setdefault(q.component, []).append(
                (answers[q.id] - q.scale_min) * 100 / (q.scale_max - q.scale_min))
    return DemoPlan(
        name=name, seed=seed, start_date=today - timedelta(days=START_DAYS_AGO),
        end_date=today - timedelta(days=END_DAYS_AGO), responses=responses, unused_categories=unused,
        category_counts=counts, unit_counts=dict(sorted(Counter(unit for _, unit, _ in responses).items())),
        component_scores={code: round(sum(v) / len(v), 1) for code, v in sorted(sums.items())},
        hidden_categories=[c for c, hidden in zip(categories, flags) if hidden])


def _load_inputs(db) -> tuple[list[QuestionSpec], list[str]]:
    from .models import Question, Unit
    questions = [QuestionSpec(q.id, q.component.code, q.scale_min, q.scale_max)
                 for q in db.query(Question).filter(Question.kind == "survey").order_by(Question.id)]
    units = [u.name for u in db.query(Unit).order_by(Unit.name)]
    if not questions:
        raise DemoRefused("В анкеті немає питань (kind = survey); нічого не змінено.")
    if not units:
        raise DemoRefused("Довідник підрозділів порожній; нічого не змінено.")
    for q in questions:
        if q.scale_max <= q.scale_min:
            raise DemoRefused(f"Питання {q.id} має некоректну шкалу; нічого не змінено.")
    return questions, units


def check_guards(db, name: str) -> None:
    """Перевірки до будь-яких змін: позначка synthetic і унікальна назва циклу."""
    from .models import Cycle, InstanceMeta
    marker = db.get(InstanceMeta, "dataset")
    if marker is None or marker.value != "synthetic":
        raise DemoRefused("БД не позначена як синтетична (instance_meta.dataset = 'synthetic'): "
                          "демо-анкети не змішуються з реальними даними. Нічого не змінено.")
    if db.query(Cycle).filter(Cycle.name == name).first() is not None:
        raise DemoRefused(f"Цикл з назвою «{name}» уже є; нічого не змінено.")


def apply_plan(db, plan: DemoPlan) -> int:
    """Записує план у поточну сесію і комітить ОДИН раз. Повертає id нового циклу."""
    from . import audit
    from .models import (AccessToken, AccessTokenPolicy, Answer, Cycle, CycleConfig, ResponseSet,
                         hash_access_code)
    cycle = Cycle(name=plan.name, start_date=plan.start_date, status="closed", min_group_size=MIN_GROUP_SIZE)
    db.add(cycle)
    db.flush()
    db.add(CycleConfig(cycle_id=cycle.id, description=DESCRIPTION, scope=SCOPE,
                       categories_json=json.dumps(list(CATEGORIES)),
                       questionnaire_version=QUESTIONNAIRE_VERSION, end_date=plan.end_date))
    for category, unit, answers in plan.responses:
        response = ResponseSet(cycle_id=cycle.id, respondent_category=category, unit=unit)
        response.answers = [Answer(question_id=qid, value=value) for qid, value in answers.items()]
        db.add(response)
    # Коди: лише SHA-256 випадкових кодів (сам код ніде не зберігається). Порядок рядків перемішано,
    # щоб порядок кодів не повторював порядок анкет.
    token_rows = ([(category, True) for category, _, _ in plan.responses]
                  + [(category, False) for category in plan.unused_categories])
    random.Random(plan.seed + 1).shuffle(token_rows)
    expires = datetime.combine(plan.end_date, time(23, 59))
    tokens = [AccessToken(cycle_id=cycle.id, token_hash=hash_access_code(secrets.token_hex(16)), used=used)
              for _, used in token_rows]
    db.add_all(tokens)
    db.flush()
    db.add_all(AccessTokenPolicy(token_id=token.id, category=category, expires_at=expires)
               for token, (category, _) in zip(tokens, token_rows))
    audit.record(db, "server", "demo.cycle_generated", cycle.id, count=len(plan.responses))
    db.commit()
    return cycle.id


def _check_environment(engine) -> None:
    if settings.is_release() and not os.environ.get("INTEGRITY_DB"):
        raise RuntimeError("У release потрібна змінна середовища INTEGRITY_DB")
    from .migrations import check_schema
    check_schema(engine)


def _summary(plan: DemoPlan) -> list[str]:
    categories = ", ".join(f"{c} {plan.category_counts[c]}" for c in CATEGORIES)
    units = ", ".join(f"{u} {n}" for u, n in plan.unit_counts.items())
    scores = ", ".join(f"{code} {score}" for code, score in plan.component_scores.items())
    hidden = ", ".join(plan.hidden_categories) or "немає"
    return [f"  анкет: {len(plan.responses)}; кодів: {len(plan.responses) + len(plan.unused_categories)} "
            f"(невикористаних {len(plan.unused_categories)}); дати: {plan.start_date} — {plan.end_date}; k = {MIN_GROUP_SIZE}",
            f"  за категоріями: {categories}",
            f"  приховані порогом k категорії: {hidden}",
            f"  за підрозділами: {units}",
            f"  середні за компонентами (0–100): {scores}"]


def run(engine, *, responses: int, seed: int, name: str, confirm: bool, today: date | None = None,
        out: Callable[[str], None] = print, unit_safe: bool = False) -> int:
    """Основна логіка CLI (engine передається явно — так тести працюють з копією БД)."""
    from sqlalchemy.orm import Session
    name = " ".join(name.split())
    if not name or len(name) > MAX_NAME_CHARS:
        out(f"ВІДМОВА  назва циклу має містити від 1 до {MAX_NAME_CHARS} символів.")
        return EXIT_REFUSED
    if not MIN_RESPONSES <= responses <= MAX_RESPONSES:
        out(f"ВІДМОВА  --responses має бути від {MIN_RESPONSES} до {MAX_RESPONSES}.")
        return EXIT_REFUSED
    try:
        _check_environment(engine)
        with Session(engine, autoflush=False) as db:
            check_guards(db, name)
            questions, units = _load_inputs(db)
            plan = build_plan(name=name, seed=seed, total=responses, questions=questions, units=units,
                              today=today or date.today(), unit_safe=unit_safe)
            out(f"ПЛАН  синтетичний цикл «{name}» (seed {seed}, статус closed):")
            for line in _summary(plan):
                out(line)
            if not confirm:
                out("Лише план, нічого не змінено. Щоб виконати, повторіть команду з --confirm.")
                return EXIT_OK
            try:
                cycle_id = apply_plan(db, plan)
            except Exception:
                db.rollback()
                raise
    except DemoRefused as error:
        out(f"ВІДМОВА  {error}")
        return EXIT_REFUSED
    except Exception as error:  # noqa: BLE001 — коротке повідомлення без трасування (без кодів і відповідей)
        out(f"ПОМИЛКА  {error}; транзакцію відкочено, нічого не змінено.")
        return EXIT_ERROR
    out(f"ВИКОНАНО  створено цикл id {cycle_id} «{name}»: {len(plan.responses)} анкет; "
        f"подія журналу demo.cycle_generated.")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.demo_cycle",
                                     description="Синтетичний закритий демо-цикл (без --confirm — лише план)")
    parser.add_argument("--responses", type=int, default=150, help="кількість анкет (30–2000)")
    parser.add_argument("--seed", type=int, default=2026, help="зерно генератора (відтворюваність)")
    parser.add_argument("--name", default=DEFAULT_NAME, help="назва циклу (до 50 символів, унікальна)")
    parser.add_argument("--confirm", action="store_true", help="записати в БД (без нього — лише план)")
    parser.add_argument("--no-small-groups", action="store_true",
                        help="без малих клітинок «категорія × підрозділ» (для екрана «Результати підрозділу»)")
    args = parser.parse_args(argv)           # неправильні аргументи → SystemExit(2), тобто «відмова»
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    from .database import engine            # створення engine не відкриває і не створює файл
    return run(engine, responses=args.responses, seed=args.seed, name=args.name, confirm=args.confirm,
               unit_safe=args.no_small_groups)


if __name__ == "__main__":
    sys.exit(main())
