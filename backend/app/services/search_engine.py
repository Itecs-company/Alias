from __future__ import annotations

from dataclasses import dataclass
from typing import List

from loguru import logger
from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.part import Manufacturer, ManufacturerAlias, Part
from app.schemas.part import PartBase, SearchResult

from .document_parser import extract_from_urls
from .search_providers import (
    SearchProvider,
    get_default_providers,
    get_fallback_provider,
    get_google_provider,
)


@dataclass
class Candidate:
    manufacturer: str
    alias_used: str | None
    confidence: float
    source_url: str
    debug_log: str


class ManufacturerResolver:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def resolve(self, name: str) -> Manufacturer:
        stmt = select(Manufacturer).where(Manufacturer.name.ilike(name))
        result = await self.session.execute(stmt)
        manufacturer = result.scalar_one_or_none()
        if manufacturer:
            return manufacturer

        manufacturer = Manufacturer(name=name)
        self.session.add(manufacturer)
        await self.session.flush()
        return manufacturer

    async def sync_aliases(self, manufacturer: Manufacturer, aliases: List[str]) -> None:
        existing = {alias.name.lower(): alias for alias in manufacturer.aliases}
        for alias in aliases:
            if alias.lower() not in existing:
                manufacturer.aliases.append(ManufacturerAlias(name=alias))
        await self.session.flush()


class PartSearchEngine:
    def __init__(
        self,
        session: AsyncSession,
        providers: list[SearchProvider] | None = None,
        google_provider: SearchProvider | None = None,
        fallback_provider: SearchProvider | None = None,
    ):
        self.session = session
        self.providers = providers or get_default_providers()
        self.google_provider = google_provider or get_google_provider()
        self.fallback_provider = fallback_provider or get_fallback_provider()
        self.resolver = ManufacturerResolver(session)

    async def _search_with_provider(
        self, provider: SearchProvider, query: str, *, max_results: int = 5
    ) -> list[str]:
        try:
            results = await provider.search(query, max_results=max_results)
        except Exception:  # noqa: BLE001
            logger.exception("Provider %s failed", provider.name)
            return []
        return [item.get("link") for item in results if item.get("link")]

    async def _aggregate_urls(self, part: PartBase) -> list[str]:
        query = f"{part.part_number} {part.manufacturer_hint or ''} datasheet manufacturer"
        urls: list[str] = []
        for provider in self.providers:
            urls.extend(await self._search_with_provider(provider, query))
        if not urls and self.google_provider:
            urls.extend(await self._search_with_provider(self.google_provider, query))
        if not urls:
            urls.extend(await self._search_with_provider(self.fallback_provider, query))
        seen: set[str] = set()
        unique_urls: list[str] = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)
        return unique_urls

    async def _extract_candidates(self, part: PartBase) -> list[Candidate]:
        urls = await self._aggregate_urls(part)
        if not urls:
            return []
        contents = await extract_from_urls(urls[:6])
        candidates: list[Candidate] = []
        for url, text in contents.items():
            candidate = self._guess_manufacturer_from_text(text, part)
            if candidate:
                manufacturer, alias, confidence, debug = candidate
                candidates.append(
                    Candidate(
                        manufacturer=manufacturer,
                        alias_used=alias,
                        confidence=confidence,
                        source_url=url,
                        debug_log=debug,
                    )
                )
        return candidates

    def _guess_manufacturer_from_text(self, text: str, part: PartBase) -> tuple[str, str | None, float, str] | None:
        lines = text.splitlines()
        candidates = [line for line in lines if part.part_number.lower() in line.lower()]
        if not candidates and part.manufacturer_hint:
            candidates = [line for line in lines if part.manufacturer_hint.lower() in line.lower()]
        if not candidates:
            candidates = lines[:20]
        manufacturer_names: list[str] = []
        for line in candidates:
            tokens = [token.strip(" ,.;:()[]") for token in line.split() if token.isalpha()]
            if tokens:
                manufacturer_names.append(" ".join(tokens[:3]))
        if not manufacturer_names:
            return None
        alias = None
        if part.manufacturer_hint:
            match = process.extractOne(
                part.manufacturer_hint,
                manufacturer_names,
                scorer=fuzz.WRatio,
            )
            if match:
                alias = part.manufacturer_hint
                confidence = match[1] / 100
                manufacturer = match[0]
                debug = f"Matched alias '{alias}' with score {confidence:.2f}"
                return manufacturer, alias, confidence, debug
        top = process.extractOne(part.part_number, manufacturer_names, scorer=fuzz.partial_ratio)
        if top:
            manufacturer = top[0]
            confidence = top[1] / 100
            debug = f"Heuristic manufacturer from datasheet context score {confidence:.2f}"
            return manufacturer, alias, confidence, debug
        manufacturer = manufacturer_names[0]
        return manufacturer, alias, 0.3, "Fallback manufacturer selection"

    async def search_part(self, part: PartBase, *, debug: bool = False) -> SearchResult:
        candidates = await self._extract_candidates(part)
        if not candidates:
            return SearchResult(
                part_number=part.part_number,
                manufacturer_name=None,
                alias_used=part.manufacturer_hint,
                confidence=None,
                source_url=None,
                debug_log="No sources found",
            )
        best = max(candidates, key=lambda c: c.confidence)
        manufacturer = await self.resolver.resolve(best.manufacturer)
        if best.alias_used:
            await self.resolver.sync_aliases(manufacturer, [best.alias_used])
        manufacturer_name = manufacturer.name
        new_part = Part(
            part_number=part.part_number,
            manufacturer=manufacturer,
            manufacturer_name=manufacturer_name,
            alias_used=best.alias_used,
            confidence=best.confidence,
            source_url=best.source_url,
            debug_log=best.debug_log if debug else None,
        )
        self.session.add(new_part)
        await self.session.flush()
        return SearchResult(
            part_number=part.part_number,
            manufacturer_name=manufacturer_name,
            alias_used=best.alias_used,
            confidence=best.confidence,
            source_url=best.source_url,
            debug_log=best.debug_log if debug else None,
        )

    async def search_many(self, items: list[PartBase], *, debug: bool = False) -> list[SearchResult]:
        results: list[SearchResult] = []
        for item in items:
            results.append(await self.search_part(item, debug=debug))
        return results
