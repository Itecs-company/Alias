from __future__ import annotations

from pathlib import Path

import pandas as pd
from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.part import Part

settings = get_settings()


def _build_table_rows(parts: list[Part]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for part in parts:
        manufacturer = part.manufacturer_name or "—"
        alias = part.alias_used or "—"
        submitted = part.submitted_manufacturer or "—"
        if part.match_status == "matched":
            match = "Совпадает"
            if part.match_confidence:
                match = f"Совпадает ({part.match_confidence * 100:.1f}%)"
        elif part.match_status == "mismatch":
            match = "Расхождение"
            if part.match_confidence:
                match = f"Расхождение ({part.match_confidence * 100:.1f}%)"
        elif part.match_status == "pending":
            match = "Ожидание проверки"
        else:
            match = "—"
        rows.append(
            {
                "Article": part.part_number,
                "Manufacturer": manufacturer,
                "Alias": alias,
                "Submitted": submitted,
                "Match": match,
                "What Produces": part.what_produces or "—",
                "Website": part.website or "—",
                "Manufacturer Aliases": part.manufacturer_aliases or "—",
                "Country": part.country or "—",
            }
        )
    return rows


async def export_parts_to_excel(session: AsyncSession) -> Path:
    stmt = select(Part)
    result = await session.execute(stmt)
    parts = result.scalars().all()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    columns = ["Article", "Manufacturer", "Alias", "Submitted", "Match", "What Produces", "Website", "Manufacturer Aliases", "Country"]
    df = pd.DataFrame(_build_table_rows(parts), columns=columns)
    export_path = settings.storage_dir / "export.xlsx"
    df.to_excel(export_path, index=False)
    return export_path


async def export_parts_to_pdf(session: AsyncSession) -> Path:
    stmt = select(Part)
    result = await session.execute(stmt)
    parts = result.scalars().all()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)

    rows = _build_table_rows(parts)

    # Создаем PDF с поддержкой Unicode в альбомной ориентации
    pdf = FPDF(orientation="L")  # L = Landscape (альбомная ориентация)
    pdf.set_auto_page_break(auto=True, margin=15)

    # Добавляем шрифты DejaVu с поддержкой кириллицы
    try:
        pdf.add_font("DejaVu", "", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
        pdf.add_font("DejaVu", "B", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        font_name = "DejaVu"
    except Exception:
        # Если не удалось загрузить DejaVu, используем стандартный шрифт
        font_name = "Helvetica"

    pdf.add_page()

    pdf.set_font(font_name, style="B", size=14)
    pdf.cell(0, 10, "Сводная таблица производителей", ln=True, align="C")
    pdf.ln(2)

    # Увеличенная ширина колонок для альбомной ориентации (общая ширина ~277mm)
    headers = ["Article", "Manufacturer", "Alias", "Submitted", "Match", "What Produces", "Website", "Aliases", "Country"]
    col_widths = [30, 35, 25, 30, 28, 40, 35, 30, 24]  # Сумма: 277mm
    pdf.set_font(font_name, style="B", size=9)
    for header, width in zip(headers, col_widths):
        pdf.cell(width, 10, header, border=1, align="C")
    pdf.ln()

    pdf.set_font(font_name, size=8)
    if not rows:
        pdf.cell(sum(col_widths), 10, "Данные отсутствуют", border=1, align="C")
        pdf.ln()
    else:
        for row in rows:
            pdf.cell(col_widths[0], 8, str(row["Article"]), border=1)
            pdf.cell(col_widths[1], 8, str(row["Manufacturer"]), border=1)
            pdf.cell(col_widths[2], 8, str(row["Alias"]), border=1)
            pdf.cell(col_widths[3], 8, str(row["Submitted"]), border=1)
            pdf.cell(col_widths[4], 8, str(row["Match"]), border=1)
            pdf.cell(col_widths[5], 8, str(row["What Produces"])[:25], border=1)
            pdf.cell(col_widths[6], 8, str(row["Website"])[:25], border=1)
            pdf.cell(col_widths[7], 8, str(row["Manufacturer Aliases"])[:20], border=1)
            pdf.cell(col_widths[8], 8, str(row["Country"]), border=1, ln=1)

    export_path = settings.storage_dir / "export.pdf"
    pdf.output(export_path)
    return export_path
