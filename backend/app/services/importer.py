from __future__ import annotations

import asyncio
import re
from io import BytesIO

import pandas as pd
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.part import PartCreate

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _normalize_column_name(name: str) -> str:
    return "".join(ch.lower() for ch in name if ch.isalnum())


COLUMN_ALIASES: dict[str, set[str]] = {
    "part_number": {
        "partnumber",
        "partno",
        "pn",
        "mpn",
        "article",
        "articlenumber",
        "артикул",
        "articul",
        "артикулпроизводителя",
        "каталожныйномер",
        "партномер",
    },
    "manufacturer_hint": {
        "manufacturerhint",
        "manufacturer",
        "manufacturername",
        "alias",
        "manufactureralias",
        "manufacturernalias",
        "manufactureroralias",
        "manufactureraliashint",
        "reqmnfc",
        "submittedmanufacturer",
        "submitted",
        "brand",
        "vendor",
        "произв",
        "производитель",
        "алиас",
        "производительалиас",
        "бренд",
        "марка",
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
    if isinstance(value, float):
        if pd.isna(value):
            return None
        if value.is_integer():
            value = int(value)
    text = " ".join(str(value).split())
    # Числовые артикулы, прочитанные как float: "6030646.0" -> "6030646"
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    if text.lower() in {"nan", "none", "null"}:
        return None
    return text or None


def _read_table(content: bytes, filename: str) -> pd.DataFrame:
    if filename.lower().endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        return pd.read_csv(BytesIO(text.encode("utf-8")), dtype=str, sep=None, engine="python")
    return pd.read_excel(BytesIO(content), dtype=str)


def _parse_rows(content: bytes, filename: str) -> tuple[int, list[str], list[PartCreate]]:
    try:
        df = _read_table(content, filename)
    except Exception as exc:  # noqa: BLE001 - любые ошибки формата файла
        raise ValueError(f"Не удалось прочитать файл «{filename}»: {exc}") from exc

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

    skipped = 0
    errors: list[str] = []
    items: list[PartCreate] = []
    seen: set[tuple[str, str]] = set()
    hint_column = column_mapping.get("manufacturer_hint")
    for index, row in enumerate(df.itertuples(index=False, name=None), start=2):
        record = dict(zip(df.columns, row))
        part_number = _normalize(record.get(column_mapping["part_number"]))
        if not part_number:
            skipped += 1
            continue
        hint = _normalize(record.get(hint_column)) if hint_column else None
        if len(part_number) > 255:
            errors.append(f"Строка {index}: слишком длинный артикул")
            skipped += 1
            continue
        key = (part_number.upper(), (hint or "").lower())
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        items.append(PartCreate(part_number=part_number, manufacturer_hint=hint[:255] if hint else None))
    return skipped, errors, items


async def import_parts_from_excel(
    session: AsyncSession,
    file: UploadFile,
    *,
    debug: bool = False,
) -> tuple[int, int, list[str], str, list[PartCreate]]:
    display_name = file.filename or "Excel"
    content = await file.read()
    if not content:
        raise ValueError("Файл пустой")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("Файл слишком большой (максимум 20 МБ)")
    # Разбор Excel — CPU-задача, не блокируем event loop
    skipped, errors, items = await asyncio.to_thread(_parse_rows, content, display_name)
    imported = len(items)
    status_message = f"Файл {display_name} обработан: {imported} записей"
    if skipped:
        status_message += f", пропущено: {skipped}"
    return imported, skipped, errors, status_message, items
