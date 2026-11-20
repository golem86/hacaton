"""
Синтетичні демо-дані зрілості за Додатком В для закритих seed-циклів (2025-II, 2026-I).
Без модуля random: усе детерміновано, тож основний seed (random.seed(2026)) не змінюється.

Що показує демо (k = 5):
  - анкет Додатка В: mgmt 7, npp 15, cadets 24, staff 3 → staff прихована первинно (< k),
    mgmt — вторинно (інакше staff можна було б вирахувати з підсумку); видимі npp і cadets;
  - одна експертна оцінка на цикл; чек-лист заповнено повністю, 2 пункти не підтверджено;
  - об'єктивні показники, частина не підтверджена;
  - у циклі 2026-I спрацьовує кожне правило: MAT_SELF_EXPERT_GAP_GE_1, MAT_SELF_CHECKLIST_GAP_GE_1,
    MAT_LOW_LEVEL_LT_3, MAT_OBJECTIVE_BELOW_TARGET, MAT_OBJECTIVE_UNCONFIRMED.
"""
import json
from datetime import datetime, timedelta
from fractions import Fraction

from .annex_v import ANNEX_V_VERSION, FORMS, LEVEL_MAPS, LEVELS
from .models import AnnexVAnswer, AnnexVExpertAssessment, AnnexVResponse, ChecklistEntry, Cycle, MaturityIndicator

COUNTS = {"mgmt": 7, "npp": 15, "cadets": 24, "staff": 3}
CADETS_FORM1 = 10                         # перші 10 курсантів заповнюють форму 1, решта — форму 2
FORM1_CATEGORIES = {"mgmt", "staff"}
OFFSET = {"mgmt": Fraction(4, 10), "npp": Fraction(-1, 10), "cadets": Fraction(0), "staff": Fraction(-3, 10)}

# Цільовий рівень самооцінки 2026-I по критеріях; 2025-II — на 0,4 нижче
TARGET = {"leadership": "4.3", "ethics": "3.6", "education": "3.9", "openness": "3.3", "officer": "4.2",
          "strategy": "3.9", "risks": "2.7", "checks": "3.1", "whistleblowers": "2.6", "audit": "2.9",
          "maturity": "3.6"}
SHIFT = {"2025-II": Fraction(-4, 10), "2026-I": Fraction(0)}

EXPERT_LABEL = "Голова робочої групи з доброчесності"
EXPERT = {  # рівень експерта по критеріях (форма 1)
    "2026-I": {"leadership": 3, "ethics": 3, "education": 4, "openness": 3, "officer": 4, "strategy": 3,
               "risks": 2, "checks": 3, "whistleblowers": 2, "audit": 2, "maturity": 3},
    "2025-II": {"leadership": 3, "ethics": 3, "education": 3, "openness": 3, "officer": 3, "strategy": 3,
                "risks": 2, "checks": 3, "whistleblowers": 2, "audit": 2, "maturity": 3},
}

CHECKLIST = {
    "2026-I": {"B-01": "no", "B-02": "yes", "B-03": "yes", "B-04": "yes", "B-05": "yes", "B-06": "partial",
               "B-07": "partial", "B-08": "yes", "B-09": "partial", "B-10": "yes", "B-11": "partial",
               "B-12": "partial", "B-13": "yes", "B-14": "yes", "B-15": "yes", "B-16": "partial",
               "B-17": "partial", "B-18": "partial", "B-19": "partial", "B-20": "no"},
    "2025-II": {"B-01": "no", "B-02": "yes", "B-03": "partial", "B-04": "yes", "B-05": "partial",
                "B-06": "partial", "B-07": "partial", "B-08": "partial", "B-09": "partial", "B-10": "partial",
                "B-11": "no", "B-12": "partial", "B-13": "yes", "B-14": "partial", "B-15": "yes",
                "B-16": "no", "B-17": "partial", "B-18": "partial", "B-19": "no", "B-20": "no"},
}
UNCONFIRMED_CODES = {"B-11", "B-16"}       # внесено, але ще не підтверджено (критерії мають інші пункти)

# (критерій, назва, значення 2026-I, ціль, підтверджено)
INDICATORS = [
    ("education", "Персонал, що пройшов навчання з доброчесності", 81, 90, True),
    ("officer", "Виконання плану роботи уповноваженого", 92, 90, False),
    ("risks", "Ризики з реєстру, щодо яких виконано заходи", 46, 80, True),
    ("whistleblowers", "Повідомлення, розглянуті у строк", 70, 100, True),
    ("openness", "Оприлюднені звіти уповноваженого за період", 100, 100, False),
]


def _letter(criterion: str, level: int) -> str:
    """Перша буква варіанта з потрібним рівнем (для викривачів 4 → d, 5 → f)."""
    levels = LEVEL_MAPS.get(criterion, LEVELS)
    return next(x for x, value in levels.items() if value == level)


def _levels(target: Fraction, n: int) -> list[int]:
    """n цілих рівнів 1..5 із сумою round(target·n): спершу вищі, потім нижчі (детерміновано)."""
    total = max(n, min(5 * n, int(target * n + Fraction(1, 2))))
    base, extra = divmod(total, n)
    return [min(5, base + (1 if i < extra else 0)) for i in range(n)]


def _form(category: str, index: int) -> int:
    if category in FORM1_CATEGORIES or (category == "cadets" and index < CADETS_FORM1):
        return 1
    return 2


def seed_annex_v(db, cycles: list[Cycle]) -> None:
    for cycle in cycles:
        shift = SHIFT.get(cycle.name)
        if shift is None:
            continue
        # 1. Анонімні анкети: лише категорія, форма й версія
        for category, n in COUNTS.items():
            plan = {key: _levels(Fraction(TARGET[key]) + shift + OFFSET[category], n) for key in TARGET}
            for i in range(n):
                form = _form(category, i)
                response = AnnexVResponse(cycle_id=cycle.id, respondent_category=category, form=form,
                                          version=ANNEX_V_VERSION)
                response.answers = [AnnexVAnswer(question_id=qid,
                                                 option_id=f"{qid}-{_letter(q['criterion'], plan[q['criterion']][i])}")
                                    for qid, q in FORMS[form].items()]
                db.add(response)
        # 2. Експертна оцінка (форма 1)
        expert = EXPERT[cycle.name]
        answers = {qid: f"{qid}-{_letter(q['criterion'], expert[q['criterion']])}" for qid, q in FORMS[1].items()}
        entered = datetime.combine(cycle.start_date + timedelta(days=75), datetime.min.time()) + timedelta(hours=10)
        db.add(AnnexVExpertAssessment(cycle_id=cycle.id, expert_label=EXPERT_LABEL, form=1,
                                      version=ANNEX_V_VERSION, answers_json=json.dumps(answers),
                                      entered_role="admin", created_at=entered))
        # 3. Чек-лист: вносить data_officer, підтверджує admin (інший користувач)
        for code, status in CHECKLIST[cycle.name].items():
            confirmed = code not in UNCONFIRMED_CODES
            db.add(ChecklistEntry(cycle_id=cycle.id, code=code, status=status,
                                  evidence=f"Синтетичний доказ до пункту {code}", entered_role="data_officer",
                                  entered_at=entered, confirmed=confirmed,
                                  confirmed_role="admin" if confirmed else None,
                                  confirmed_at=entered + timedelta(days=1) if confirmed else None))
        # 4. Об'єктивні показники (2025-II — на 6 п.п. нижче)
        delta = 0 if cycle.name == "2026-I" else -6
        for criterion, name, value, target, confirmed in INDICATORS:
            db.add(MaturityIndicator(cycle_id=cycle.id, criterion=criterion, name=name,
                                     value=float(max(0, value + delta)), target=float(target), period=cycle.name,
                                     entered_role="data_officer", entered_at=entered, confirmed=confirmed,
                                     confirmed_role="admin" if confirmed else None,
                                     confirmed_at=entered + timedelta(days=1) if confirmed else None))
