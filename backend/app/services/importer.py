from __future__ import annotations

from io import BytesIO

import pandas as pd
from fastapi import UploadFile
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.part import PartCreate

from .search_engine import PartSearchEngine


def _normalize_column_name(name: str) -> str:
    return "".join(ch.lower() for ch in name if ch.isalnum())


COLUMN_ALIASES: dict[str, set[str]] = {
    "part_number": {
        "partnumber",
        "article",
        "артикул",
        "articul",
    },
    "manufacturer_hint": {
        "manufacturerhint",
        "manufacturer",
        "alias",
        "manufactureralias",
        "manufacturernalias",
        "manufactureralias",
        "manufactureroralias",
        "manufactureraliashint",
        "произв",
        "производитель",
        "алиас",
        "производительалиас",
    },
}


IGNORED_COLUMNS = {"№", "no", "номер", "number"}


def _should_ignore_column(name: str) -> bool:
    raw = str(name).strip().lower()
    normalized = _normalize_column_name(str(name))
    return raw in IGNORED_COLUMNS or normalized in IGNORED_COLUMNS or "№" in raw


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
) -> tuple[int, int, list[str], str]:
    display_name = file.filename or "Excel"
    content = await file.read()
    df = pd.read_excel(BytesIO(content))

    column_mapping: dict[str, str] = {}
    for column in df.columns:
        if _should_ignore_column(str(column)):
            continue
        normalized = _normalize_column_name(str(column))
        for target, aliases in COLUMN_ALIASES.items():
            if normalized in aliases and target not in column_mapping:
                column_mapping[target] = column

    if "part_number" not in column_mapping:
        raise ValueError(
            "Не удалось найти столбец с артикулами. Убедитесь, что используется колонка 'Article' или 'part_number'."
        )

    imported = 0
    skipped = 0
    errors: list[str] = []
    engine = PartSearchEngine(session)
    for _, row in df.iterrows():
        part_number = _normalize(row[column_mapping["part_number"]])
        if not part_number:
            skipped += 1
            continue
        manufacturer_hint_column = column_mapping.get("manufacturer_hint")
        manufacturer_hint = (
            _normalize(row[manufacturer_hint_column]) if manufacturer_hint_column else None
        )
        item = PartCreate(part_number=part_number, manufacturer_hint=manufacturer_hint)
        try:
            await engine.search_part(item, debug=debug)
            imported += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to import part {part}", part=item.part_number)
            errors.append(str(exc))
    await session.commit()
    status_message = f"Файл {display_name} обработан: {imported} записей"
    return imported, skipped, errors, status_message
