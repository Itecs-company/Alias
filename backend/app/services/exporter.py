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
                "Req.Mnfc": submitted,
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
    columns = ["Article", "Manufacturer", "Alias", "Req.Mnfc", "Match", "What Produces", "Website", "Manufacturer Aliases", "Country"]
    df = pd.DataFrame(_build_table_rows(parts), columns=columns)
    export_path = settings.storage_dir / "export.xlsx"
    df.to_excel(export_path, index=False)
    return export_path


def _wrap_text(text: str, max_width: int, pdf: FPDF) -> list[str]:
    """Разбивает текст на строки, чтобы он помещался в заданную ширину."""
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test_line = current_line + " " + word if current_line else word
        if pdf.get_string_width(test_line) <= max_width - 4:  # -4 для отступов
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines if lines else [text[:30]]  # Если текст не разбился, обрезаем


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
    headers = ["Article", "Manufacturer", "Alias", "Req.Mnfc", "Match", "What Produces", "Website", "Aliases", "Country"]
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
            # Подготавливаем данные для ячеек
            cells_data = [
                str(row["Article"]),
                str(row["Manufacturer"]),
                str(row["Alias"]),
                str(row["Req.Mnfc"]),
                str(row["Match"]),
                str(row["What Produces"]),
                str(row["Website"]),
                str(row["Manufacturer Aliases"]),
                str(row["Country"])
            ]

            # Разбиваем длинный текст на строки для каждой ячейки
            wrapped_cells = []
            max_lines = 1
            for i, (text, width) in enumerate(zip(cells_data, col_widths)):
                lines = _wrap_text(text, width, pdf)
                wrapped_cells.append(lines)
                max_lines = max(max_lines, len(lines))

            # Рассчитываем высоту строки (минимум 8, + дополнительно для каждой строки)
            row_height = max(8, max_lines * 5)

            # Запоминаем начальную позицию Y
            start_y = pdf.get_y()
            start_x = pdf.get_x()

            # Рисуем каждую ячейку
            for i, (lines, width) in enumerate(zip(wrapped_cells, col_widths)):
                # Позиционируем курсор для каждой ячейки
                current_x = start_x + sum(col_widths[:i])
                pdf.set_xy(current_x, start_y)

                # Рисуем границу ячейки
                pdf.rect(current_x, start_y, width, row_height)

                # Выводим текст построчно с вертикальным центрированием
                text_y_offset = (row_height - len(lines) * 5) / 2
                for line_idx, line in enumerate(lines):
                    pdf.set_xy(current_x + 2, start_y + text_y_offset + line_idx * 5)
                    pdf.cell(width - 4, 5, line, border=0)

            # Переходим на следующую строку
            pdf.set_xy(start_x, start_y + row_height)

    export_path = settings.storage_dir / "export.pdf"
    pdf.output(export_path)
    return export_path
