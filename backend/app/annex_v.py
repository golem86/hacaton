"""
Серверний каталог Додатка В (анкети зрілості) і адаптованого чек-листа Додатка Б.

Ідентифікатори питань і варіантів відповідей дзеркалять frontend/src/official/catalog-v2.ts,
шаблони версії "2.0.0":
  - питання: av-f{форма}-{розділ}-{номер}, розділ ∈ culture | system | accountability | maturity;
  - варіант: {id питання}-{a..e}; у питаннях про викривачів (whistleblowers) є ще варіант `f`.
Критерій (criterion) = ключ набору варіантів (`choices`) у catalog-v2.ts для цього питання.

ПРАВИЛО РІВНЯ (рішення команди, задокументоване в API; дані — LEVEL_MAPS нижче):
  - усі питання: a=1, b=2, c=3, d=4, e=5 (варіанти в Додатку В упорядковані за зрілістю);
  - питання про викривачів (6 варіантів): a=1, b=2, c=3, d=4, e=4, f=5 — за Додатком Г, с. 73.
У формі 1 критерій openness має два питання (№4 і №5 — те саме питання джерела): спершу
середнє в межах ОДНІЄЇ анкети, тож анкета враховується для openness один раз. Критерій `maturity` (заявлений загальний рівень) показується
окремо й до індексу зрілості не входить.

Тексти питань тут не дублюються: їх показує frontend. Сервер знає лише id → критерій і рівень.
"""
from fractions import Fraction

ANNEX_V_VERSION = "2.0.0"
FORM_TEMPLATES = {1: "appendix-v-form-1", 2: "appendix-v-form-2"}
LEVEL_RULE = "a=1…e=5; викривачі: a=1, b=2, c=3, d=4, e=4, f=5 (Додаток Г, с. 73)"
LEVELS = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}
# Буква варіанта → рівень для критерію; критерій без власного запису використовує LEVELS
LEVEL_MAPS: dict[str, dict[str, int]] = {
    "whistleblowers": {"a": 1, "b": 2, "c": 3, "d": 4, "e": 4, "f": 5},     # Додаток Г, с. 73
}

# Критерії Додатка В: назва українською і компонент Integrity Index (лише для показу).
# C4 (доброчесність освітнього процесу) не має відповідного критерію в Додатку В — не вигадуємо.
CRITERIA: dict[str, dict] = {
    "leadership": {"name_uk": "Лідерство керівника", "component_code": "C1"},
    "ethics": {"name_uk": "Доброчесність і корпоративна етика", "component_code": "C1"},
    "education": {"name_uk": "Навчання персоналу", "component_code": "C5"},
    "openness": {"name_uk": "Відкритість інформації про доброчесність", "component_code": "C7"},
    "officer": {"name_uk": "Уповноважений з доброчесності", "component_code": "C2"},
    "strategy": {"name_uk": "Стратегія доброчесності", "component_code": "C2"},
    "risks": {"name_uk": "Управління корупційними ризиками", "component_code": "C3"},
    "checks": {"name_uk": "Аналіз актів, перевірка кандидатів і контрагентів", "component_code": "C3"},
    "whistleblowers": {"name_uk": "Повідомлення про корупцію і захист викривачів", "component_code": "C6"},
    "audit": {"name_uk": "Аудит системи доброчесності", "component_code": "C7"},
    "maturity": {"name_uk": "Заявлений загальний рівень зрілості", "component_code": None},
}
OVERALL_CRITERION = "maturity"
INDEX_CRITERIA = tuple(key for key in CRITERIA if key != OVERALL_CRITERION)   # 10 критеріїв індексу

# (розділ, номер, критерій) — у порядку catalog-v2.ts
_FORM1 = [("culture", 1, "leadership"), ("culture", 2, "ethics"), ("culture", 3, "education"),
          ("culture", 4, "openness"), ("culture", 5, "openness"),
          ("system", 1, "officer"), ("system", 2, "strategy"),
          ("accountability", 1, "risks"), ("accountability", 2, "checks"),
          ("accountability", 3, "whistleblowers"), ("accountability", 4, "audit"),
          ("maturity", 1, "maturity")]
_FORM2 = [("culture", 1, "ethics"), ("culture", 2, "education"), ("culture", 3, "openness"),
          ("system", 1, "officer"), ("system", 2, "strategy"),
          ("accountability", 1, "risks"), ("accountability", 2, "checks"),
          ("accountability", 3, "whistleblowers"), ("accountability", 4, "audit"),
          ("maturity", 1, "maturity")]


def _questions(form: int, entries) -> dict[str, dict]:
    result = {}
    for section, number, criterion in entries:
        qid = f"av-f{form}-{section}-{number}"
        levels = LEVEL_MAPS.get(criterion, LEVELS)
        result[qid] = {"criterion": criterion, "options": {f"{qid}-{x}": level for x, level in levels.items()}}
    return result


# {форма: {id питання: {"criterion": ..., "options": {id варіанта: рівень}}}}
FORMS: dict[int, dict[str, dict]] = {1: _questions(1, _FORM1), 2: _questions(2, _FORM2)}


def validate_answers(form: int, answers: dict[str, str]) -> str | None:
    """None, якщо відповіді повні й коректні; інакше текст помилки (для 422)."""
    questions = FORMS.get(form)
    if questions is None:
        return "Невідома форма анкети"
    if set(answers) != set(questions):
        return "Потрібна рівно одна відповідь на кожне питання форми"
    for qid, option in answers.items():
        if option not in questions[qid]["options"]:
            return f"Варіант відповіді не належить питанню {qid}"
    return None


def criterion_levels(form: int, answers: dict[str, str]) -> dict[str, Fraction]:
    """
    Рівень кожного критерію для ОДНІЄЇ анкети: середнє рівнів її відповідей на питання критерію
    (у формі 1 критерій openness має два питання — анкета враховується один раз). Точна арифметика.
    """
    values: dict[str, list[int]] = {}
    for qid, option in answers.items():
        question = FORMS[form][qid]
        values.setdefault(question["criterion"], []).append(question["options"][option])
    return {key: Fraction(sum(items), len(items)) for key, items in values.items()}


# ---------------------------------------------------------------------------
# Чек-лист: адаптовано з Додатка Б («Контрольний чек-лист застосування інструментів та механізмів
# для трансформації функціонування ВВНЗ (ВНП ЗВО) на засадах прозорості та доброчесності»).
# Формулювання — стислі незалежні адаптації завдань і індикаторів; `source_item` — номер пункту
# в Додатку Б. Прив'язка до критерію Додатка В — рішення команди (потребує методичного погодження).
# ---------------------------------------------------------------------------
CHECKLIST_SOURCE = "Додаток Б (адаптовано)"
CHECKLIST: list[dict] = [
    {"code": "B-01", "source_item": "1.1", "criterion": "strategy",
     "text": "Визначено поточний рівень зрілості доброчесності закладу та затверджено план заходів трансформації"},
    {"code": "B-02", "source_item": "1.2", "criterion": "leadership",
     "text": "Доброчесність закріплено серед цінностей у місії, візії та статуті (положенні) закладу"},
    {"code": "B-03", "source_item": "1.3", "criterion": "leadership",
     "text": "Визначено лідерську роль керівництва й затверджено програму доброчесності (антикорупційну програму)"},
    {"code": "B-04", "source_item": "2.1", "criterion": "officer",
     "text": "Видано акт про правовий статус і засади діяльності антикорупційного уповноваженого"},
    {"code": "B-05", "source_item": "2.2–2.3", "criterion": "officer",
     "text": "Уповноважений відповідає професійному стандарту й пройшов курс «Стоп корупція. Уповноважені»"},
    {"code": "B-06", "source_item": "2.4", "criterion": "risks",
     "text": "Проведено оцінку корупційних ризиків і затверджено заходи з їх мінімізації"},
    {"code": "B-07", "source_item": "2.5", "criterion": "strategy",
     "text": "Розроблено й виконується план роботи уповноваженого з урахуванням специфіки закладу"},
    {"code": "B-08", "source_item": "2.6", "criterion": "education",
     "text": "Регулярні навчальні заходи з доброчесності включено до навчальних планів персоналу й здобувачів"},
    {"code": "B-09", "source_item": "2.7", "criterion": "whistleblowers",
     "text": "Функціонує система повідомлень про корупцію та порушення доброчесності, канали відомі персоналу"},
    {"code": "B-10", "source_item": "2.8", "criterion": "openness",
     "text": "Антикорупційний розділ офіційного вебсайту має визначену структуру й регулярно оновлюється"},
    {"code": "B-11", "source_item": "3.3", "criterion": "audit",
     "text": "Проводиться регулярне електронне анонімне оцінювання якості викладання"},
    {"code": "B-12", "source_item": "3.4", "criterion": "audit",
     "text": "Питання доброчесності включено до регулярних опитувань, результати аналізують і обговорюють"},
    {"code": "B-13", "source_item": "4.1", "criterion": "ethics",
     "text": "Діють внутрішні політики запобігання та врегулювання конфлікту інтересів"},
    {"code": "B-14", "source_item": "4.4", "criterion": "risks",
     "text": "Функції управління фінансами, закупівель і контролю розподілено між окремими посадами"},
    {"code": "B-15", "source_item": "4.5", "criterion": "checks",
     "text": "Здійснюється перевірка контрагентів і антикорупційний моніторинг публічних закупівель"},
    {"code": "B-16", "source_item": "4.6", "criterion": "openness",
     "text": "Інформацію про орендовані необоротні активи закладу оприлюднено на відкритих ресурсах"},
    {"code": "B-17", "source_item": "5.2", "criterion": "education",
     "text": "Впроваджено регулярне навчання учасників освітнього процесу з академічної доброчесності"},
    {"code": "B-18", "source_item": "5.5", "criterion": "ethics",
     "text": "Забезпечено контроль за дотриманням правил академічної доброчесності"},
    {"code": "B-19", "source_item": "6.1", "criterion": "checks",
     "text": "Залучення благодійних коштів і партнерство з бізнесом прозорі та підконтрольні"},
    {"code": "B-20", "source_item": "6.3", "criterion": "risks",
     "text": "Регламентовано й контролюється залучення та використання грантових коштів"},
]
CHECKLIST_BY_CODE = {item["code"]: item for item in CHECKLIST}
CHECKLIST_STATUSES = ("yes", "partial", "no")
