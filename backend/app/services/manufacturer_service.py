"""Работа с производителями в БД и справочная информация о них."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, fields

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import ci_equals
from app.models.part import Manufacturer, ManufacturerAlias, Part
from app.services.ai import ai_available, chat_json
from app.services.log_recorder import SearchLogRecorder
from app.services.manufacturers import manufacturer_info_from_dictionary


@dataclass
class ManufacturerInfo:
    """Дополнительная информация о производителе"""

    what_produces: str | None = None
    website: str | None = None
    manufacturer_aliases: str | None = None
    country: str | None = None

    @property
    def complete(self) -> bool:
        return bool(self.what_produces and self.country)

    def merged_with(self, other: "ManufacturerInfo") -> "ManufacturerInfo":
        return ManufacturerInfo(**{f.name: getattr(self, f.name) or getattr(other, f.name) for f in fields(self)})


class ManufacturerResolver:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def resolve(self, name: str) -> Manufacturer:
        stmt = (
            select(Manufacturer)
            .options(selectinload(Manufacturer.aliases))
            .where(ci_equals(Manufacturer.name, name.strip()))
            .order_by(Manufacturer.id)
            .limit(1)
        )
        manufacturer = (await self.session.execute(stmt)).scalars().first()
        if manufacturer:
            return manufacturer

        manufacturer = Manufacturer(name=name.strip())
        self.session.add(manufacturer)
        await self.session.flush()
        return manufacturer

    async def sync_aliases(self, manufacturer: Manufacturer, aliases: list[str]) -> None:
        aliases = [alias.strip() for alias in aliases if alias and alias.strip()]
        if not aliases:
            return
        stmt = select(ManufacturerAlias).where(ManufacturerAlias.manufacturer_id == manufacturer.id)
        existing = {alias.name.lower() for alias in (await self.session.execute(stmt)).scalars()}
        existing.add(manufacturer.name.lower())
        for alias in aliases:
            if alias.lower() not in existing:
                self.session.add(ManufacturerAlias(name=alias, manufacturer_id=manufacturer.id))
                existing.add(alias.lower())
        await self.session.flush()


# Информация о производителях общая для всех запросов и почти не меняется
_INFO_CACHE: dict[str, ManufacturerInfo] = {}
_INFO_CACHE_LIMIT = 5000


def _clean(value: object, limit: int = 255) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "unknown", "n/a", "неизвестно"}:
        return None
    return text[:limit]


class ManufacturerInfoExtractor:
    """Справочная информация о производителе: справочник → БД → OpenAI (с кешем)."""

    def __init__(self, session: AsyncSession | None = None, *, db_lock: asyncio.Lock | None = None,
                 recorder: SearchLogRecorder | None = None, use_ai: bool | None = None):
        self.session = session
        self.db_lock = db_lock or asyncio.Lock()
        self.recorder = recorder
        self.use_ai = ai_available() if use_ai is None else use_ai
        self._inflight: dict[str, asyncio.Task[ManufacturerInfo]] = {}

    async def extract_info(self, manufacturer_name: str) -> ManufacturerInfo:
        key = manufacturer_name.strip().lower()
        if not key:
            return ManufacturerInfo()
        cached = _INFO_CACHE.get(key)
        if cached is not None:
            return cached
        # Параллельные поиски одного производителя разделяют один запрос
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.ensure_future(self._load(manufacturer_name))
            self._inflight[key] = task
        try:
            info = await task
        finally:
            self._inflight.pop(key, None)
        # Пустой результат (например, временная ошибка OpenAI) не кешируем
        if any(getattr(info, f.name) for f in fields(info)):
            if len(_INFO_CACHE) >= _INFO_CACHE_LIMIT:
                _INFO_CACHE.clear()
            _INFO_CACHE[key] = info
        return info

    async def _load(self, name: str) -> ManufacturerInfo:
        info = ManufacturerInfo(**manufacturer_info_from_dictionary(name))
        if info.complete:
            return info
        stored = await self._from_database(name)
        if stored is not None:
            info = stored.merged_with(info)
            if info.complete:
                return info
        if self.use_ai:
            ai_info = await self._from_openai(name)
            info = info.merged_with(ai_info)
        return info

    async def _from_database(self, name: str) -> ManufacturerInfo | None:
        if self.session is None:
            return None
        stmt = (
            select(Part)
            .where(ci_equals(Part.manufacturer_name, name), Part.what_produces.is_not(None))
            .order_by(Part.id.desc())
            .limit(1)
        )
        async with self.db_lock:
            part = (await self.session.execute(stmt)).scalars().first()
        if part is None:
            return None
        return ManufacturerInfo(
            what_produces=part.what_produces,
            website=part.website,
            manufacturer_aliases=part.manufacturer_aliases,
            country=part.country,
        )

    async def _from_openai(self, name: str) -> ManufacturerInfo:
        messages = [
            {
                "role": "system",
                "content": (
                    "Ты эксперт по производителям электроники и промышленного оборудования. "
                    "Ответь только JSON: {\"what_produces\": \"что производит, до 60 символов, по-русски\", "
                    "\"website\": \"официальный сайт (URL)\", \"aliases\": \"другие названия через запятую\", "
                    "\"country\": \"страна штаб-квартиры по-русски\"}. Если не знаешь — null."
                ),
            },
            {"role": "user", "content": f"Производитель: {name}"},
        ]
        data = await chat_json(messages, max_tokens=150, recorder=self.recorder, provider="openai-info", query=name)
        if not data:
            return ManufacturerInfo()
        website = _clean(data.get("website"), 500)
        if website and not website.startswith(("http://", "https://")):
            website = "https://" + website
        info = ManufacturerInfo(
            what_produces=_clean(data.get("what_produces")),
            website=website,
            manufacturer_aliases=_clean(data.get("aliases")),
            country=_clean(data.get("country")),
        )
        logger.debug("Manufacturer info for {name}: {info}", name=name, info=info)
        return info
