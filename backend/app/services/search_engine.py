from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from typing import List
from urllib.parse import urlparse

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


DOMAIN_MANUFACTURER_HINTS: dict[str, str] = {
    "ti.com": "Texas Instruments",
    "texasinstruments.com": "Texas Instruments",
    "analog.com": "Analog Devices",
    "adi.com": "Analog Devices",
    "st.com": "STMicroelectronics",
    "microchip.com": "Microchip Technology",
    "onsemi.com": "onsemi",
    "nxp.com": "NXP Semiconductors",
    "infineon.com": "Infineon Technologies",
    "renesas.com": "Renesas Electronics",
    "vishay.com": "Vishay Intertechnology",
    "maximintegrated.com": "Maxim Integrated",
    "diodes.com": "Diodes Incorporated",
    "broadcom.com": "Broadcom",
    "fairchildsemi.com": "Fairchild Semiconductor",
    "rohm.com": "ROHM Semiconductor",
    "semiconductor.samsung.com": "Samsung Semiconductor",
    "semtech.com": "Semtech",
}

KNOWN_MANUFACTURERS: list[str] = [
    "Texas Instruments",
    "Analog Devices",
    "STMicroelectronics",
    "Microchip Technology",
    "NXP Semiconductors",
    "Infineon Technologies",
    "onsemi",
    "ON Semiconductor",
    "Renesas Electronics",
    "Vishay Intertechnology",
    "Maxim Integrated",
    "Diodes Incorporated",
    "Broadcom",
    "ROHM Semiconductor",
    "Semtech",
    "Samsung Semiconductor",
]

KEYWORD_HINTS = (
    "datasheet",
    "manufacturer",
    "semiconductor",
    "devices",
    "instruments",
    "technology",
    "microelectronics",
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
        queries = [
            f"{part.part_number} {part.manufacturer_hint} datasheet" if part.manufacturer_hint else None,
            f"{part.part_number} datasheet manufacturer",
            f"{part.part_number} pdf",
        ]
        urls: list[str] = []
        for provider in providers:
            for query in filter(None, queries):
                urls.extend(await self._search_with_provider(provider, query))
                if len(urls) >= 10:
                    break
            if len(urls) >= 10:
                break
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
            candidate = self._guess_manufacturer_from_text(text, part, url)
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

    def _guess_manufacturer_from_text(
        self, text: str, part: PartBase, url: str
    ) -> tuple[str, str | None, float, str] | None:
        domain_manufacturer = self._manufacturer_from_domain(url)
        if domain_manufacturer:
            alias = self._alias_if_similar(part, domain_manufacturer)
            host = urlparse(url).hostname or url
            return (
                domain_manufacturer,
                alias,
                0.96,
                f"Производитель определён по домену {host}",
            )

        known_manufacturer = self._manufacturer_from_known_text(text)
        if known_manufacturer:
            alias = self._alias_if_similar(part, known_manufacturer)
            return (
                known_manufacturer,
                alias,
                0.9,
                "В тексте даташита найдено упоминание производителя",
            )

        lines = text.splitlines()
        candidates = [line for line in lines if part.part_number.lower() in line.lower()]
        if not candidates and part.manufacturer_hint:
            candidates = [line for line in lines if part.manufacturer_hint.lower() in line.lower()]
        if not candidates:
            keyword_lines = [
                line
                for line in lines
                if any(keyword in line.lower() for keyword in KEYWORD_HINTS)
            ]
            if keyword_lines:
                candidates = keyword_lines[:20]
        if not candidates:
            candidates = lines[:20]

        manufacturer_names: list[str] = []
        for line in candidates:
            tokens = [
                token.strip(" ,.;:()[]")
                for token in line.split()
                if token.isalpha() and len(token) > 2
            ]
            if tokens:
                manufacturer_names.append(" ".join(tokens[:3]))
        if not manufacturer_names:
            return None

        best_known: tuple[str, float] | None = None
        for name in manufacturer_names:
            match = process.extractOne(name, KNOWN_MANUFACTURERS, scorer=fuzz.WRatio)
            if match:
                score = match[1]
                if not best_known or score > best_known[1]:
                    best_known = (match[0], score)
        if best_known and best_known[1] >= 82:
            manufacturer = best_known[0]
            alias = self._alias_if_similar(part, manufacturer)
            confidence = min(0.97, best_known[1] / 100)
            debug = f"Определено по базе производителей ({confidence:.2f})"
            return manufacturer, alias, confidence, debug

        if part.manufacturer_hint:
            match = process.extractOne(
                part.manufacturer_hint,
                manufacturer_names,
                scorer=fuzz.WRatio,
            )
            if match and match[1] >= 67:
                confidence = max(0.67, match[1] / 100)
                manufacturer = match[0]
                debug = f"Совпадение с подсказкой оператора ({confidence:.2f})"
                return manufacturer, part.manufacturer_hint, confidence, debug

        top = process.extractOne(part.part_number, manufacturer_names, scorer=fuzz.partial_ratio)
        if top:
            manufacturer = top[0]
            confidence = top[1] / 100
            alias = self._alias_if_similar(part, manufacturer)
            if part.manufacturer_hint:
                hint_score = fuzz.WRatio(part.manufacturer_hint, manufacturer) / 100
                confidence = max(confidence, min(0.95, hint_score))
                debug = (
                    f"Эвристика по контексту даташита ({confidence:.2f}), совпадение с подсказкой {hint_score:.2f}"
                )
            else:
                debug = f"Эвристика по контексту даташита ({confidence:.2f})"
            return manufacturer, alias, confidence, debug

        manufacturer = manufacturer_names[0]
        alias = self._alias_if_similar(part, manufacturer)
        return manufacturer, alias, 0.35, "Резервное определение производителя"

    def _manufacturer_from_domain(self, url: str) -> str | None:
        try:
            hostname = urlparse(url).hostname
        except ValueError:
            return None
        if not hostname:
            return None
        hostname = hostname.lower()
        for domain, manufacturer in DOMAIN_MANUFACTURER_HINTS.items():
            if hostname == domain or hostname.endswith(f".{domain}"):
                return manufacturer
        return None

    def _manufacturer_from_known_text(self, text: str) -> str | None:
        lowered = text.lower()
        matches = [name for name in KNOWN_MANUFACTURERS if name.lower() in lowered]
        if not matches:
            return None
        counts = Counter(matches)
        return counts.most_common(1)[0][0]

    def _alias_if_similar(self, part: PartBase, manufacturer: str) -> str | None:
        if not part.manufacturer_hint:
            return None
        score = fuzz.WRatio(part.manufacturer_hint, manufacturer)
        if score >= 60:
            return part.manufacturer_hint
        return None

    def _evaluate_match(
        self, submitted: str | None, resolved: str | None
    ) -> tuple[str | None, float | None]:
        if not submitted:
            return None, None
        if not resolved:
            return "pending", None
        score = fuzz.WRatio(submitted, resolved)
        status = "matched" if score >= 70 else "mismatch"
        return status, score / 100

    async def search_part(self, part: PartBase, *, debug: bool = False) -> SearchResult:
        stage_history: list[StageStatus] = []
        final_candidate: Candidate | None = None
        final_stage: str | None = None
        fallback_candidate: Candidate | None = None
        fallback_stage: str | None = None

        stmt = select(Part).where(Part.part_number == part.part_number).order_by(Part.id.desc())
        existing_part = (await self.session.execute(stmt)).scalars().first()

        if existing_part and existing_part.manufacturer_name:
            match_status, match_confidence = self._evaluate_match(
                part.manufacturer_hint, existing_part.manufacturer_name
            )
            if not part.manufacturer_hint or (match_status == "matched"):
                stage_history.append(
                    StageStatus(
                        name="Internet",
                        status="skipped",
                        message="Использован ранее найденный производитель",
                    )
                )
                stage_history.append(
                    StageStatus(
                        name="googlesearch",
                        status="skipped",
                        message="Использован ранее найденный производитель",
                    )
                )
                stage_history.append(
                    StageStatus(name="OpenAI", status="skipped", message="Результат уже в базе")
                )
                return SearchResult(
                    part_number=part.part_number,
                    manufacturer_name=existing_part.manufacturer_name,
                    alias_used=existing_part.alias_used,
                    confidence=existing_part.confidence,
                    source_url=existing_part.source_url,
                    debug_log=existing_part.debug_log if debug else None,
                    search_stage=None,
                    stage_history=stage_history,
                    submitted_manufacturer=part.manufacturer_hint,
                    match_status=match_status,
                    match_confidence=match_confidence,
                )

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
                    skip_remaining = True
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

        need_llm = final_candidate is None or (
            final_candidate.confidence is not None and final_candidate.confidence < 0.8
        )

        if need_llm:
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
                if (final_candidate is None) or (
                    final_candidate.confidence is None
                    or candidate.confidence > final_candidate.confidence
                ):
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
        elif final_candidate:
            stage_history.append(
                StageStatus(
                    name="OpenAI",
                    status="skipped",
                    message="OpenAI не потребовался",
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
            submitted = part.manufacturer_hint
            match_status: str | None = None
            match_confidence: float | None = None
            if submitted:
                target = existing_part or Part(part_number=part.part_number)
                if not existing_part:
                    self.session.add(target)
                target.submitted_manufacturer = submitted
                if target.manufacturer_name:
                    match_status, match_confidence = self._evaluate_match(
                        submitted, target.manufacturer_name
                    )
                else:
                    match_status, match_confidence = "pending", None
                target.match_status = match_status
                target.match_confidence = match_confidence
                target.debug_log = "No sources found"
                await self.session.flush()
            return SearchResult(
                part_number=part.part_number,
                manufacturer_name=None,
                alias_used=part.manufacturer_hint,
                confidence=None,
                source_url=None,
                debug_log="No sources found",
                search_stage=None,
                stage_history=stage_history,
                submitted_manufacturer=submitted,
                match_status=match_status,
                match_confidence=match_confidence,
            )

        manufacturer = await self.resolver.resolve(final_candidate.manufacturer)
        if final_candidate.alias_used:
            await self.resolver.sync_aliases(manufacturer, [final_candidate.alias_used])
        manufacturer_name = manufacturer.name

        if existing_part:
            target = existing_part
            target.manufacturer = manufacturer
        else:
            target = Part(part_number=part.part_number, manufacturer=manufacturer)
            self.session.add(target)

        match_status, match_confidence = self._evaluate_match(
            part.manufacturer_hint, manufacturer_name
        )

        target.manufacturer_name = manufacturer_name
        target.alias_used = final_candidate.alias_used
        target.submitted_manufacturer = part.manufacturer_hint
        target.match_status = match_status
        target.match_confidence = match_confidence
        target.confidence = final_candidate.confidence
        target.source_url = final_candidate.source_url
        target.debug_log = final_candidate.debug_log if debug else None
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
            submitted_manufacturer=part.manufacturer_hint,
            match_status=match_status,
            match_confidence=match_confidence,
        )

    async def search_many(self, items: list[PartBase], *, debug: bool = False) -> list[SearchResult]:
        semaphore = asyncio.Semaphore(4)

        async def run(item: PartBase) -> SearchResult:
            async with semaphore:
                return await self.search_part(item, debug=debug)

        return await asyncio.gather(*(run(item) for item in items))
