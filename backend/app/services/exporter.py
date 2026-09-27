from __future__ import annotations

import asyncio
from pathlib import Path

import pandas as pd
from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.part import Part

settings = get_settings()

COLUMNS = ["Article", "Manufacturer", "Alias", "Req.Mnfc", "Match", "What Produces", "Website", "Manufacturer Aliases", "Country"]
PDF_HEADERS = ["Article", "Manufacturer", "Alias", "Req.Mnfc", "Match", "What Produces", "Website", "Aliases", "Country"]
PDF_COL_WIDTHS = [30, 35, 25, 30, 28, 40, 35, 30, 24]  # сумма 277 мм (A4 альбомная)
FONT_CANDIDATES = (
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
)


def _match_label(part: Part) -> str:
    if part.match_status == "matched":
        label = "Совпадает"
    elif part.match_status == "mismatch":
        label = "Расхождение"
    elif part.match_status == "pending":
        return "Ожидание проверки"
    else:
        return "—"
    if part.match_confidence:
        label += f" ({part.match_confidence * 100:.1f}%)"
    return label


def _build_table_rows(parts: list[Part]) -> list[dict[str, str]]:
    return [
        {
            "Article": part.part_number,
            "Manufacturer": part.manufacturer_name or "—",
            "Alias": part.alias_used or "—",
            "Req.Mnfc": part.submitted_manufacturer or "—",
            "Match": _match_label(part),
            "What Produces": part.what_produces or "—",
            "Website": part.website or "—",
            "Manufacturer Aliases": part.manufacturer_aliases or "—",
            "Country": part.country or "—",
        }
        for part in parts
    ]


async def _load_rows(session: AsyncSession) -> list[dict[str, str]]:
    result = await session.execute(select(Part).order_by(Part.id))
    return _build_table_rows(list(result.scalars().all()))


def _write_excel(rows: list[dict[str, str]], path: Path) -> None:
    df = pd.DataFrame(rows, columns=COLUMNS)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Parts")
        sheet = writer.sheets["Parts"]
        for index, column in enumerate(COLUMNS, start=1):
            longest = max([len(column), *(len(str(value)) for value in df[column].tolist()[:500])])
            sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = min(60, longest + 2)
        sheet.freeze_panes = "A2"


async def export_parts_to_excel(session: AsyncSession) -> Path:
    rows = await _load_rows(session)
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    export_path = settings.storage_dir / "export.xlsx"
    await asyncio.to_thread(_write_excel, rows, export_path)
    return export_path


def _wrap_text(text: str, max_width: float, pdf: FPDF) -> list[str]:
    """Разбивает текст на строки по ширине ячейки (длинные слова/URL режутся по символам)."""
    usable = max_width - 4  # отступы
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if pdf.get_string_width(candidate) <= usable:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        while pdf.get_string_width(word) > usable and len(word) > 1:
            cut = len(word)
            while cut > 1 and pdf.get_string_width(word[:cut]) > usable:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        current = word
    if current:
        lines.append(current)
    return lines or [""]


def _write_pdf(rows: list[dict[str, str]], path: Path) -> None:
    pdf = FPDF(orientation="L")
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(10, 10, 10)

    font_name = "Helvetica"
    for regular, bold in FONT_CANDIDATES:
        if Path(regular).exists() and Path(bold).exists():
            pdf.add_font("DejaVu", "", regular)
            pdf.add_font("DejaVu", "B", bold)
            font_name = "DejaVu"
            break

    def safe(text: str) -> str:
        # Встроенный Helvetica поддерживает только latin-1
        if font_name == "Helvetica":
            return text.encode("latin-1", "replace").decode("latin-1")
        return text

    def header() -> None:
        pdf.set_font(font_name, style="B", size=9)
        for title, width in zip(PDF_HEADERS, PDF_COL_WIDTHS):
            pdf.cell(width, 10, safe(title), border=1, align="C")
        pdf.ln()
        pdf.set_font(font_name, size=8)

    pdf.add_page()
    pdf.set_font(font_name, style="B", size=14)
    pdf.cell(0, 10, safe("Сводная таблица производителей"), new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(2)
    header()

    line_height = 5
    bottom = pdf.h - pdf.b_margin
    if not rows:
        pdf.cell(sum(PDF_COL_WIDTHS), 10, safe("Данные отсутствуют"), border=1, align="C")
        pdf.ln()
    for row in rows:
        cells = [safe(str(row[key])) for key in COLUMNS]
        wrapped = [_wrap_text(text, width, pdf) for text, width in zip(cells, PDF_COL_WIDTHS)]
        max_lines = min(max(len(lines) for lines in wrapped), 20)
        row_height = max(8, max_lines * line_height + 2)
        if pdf.get_y() + row_height > bottom:
            pdf.add_page()
            header()
        start_x, start_y = pdf.l_margin, pdf.get_y()
        offset = 0.0
        for lines, width in zip(wrapped, PDF_COL_WIDTHS):
            x = start_x + offset
            pdf.rect(x, start_y, width, row_height)
            visible = lines[:max_lines]
            text_y = start_y + (row_height - len(visible) * line_height) / 2
            for index, line in enumerate(visible):
                pdf.set_xy(x + 2, text_y + index * line_height)
                pdf.cell(width - 4, line_height, line, border=0)
            offset += width
        pdf.set_xy(start_x, start_y + row_height)

    pdf.output(str(path))


async def export_parts_to_pdf(session: AsyncSession) -> Path:
    rows = await _load_rows(session)
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    export_path = settings.storage_dir / "export.pdf"
    await asyncio.to_thread(_write_pdf, rows, export_path)
    return export_path
