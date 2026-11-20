"""Build both export formats from the canonical, already suppressed aggregates."""

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
    tables = [
        ReportTable(
            "Підсумок", ("Показник", "Значення"),
            [
                ("Назва циклу", assessment["name"]),
                ("ID циклу", assessment["id"]),
                ("Стан циклу", "Закрито"),
                ("Сформовано (UTC)", generated_at.strftime("%Y-%m-%d %H:%M")),
                ("Поріг групи", results["min_group_size"]),
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


def render_pdf(tables: list[ReportTable]) -> bytes:
    """Embed a Cyrillic font locally so the report works with no font service."""
    with PDF_LOCK:
        if PDF_FONT not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(PDF_FONT, str(FONT_PATH)))

        output = BytesIO()
        doc = SimpleDocTemplate(output, pagesize=A4, title=TITLE, author="Integrity Management",
                                leftMargin=36, rightMargin=36, topMargin=33, bottomMargin=42)
        text = ParagraphStyle("Report", fontName=PDF_FONT, fontSize=9, leading=13, textColor=colors.HexColor(INK))
        title = ParagraphStyle("ReportTitle", parent=text, fontSize=19, leading=24, spaceAfter=7)
        heading = ParagraphStyle("ReportHeading", parent=text, fontSize=13, leading=17, spaceBefore=13,
                                 spaceAfter=6, keepWithNext=True)
        header = ParagraphStyle("ReportTableHeader", parent=text, textColor=colors.white)
        story = [Paragraph(TITLE, title), Paragraph(NOTE, text), Spacer(1, 4)]
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
    output = BytesIO()
    # Cycle titles are supplied by admins and must always remain literal text.
    with Workbook(output, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False}) as book:
        sheet = book.add_worksheet("Звіт")
        sheet.hide_gridlines(2)
        sheet.set_column("A:A", 42)
        sheet.set_column("B:B", 54)
        sheet.set_column("C:C", 18)
        title = book.add_format({"bold": True, "font_size": 17, "font_color": INK})
        subtitle = book.add_format({"font_color": INK, "text_wrap": True, "valign": "vcenter"})
        heading = book.add_format({"bold": True, "font_size": 13, "font_color": GREEN})
        header = book.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": GREEN, "valign": "vcenter"})
        body = book.add_format({"font_color": INK, "bg_color": PALE, "text_wrap": True, "valign": "vcenter"})
        sheet.merge_range("A1:C1", TITLE, title)
        sheet.merge_range("A2:C2", NOTE, subtitle)
        sheet.set_row(0, 27)
        sheet.set_row(1, 29)
        row_index = 3
        for table in tables:
            sheet.write_string(row_index, 0, table.name, heading)
            sheet.write_row(row_index + 1, 0, table.headers, header)
            sheet.set_row(row_index + 1, 21)
            row_index += 2
            for row in table.rows:
                sheet.set_row(row_index, 29)
                for column, value in enumerate(row):
                    if isinstance(value, str):
                        sheet.write_string(row_index, column, value, body)
                    else:
                        sheet.write_number(row_index, column, value, body)
                row_index += 1
            row_index += 1
        sheet.freeze_panes(2, 0)
    return output.getvalue()
