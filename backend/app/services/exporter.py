from __future__ import annotations

from pathlib import Path

import pandas as pd
from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.part import Part

settings = get_settings()


async def export_parts_to_excel(session: AsyncSession) -> Path:
    stmt = select(Part)
    result = await session.execute(stmt)
    parts = result.scalars().all()
    df = pd.DataFrame(
        [
            {
                "part_number": part.part_number,
                "manufacturer_name": part.manufacturer_name,
                "alias_used": part.alias_used,
                "confidence": part.confidence,
                "source_url": part.source_url,
            }
            for part in parts
        ]
    )
    export_path = settings.storage_dir / "export.xlsx"
    df.to_excel(export_path, index=False)
    return export_path


async def export_parts_to_pdf(session: AsyncSession) -> Path:
    stmt = select(Part)
    result = await session.execute(stmt)
    parts = result.scalars().all()

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=14)
    pdf.cell(0, 10, "AliasFinder Export", ln=True)

    pdf.set_font("Helvetica", size=10)
    for part in parts:
        pdf.cell(0, 6, f"Part: {part.part_number}", ln=True)
        pdf.cell(0, 6, f"Manufacturer: {part.manufacturer_name or '-'}", ln=True)
        pdf.cell(0, 6, f"Alias used: {part.alias_used or '-'}", ln=True)
        pdf.cell(0, 6, f"Confidence: {part.confidence if part.confidence is not None else '-'}", ln=True)
        pdf.multi_cell(0, 6, f"Source: {part.source_url or '-'}")
        pdf.ln(4)

    export_path = settings.storage_dir / "export.pdf"
    pdf.output(export_path)
    return export_path
