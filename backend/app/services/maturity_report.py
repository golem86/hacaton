"""
Звіт зрілості за Додатком В (PDF і XLSX) — за мотивами шаблону звіту Додатка Г.

Вхід — ГОТОВА відповідь services/maturity.calculate (та сама, що повертає GET /api/assessments/{id}/maturity):
жодних формул тут немає, лише подання. Приховані значення лишаються прихованими («Приховано»), а
приховані категорії не перелічуються (D4). Обидва формати будуються з одних і тих самих таблиць.

Аркуші XLSX: «Зрілість», «Розриви й пропозиції», «Джерела»; PDF — ті самі розділи підряд (DejaVuSans).
"""
from dataclasses import dataclass
from datetime import datetime

from . import maturity
from .reporting import HIDDEN, MISSING, ReportTable, XlsxSheet, render_pdf, render_xlsx_book

TITLE = "Звіт зрілості системи доброчесності (Додаток В)"
NOTE = ("Зведені дані закритого циклу за методикою команди; не є офіційним оцінюванням. "
        "Малі групи приховано, тексти пропозицій — чернетка для робочої групи.")
SYNTHETIC_NOTE = "СИНТЕТИЧНІ ДАНІ: база позначена як демонстраційна (instance_meta.dataset = synthetic)."
SOURCE_NAMES = {"self": "Самооцінювання", "expert": "Експерт", "checklist": "Чек-лист Додатка Б"}
INDEX_NAMES = {"self": "Індекс самооцінювання (0–100)", "expert": "Експертний індекс (0–100)",
               "checklist": "Індекс чек-листа (0–100)"}
FLAG_YES, FLAG_NO = "Так (≥ 1,0)", "Ні"
NOT_COMPUTED = "Не обчислено"

SHEET_MATURITY, SHEET_GAPS, SHEET_SOURCES = "Зрілість", "Розриви й пропозиції", "Джерела"


@dataclass(frozen=True)
class MaturityReportDoc:
    notes: tuple[str, ...]
    sheets: tuple[tuple[str, tuple[ReportTable, ...], tuple[int, ...]], ...]


def _level(source: dict) -> str | float:
    """Рівень джерела або чесна причина відсутності; null ніколи не стає 0."""
    if source["level"] is not None:
        return source["level"]
    return HIDDEN if source["status"] == "suppressed" else MISSING


def _count(value: int | None, status: str) -> str | int:
    if value is not None:
        return value
    return HIDDEN if status == "suppressed" else MISSING


def _gap(gap: dict) -> tuple[str | float, str]:
    if gap["diff"] is None:
        return MISSING, "—"
    return gap["diff"], FLAG_YES if gap["flag"] else FLAG_NO


def build(data: dict, generated_at: datetime, synthetic: bool) -> MaturityReportDoc:
    assessment = data["assessment"]
    criteria = data["criteria"]
    names = {c["key"]: c["name_uk"] for c in criteria}

    summary = [
        ("Назва циклу", assessment["name"]),
        ("ID циклу", assessment["id"]),
        ("Стан циклу", "Закрито"),
        ("Сформовано (UTC)", generated_at.strftime("%Y-%m-%d %H:%M")),
        ("Версія методики", data["methodology_version"]),
        ("Дані", "Синтетичні (демонстрація)" if synthetic else "Не позначені як синтетичні"),
        ("Поріг групи (k)", data["min_group_size"]),
        ("Групи, менші за поріг", HIDDEN if data["suppressed"] else "Немає"),
    ]
    for source in ("self", "expert", "checklist"):
        value = data["indices"][source]
        summary.append((INDEX_NAMES[source], NOT_COMPUTED if value is None else value))
    overall = data["overall_self_declared"]
    summary.append(("Заявлений загальний рівень (самооцінка, не в індексі)", _level(overall)))

    levels = []
    for c in criteria:
        final, source = maturity.base_level(c["self"]["level"], c["expert"]["level"])
        checklist = c["checklist"]
        levels.append((
            c["name_uk"],
            _level(c["self"]), _count(c["self"]["responses"], c["self"]["status"]),
            _level(c["expert"]), c["expert"]["experts"],
            _level(checklist), f'{checklist["items_confirmed"]} з {checklist["items_total"]}',
            MISSING if final is None else final, "—" if source is None else SOURCE_NAMES[source],
        ))

    gaps = []
    for c in criteria:
        by_right = {g["right"]: g for g in c["gaps"]}
        gaps.append((c["name_uk"], *_gap(by_right["expert"]), *_gap(by_right["checklist"])))

    recommendations = [(names.get(r["criterion"], r["criterion"]), r["rule_id"], r["text"])
                       for r in data["recommendations"]]
    if not recommendations:
        recommendations = [("—", "—", "Правила методики не спрацювали для цього циклу.")]
    rules = [(rule, condition) for rule, condition in maturity.RULE_CONDITIONS.items()]

    k = data["min_group_size"]
    sources = [
        ("Самооцінювання",
         f"Анонімні анкети Додатка В (форми 1 і 2). Категорії з кількістю анкет менше k = {k} приховано, "
         "діє вторинне приховування; приховані групи в звіті не перелічуються. Окремих анкет звіт не містить."),
        ("Експерт",
         "Експертна оцінка за формою 1. Експерт зазначається посадою або роллю, а не особою; "
         "у звіті — лише кількість експертів і середній рівень."),
        ("Чек-лист Додатка Б",
         "Рівень = 1 + 4 × (так + 0,5 × частково) / підтверджені пункти; враховуються лише пункти, "
         "підтверджені іншим користувачем."),
        ("Підсумковий рівень",
         "За правилами методики (розділ 8): рівень експерта, а без експертної оцінки — самооцінка."),
        ("Розриви", "Самооцінка − експерт і самооцінка − чек-лист; позначка — різниця ≥ 1,0 рівня."),
        ("Пропозиції",
         "Тексти пропозицій — чернетка для робочої групи: кожна потребує рішення людини, "
         "відповідальних і строки система не призначає."),
        ("Правило рівнів", data["level_rule"]),
        ("Методика", f'{data["methodology_version"]} — авторська методика команди, не затверджена.'),
        ("Обмеження",
         "Рівні 1–5 усереднюються як рівновіддалені; середнє не показує поляризації відповідей. "
         "Результат оцінює систему закладу, а не людей, і не може використовуватися для санкцій."),
    ]

    notes = (NOTE, SYNTHETIC_NOTE) if synthetic else (NOTE,)
    return MaturityReportDoc(notes, (
        (SHEET_MATURITY, (
            ReportTable("Підсумок", ("Показник", "Значення"), summary, (220, 303)),
            ReportTable("Рівні за критеріями (1–5)",
                        ("Критерій", "Самооцінка", "Анкет", "Експерт", "Експертів", "Чек-лист",
                         "Пункти підтв.", "Підсумковий рівень", "Джерело підсумку"),
                        levels, (103, 54, 40, 48, 50, 50, 52, 60, 66)),
        ), (34, 13, 10, 11, 11, 11, 13, 13, 18)),
        (SHEET_GAPS, (
            ReportTable("Розриви між джерелами",
                        ("Критерій", "Самооцінка − експерт", "Позначка", "Самооцінка − чек-лист", "Позначка"),
                        gaps, (163, 90, 90, 90, 90)),
            ReportTable("Пропозиції (чернетка для робочої групи)", ("Критерій", "Код правила", "Пояснення"),
                        recommendations, (110, 150, 263)),
            ReportTable("Правила методики", ("Код правила", "Умова"), rules, (190, 333)),
        ), (34, 34, 70, 22, 14)),
        (SHEET_SOURCES, (
            ReportTable("Джерела даних і обмеження", ("Розділ", "Пояснення"), sources, (130, 393)),
        ), (26, 110)),
    ))


def render(doc: MaturityReportDoc, format: str) -> bytes:
    if format == "pdf":
        return render_pdf([table for _, tables, _ in doc.sheets for table in tables], title=TITLE, notes=doc.notes)
    return render_xlsx_book([XlsxSheet(name, list(tables), widths) for name, tables, widths in doc.sheets],
                            title=TITLE, notes=doc.notes)
