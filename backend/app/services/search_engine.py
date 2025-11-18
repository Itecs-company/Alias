from __future__ import annotations

from dataclasses import dataclass
from typing import List

from loguru import logger
from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.part import Manufacturer, ManufacturerAlias, Part
from app.schemas.part import PartBase, SearchResult, StageStatus

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


@dataclass
class StageConfig:
    name: str
    providers: list[SearchProvider]
    confidence_threshold: float | None = None


@dataclass
class StageEvaluation:
    name: str
    provider_names: list[str]
    urls_considered: int
    candidate: Candidate | None


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

    async def _collect_urls(self, part: PartBase, providers: list[SearchProvider]) -> list[str]:
        query = f"{part.part_number} {part.manufacturer_hint or ''} datasheet manufacturer"
        urls: list[str] = []
        for provider in providers:
            urls.extend(await self._search_with_provider(provider, query))
        seen: set[str] = set()
        unique_urls: list[str] = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        return unique_urls

    async def _candidates_from_urls(self, part: PartBase, urls: list[str]) -> list[Candidate]:
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

    async def _search_stage(
        self, part: PartBase, providers: list[SearchProvider], stage_name: str
    ) -> StageEvaluation:
        if not providers:
            return StageEvaluation(stage_name, [], 0, None)
        urls = await self._collect_urls(part, providers)
        candidates = await self._candidates_from_urls(part, urls)
        best = max(candidates, key=lambda c: c.confidence) if candidates else None
        return StageEvaluation(stage_name, [provider.name for provider in providers], len(urls), best)

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
        stage_history: list[StageStatus] = []
        final_candidate: Candidate | None = None
        final_stage: str | None = None
        fallback_candidate: Candidate | None = None
        fallback_stage: str | None = None

        stage_configs: list[StageConfig] = [StageConfig("Internet", self.providers)]
        stage_configs.append(
            StageConfig(
                "googlesearch",
                [self.google_provider] if self.google_provider else [],
                confidence_threshold=0.67,
            )
        )

        skip_remaining = False
        for config in stage_configs:
            if skip_remaining:
                stage_history.append(
                    StageStatus(
                        name=config.name,
                        status="skipped",
                        message="Этап не выполнялся после получения результата",
                    )
                )
                continue
            if not config.providers:
                stage_history.append(
                    StageStatus(
                        name=config.name,
                        status="skipped",
                        message="Нет доступных поисковых провайдеров",
                    )
                )
                continue
            evaluation = await self._search_stage(part, config.providers, config.name)
            candidate = evaluation.candidate
            status = "no-results"
            message: str | None = None
            if evaluation.urls_considered == 0:
                message = "Поиск не вернул подходящих ссылок"
            elif not candidate:
                message = "Получены данные, но производитель не определен"
            else:
                if config.confidence_threshold and candidate.confidence < config.confidence_threshold:
                    status = "low-confidence"
                    message = (
                        f"Достоверность {candidate.confidence:.2f} ниже порога "
                        f"{config.confidence_threshold:.2f}. Переход к следующему этапу"
                    )
                    fallback_candidate = candidate
                    fallback_stage = config.name
                else:
                    status = "success"
                    final_candidate = candidate
                    final_stage = config.name
            stage_history.append(
                StageStatus(
                    name=config.name,
                    status=status,
                    confidence=candidate.confidence if candidate else None,
                    provider=", ".join(evaluation.provider_names) or None,
                    urls_considered=evaluation.urls_considered,
                    message=message,
                )
            )
            if final_candidate:
                skip_remaining = True

        if final_candidate:
            stage_history.append(
                StageStatus(
                    name="OpenAI",
                    status="skipped",
                    message="OpenAI не потребовался",
                )
            )
        else:
            evaluation = await self._search_stage(part, [self.fallback_provider], "OpenAI")
            candidate = evaluation.candidate
            status = "no-results"
            message: str | None = None
            if not evaluation.provider_names:
                status = "skipped"
                message = "OpenAI недоступен"
            elif evaluation.urls_considered == 0:
                message = "OpenAI не вернул полезных ссылок"
            elif not candidate:
                message = "OpenAI не смог определить производителя"
            else:
                status = "success"
                final_candidate = candidate
                final_stage = "OpenAI"
            stage_history.append(
                StageStatus(
                    name="OpenAI",
                    status=status,
                    confidence=candidate.confidence if candidate else None,
                    provider=", ".join(evaluation.provider_names) or None,
                    urls_considered=evaluation.urls_considered,
                    message=message,
                )
            )

        if not final_candidate and fallback_candidate and fallback_stage:
            final_candidate = fallback_candidate
            final_stage = fallback_stage
            for idx, stage in enumerate(stage_history):
                if stage.name == fallback_stage and stage.status == "low-confidence":
                    extra_msg = "Использован результат с низкой достоверностью из-за отсутствия альтернатив"
                    stage_history[idx] = stage.model_copy(
                        update={
                            "message": f"{stage.message + ' · ' if stage.message else ''}{extra_msg}",
                        }
                    )
                    break

        if not final_candidate:
            return SearchResult(
                part_number=part.part_number,
                manufacturer_name=None,
                alias_used=part.manufacturer_hint,
                confidence=None,
                source_url=None,
                debug_log="No sources found",
                search_stage=None,
                stage_history=stage_history,
            )

        manufacturer = await self.resolver.resolve(final_candidate.manufacturer)
        if final_candidate.alias_used:
            await self.resolver.sync_aliases(manufacturer, [final_candidate.alias_used])
        manufacturer_name = manufacturer.name
        new_part = Part(
            part_number=part.part_number,
            manufacturer=manufacturer,
            manufacturer_name=manufacturer_name,
            alias_used=final_candidate.alias_used,
            confidence=final_candidate.confidence,
            source_url=final_candidate.source_url,
            debug_log=final_candidate.debug_log if debug else None,
        )
        self.session.add(new_part)
        await self.session.flush()
        return SearchResult(
            part_number=part.part_number,
            manufacturer_name=manufacturer_name,
            alias_used=final_candidate.alias_used,
            confidence=final_candidate.confidence,
            source_url=final_candidate.source_url,
            debug_log=final_candidate.debug_log if debug else None,
            search_stage=final_stage,
            stage_history=stage_history,
        )

    async def search_many(self, items: list[PartBase], *, debug: bool = False) -> list[SearchResult]:
        results: list[SearchResult] = []
        for item in items:
            results.append(await self.search_part(item, debug=debug))
        return results
