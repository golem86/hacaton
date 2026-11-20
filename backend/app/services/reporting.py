"""Build both export formats from the canonical, already suppressed aggregates."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from threading import Lock
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle
from xlsxwriter import Workbook

TITLE = "Звіт про оцінювання доброчесності"
NOTE = "Звіт містить зведені дані закритого циклу. Малі групи приховано."
HIDDEN = "Приховано"
MISSING = "Немає даних"
CATEGORY_NAMES = {
    "cadets": "Курсанти",
    "mgmt": "Керівництво",
    "npp": "Науково-педагогічні працівники",
    "staff": "Персонал",
}
INK = "#17302F"
GREEN = "#235D50"
PALE = "#ECF4F0"
LINE = "#D8E2DE"
FONT_PATH = Path(__file__).resolve().parents[1] / "static" / "report-font" / "DejaVuSans.ttf"
PDF_FONT = "IntegrityV2DejaVuSans"
PDF_LOCK = Lock()

Cell = str | int | float


@dataclass(frozen=True)
class ReportTable:
    name: str
    headers: tuple[str, ...]
    rows: list[tuple[Cell, ...]]
    pdf_widths: tuple[int, ...]


def _display(value: int | float | None, *, hidden: bool = False) -> Cell:
    if hidden:
        return HIDDEN
    return MISSING if value is None else value


def report_tables(results: dict, generated_at: datetime) -> list[ReportTable]:
    assessment = results["assessment"]
    components = results["components"]
    categories = results["categories"]
    total = results["responses_total"]
    # /results не перелічує приховані категорії (D4): про приховування говорить лише прапорець
    suppressed = results.get("suppressed", any(item.get("hidden") for item in categories))
    tables = [
        ReportTable(
            "Підсумок", ("Показник", "Значення"),
            [
                ("Назва циклу", assessment["name"]),
                ("ID циклу", assessment["id"]),
                ("Стан циклу", "Закрито"),
                ("Сформовано (UTC)", generated_at.strftime("%Y-%m-%d %H:%M")),
                ("Поріг групи", results["min_group_size"]),
                ("Групи, менші за поріг", HIDDEN if suppressed else "Немає"),
                ("Анкет у циклі", _display(total, hidden=total is None)),
            ],
            (165, 340),
        ),
        ReportTable(
            "Бали компонентів", ("Код", "Компонент", "Бал (0–100)"),
            [(item["code"], item["name"], _display(item["score"], hidden=total is None))
             for item in components],
            (58, 340, 107),
        ),
    ]
    if not categories:
        return tables

    category_rows = [
        (CATEGORY_NAMES.get(item["category"], item["category"]), _display(item["responses"], hidden=item["hidden"]))
        for item in categories
    ]
    breakdown = []
    for component in components:
        scores = {item["category"]: item for item in component["by_category"]}
        for category in categories:
            code = category["category"]
            score = scores.get(code)
            hidden = category["hidden"] or (score is not None and score["hidden"])
            breakdown.append((
                component["code"], CATEGORY_NAMES.get(code, code),
                _display(score["score"] if score else None, hidden=hidden),
            ))
    tables.extend([
        ReportTable("Участь за категоріями", ("Категорія", "Анкет"), category_rows, (378, 127)),
        ReportTable("Бали за категоріями", ("Код", "Категорія", "Бал (0–100)"), breakdown, (58, 340, 107)),
    ])
    return tables


def render_pdf(tables: list[ReportTable], *, title: str = TITLE, notes: Sequence[str] = (NOTE,)) -> bytes:
    """Embed a Cyrillic font locally so the report works with no font service."""
    with PDF_LOCK:
        if PDF_FONT not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(PDF_FONT, str(FONT_PATH)))

        output = BytesIO()
        doc = SimpleDocTemplate(output, pagesize=A4, title=title, author="Integrity Management",
                                leftMargin=36, rightMargin=36, topMargin=33, bottomMargin=42)
        text = ParagraphStyle("Report", fontName=PDF_FONT, fontSize=9, leading=13, textColor=colors.HexColor(INK))
        title_style = ParagraphStyle("ReportTitle", parent=text, fontSize=19, leading=24, spaceAfter=7)
        heading = ParagraphStyle("ReportHeading", parent=text, fontSize=13, leading=17, spaceBefore=13,
                                 spaceAfter=6, keepWithNext=True)
        header = ParagraphStyle("ReportTableHeader", parent=text, textColor=colors.white)
        story = [Paragraph(escape(title), title_style), *(Paragraph(escape(note), text) for note in notes),
                 Spacer(1, 4)]
        for section in tables:
            story.append(Paragraph(section.name, heading))
            rows = [[Paragraph(escape(value), header) for value in section.headers]]
            rows.extend([Paragraph(escape(str(value)), text) for value in row] for row in section.rows)
            table = LongTable(rows, colWidths=section.pdf_widths, repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(GREEN)),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(PALE)]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LINEBELOW", (0, -1), (-1, -1), .5, colors.HexColor(LINE)),
            ]))
            story.append(table)

        def page_number(canvas, _doc):
            canvas.setFont(PDF_FONT, 8)
            canvas.setFillColor(colors.HexColor(INK))
            canvas.drawRightString(A4[0] - 42, 25, f"Сторінка {canvas.getPageNumber()}")

        doc.build(story, onFirstPage=page_number, onLaterPages=page_number)
        return output.getvalue()


def render_xlsx(tables: list[ReportTable]) -> bytes:
    return render_xlsx_book([XlsxSheet("Звіт", tables, (42, 54, 18), row_height=29)])


@dataclass(frozen=True)
class XlsxSheet:
    name: str
    tables: list[ReportTable]
    column_widths: tuple[int, ...]
    row_height: int | None = None          # None — висота за довжиною тексту (довгі пояснення)


def _row_height(row: tuple[Cell, ...], widths: tuple[int, ...]) -> int:
    lines = max((max(1, -(-len(str(value)) // max(width - 2, 1))) for value, width in zip(row, widths)), default=1)
    return min(15 * lines + 6, 300)


def render_xlsx_book(sheets: list[XlsxSheet], *, title: str = TITLE, notes: Sequence[str] = (NOTE,)) -> bytes:
    output = BytesIO()
    # Cycle titles are supplied by admins and must always remain literal text.
    with Workbook(output, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False}) as book:
        title_format = book.add_format({"bold": True, "font_size": 17, "font_color": INK})
        subtitle = book.add_format({"font_color": INK, "text_wrap": True, "valign": "vcenter"})
        heading = book.add_format({"bold": True, "font_size": 13, "font_color": GREEN})
        header = book.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": GREEN, "valign": "vcenter",
                                  "text_wrap": True})
        body = book.add_format({"font_color": INK, "bg_color": PALE, "text_wrap": True, "valign": "vcenter"})
        for spec in sheets:
            sheet = book.add_worksheet(spec.name)
            sheet.hide_gridlines(2)
            for column, width in enumerate(spec.column_widths):
                sheet.set_column(column, column, width)
            last = max(len(spec.column_widths) - 1, 0)
            sheet.merge_range(0, 0, 0, last, title, title_format)
            sheet.set_row(0, 27)
            row_index = 1
            for note in notes:
                sheet.merge_range(row_index, 0, row_index, last, note, subtitle)
                sheet.set_row(row_index, 29)
                row_index += 1
            frozen = row_index
            row_index += 1
            for table in spec.tables:
                sheet.write_string(row_index, 0, table.name, heading)
                sheet.write_row(row_index + 1, 0, table.headers, header)
                sheet.set_row(row_index + 1, 21 if spec.row_height else 33)
                row_index += 2
                for row in table.rows:
                    sheet.set_row(row_index, spec.row_height or _row_height(row, spec.column_widths))
                    for column, value in enumerate(row):
                        if isinstance(value, str):
                            sheet.write_string(row_index, column, value, body)
                        else:
                            sheet.write_number(row_index, column, value, body)
                    row_index += 1
                row_index += 1
            sheet.freeze_panes(frozen, 0)
    return output.getvalue()
