from __future__ import annotations

from io import BytesIO

import pandas as pd
from fastapi import UploadFile
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.part import Part
from app.schemas.part import PartCreate

from .search_engine import PartSearchEngine


def _normalize(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


async def import_parts_from_excel(
    session: AsyncSession,
    file: UploadFile,
    *,
    debug: bool = False,
) -> tuple[int, int, list[str]]:
    content = await file.read()
    df = pd.read_excel(BytesIO(content))
    required_columns = {"part_number", "manufacturer_hint"}
    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {', '.join(missing)}")

    imported = 0
    skipped = 0
    errors: list[str] = []
    engine = PartSearchEngine(session)
    for _, row in df.iterrows():
        part_number = _normalize(row["part_number"])
        if not part_number:
            skipped += 1
            continue
        item = PartCreate(part_number=part_number, manufacturer_hint=_normalize(row.get("manufacturer_hint")))
        stmt = select(Part).where(Part.part_number == item.part_number)
        result = await session.execute(stmt)
        if result.scalar_one_or_none():
            skipped += 1
            continue
        try:
            await engine.search_part(item, debug=debug)
            imported += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to import part {part}", part=item.part_number)
            errors.append(str(exc))
    await session.commit()
    return imported, skipped, errors
