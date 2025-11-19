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
        manufacturer = part.manufacturer_name or ""
        alias = part.alias_used or ""
        combined = " / ".join(filter(None, [manufacturer, alias])) or "—"
        rows.append({"Article": part.part_number, "Manufacturer/Alias": combined})
    return rows


async def export_parts_to_excel(session: AsyncSession) -> Path:
    stmt = select(Part)
    result = await session.execute(stmt)
    parts = result.scalars().all()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(_build_table_rows(parts), columns=["Article", "Manufacturer/Alias"])
    export_path = settings.storage_dir / "export.xlsx"
    df.to_excel(export_path, index=False)
    return export_path


async def export_parts_to_pdf(session: AsyncSession) -> Path:
    stmt = select(Part)
    result = await session.execute(stmt)
    parts = result.scalars().all()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)

    rows = _build_table_rows(parts)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", style="B", size=14)
    pdf.cell(0, 10, "Сводная таблица производителей", ln=True, align="C")
    pdf.ln(2)

    headers = ["Article", "Manufacturer/Alias"]
    col_widths = [65, 130]
    pdf.set_font("Helvetica", style="B", size=11)
    for header, width in zip(headers, col_widths):
        pdf.cell(width, 10, header, border=1, align="C")
    pdf.ln()

    pdf.set_font("Helvetica", size=10)
    if not rows:
        pdf.cell(sum(col_widths), 10, "Данные отсутствуют", border=1, align="C")
        pdf.ln()
    else:
        for row in rows:
            pdf.cell(col_widths[0], 8, str(row["Article"]), border=1)
            pdf.cell(col_widths[1], 8, str(row["Manufacturer/Alias"]), border=1, ln=1)

    export_path = settings.storage_dir / "export.pdf"
    pdf.output(export_path)
    return export_path
