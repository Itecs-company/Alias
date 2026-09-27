"""
Поисковый движок AliasFinder: определение производителя по артикулу.

Этапы (названия совпадают с интерфейсом и параметром ``stages`` API):

1. ``Internet`` — веб-поиск (SerpAPI при наличии ключа, затем бесплатные
   Yahoo → Bing → DuckDuckGo → Google; «мусорная» выдача без артикула
   распознаётся и провайдер переключается). Сначала анализируются только метаданные выдачи
   (домен, заголовок, сниппет, URL карточки дистрибьютора), и лишь при
   недостаточной уверенности параллельно скачиваются 3–4 самых информативных
   документа (даташиты, страницы производителя).
2. ``googlesearch`` — Google Custom Search API (если настроен), только если
   после первого этапа уверенность ниже порога.
3. ``OpenAI`` — одна компактная JSON-подсказка по уже собранному контексту
   (сниппеты + выдержки из документов, ~1000 токенов) для спорных случаев.

Все признаки из разных источников агрегируются (см. :mod:`app.services.evidence`),
поэтому итоговая уверенность отражает количество независимых подтверждений,
а подсказка оператора используется как решающий голос для деталей, которые
выпускают несколько производителей.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import ci_equals
from app.models.part import Part
from app.schemas.part import PartBase, SearchResult, StageStatus
from app.services.ai import ai_available, chat_json
from app.services.document_parser import document_to_text, fetch_document
from app.services.evidence import (
    CandidateScore,
    Evidence,
    SearchHit,
    evidence_from_document,
    evidence_from_hit,
    rank_candidates,
)
from app.services.log_recorder import SearchLogRecorder
from app.services.manufacturer_service import ManufacturerInfo, ManufacturerInfoExtractor, ManufacturerResolver
from app.services.manufacturers import (
    evaluate_match,
    hostname,
    is_distributor,
    manufacturer_from_url,
    manufacturer_similarity,
    normalize_manufacturer_name,
    part_number_key,
    part_number_strength,
    query_part_number,
)
from app.services.search_providers import (
    SearchProvider,
    get_google_provider,
    get_serpapi_provider,
    get_web_providers,
)

settings = get_settings()

STAGE_INTERNET = "Internet"
STAGE_GOOGLE = "googlesearch"
STAGE_OPENAI = "OpenAI"
ALL_STAGES: tuple[str, ...] = (STAGE_INTERNET, STAGE_GOOGLE, STAGE_OPENAI)

_STAGE_ALIASES = {
    "internet": STAGE_INTERNET,
    "web": STAGE_INTERNET,
    "document search": STAGE_INTERNET,
    "googlesearch": STAGE_GOOGLE,
    "google": STAGE_GOOGLE,
    "google-custom-search": STAGE_GOOGLE,
    "openai": STAGE_OPENAI,
    "ai": STAGE_OPENAI,
    "ai analysis": STAGE_OPENAI,
    "chatgpt": STAGE_OPENAI,
}

# Пороги уверенности
INTERNET_THRESHOLD = 0.75     # этап Internet считается успешным
METADATA_THRESHOLD = 0.8      # достаточно метаданных выдачи, документы не скачиваем
GOOGLE_THRESHOLD = 0.67       # этап googlesearch считается успешным
OPENAI_TRIGGER = 0.8          # ниже этой уверенности результат проверяется через OpenAI
OPENAI_THRESHOLD = 0.6        # этап OpenAI считается успешным
MIN_ACCEPT = 0.45             # ниже — производитель не считается найденным

MAX_DOCUMENTS = 4
DOCUMENT_TIMEOUT = 8.0         # общий бюджет на одну пачку документов, с
FOLLOWUP_DOCUMENT_TIMEOUT = 6.0
MAX_HITS_PER_QUERY = 10

_MARKETPLACES = ("amazon.", "ebay.", "aliexpress.", "ozon.", "wildberries.", "avito.", "market.yandex.", "alibaba.")
# Сайты, которые отдают ботам 403/JS-заглушку: их улики уже извлечены из URL/заголовка
_NO_FETCH_HOSTS = ("digikey.", "mouser.", "arrow.com", "octopart.", "findchips.", "lcsc.com", "avnet.", "farnell.",
                   "newark.", "rs-online.", "reddit.", "youtube.", "facebook.", "linkedin.")


def normalize_stages(stages: Sequence[str] | None) -> list[str] | None:
    """Приводит список этапов из запроса к каноническим именам (None — все этапы)."""
    if not stages:
        return None
    resolved: list[str] = []
    for stage in stages:
        name = _STAGE_ALIASES.get(str(stage).strip().lower())
        if name and name not in resolved:
            resolved.append(name)
    return resolved or None


@dataclass
class PartContext:
    """Рабочее состояние поиска одного артикула."""

    part_number: str
    hint: str | None
    hits: list[SearchHit] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    documents: dict[str, str] = field(default_factory=dict)
    attempted_documents: set[str] = field(default_factory=set)
    executed_queries: set[tuple[str, str]] = field(default_factory=set)
    providers_used: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def query_part(self) -> str:
        return query_part_number(self.part_number)

    def add_hits(self, provider: str, query: str, results: list[dict[str, Any]]) -> int:
        known = {hit.url for hit in self.hits}
        added = 0
        for rank, item in enumerate(results):
            url = item.get("link")
            if not url or url in known:
                continue
            known.add(url)
            hit = SearchHit(
                url=url,
                title=item.get("title") or "",
                snippet=item.get("snippet") or "",
                provider=provider,
                query=query,
                rank=rank,
            )
            self.hits.append(hit)
            self.evidence.extend(evidence_from_hit(hit, self.part_number, self.hint))
            added += 1
        if provider not in self.providers_used:
            self.providers_used.append(provider)
        return added

    def ranked(self) -> list[CandidateScore]:
        return rank_candidates(self.evidence, self.hint)

    def best(self) -> CandidateScore | None:
        ranked = self.ranked()
        return ranked[0] if ranked else None

    def best_confidence(self) -> float:
        best = self.best()
        return best.confidence if best else 0.0


class OptimizedPartSearchEngine:
    """Поиск производителя с минимальным трафиком и расходом токенов."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        web_providers: list[SearchProvider] | None = None,
        serpapi_provider: SearchProvider | None | bool = True,
        google_provider: SearchProvider | None = None,
        use_ai: bool | None = None,
        concurrency: int | None = None,
    ):
        self.session = session
        self.log_recorder = SearchLogRecorder(session)
        self.web_providers = web_providers if web_providers is not None else get_web_providers()
        if serpapi_provider is True:
            serpapi_provider = get_serpapi_provider()
        self.serpapi_provider: SearchProvider | None = serpapi_provider or None
        self.google_provider = google_provider or get_google_provider()
        self.use_ai = ai_available() if use_ai is None else use_ai
        self.concurrency = concurrency or settings.search_concurrency

        # AsyncSession не допускает конкурентных операций — все обращения к БД
        # выполняются под этой блокировкой, сетевые запросы идут параллельно.
        self._db_lock = asyncio.Lock()
        self.resolver = ManufacturerResolver(session)
        self.info_extractor = ManufacturerInfoExtractor(
            session, db_lock=self._db_lock, recorder=self.log_recorder, use_ai=self.use_ai
        )
        for provider in self._all_providers():
            provider.set_recorder(self.log_recorder)

    # --- провайдеры ----------------------------------------------------------------------
    def _all_providers(self) -> list[SearchProvider]:
        providers = list(self.web_providers)
        if self.serpapi_provider:
            providers.insert(0, self.serpapi_provider)
        if self.google_provider:
            providers.append(self.google_provider)
        return providers

    def _internet_providers(self) -> list[SearchProvider]:
        providers = [provider for provider in self.web_providers]
        if self.serpapi_provider:
            providers.insert(0, self.serpapi_provider)
        return providers

    @staticmethod
    def _is_relevant(ctx: PartContext, results: list[dict[str, Any]]) -> bool:
        """Есть ли в выдаче хоть одно упоминание артикула (защита от «мусорной» выдачи)."""
        return any(
            part_number_strength(
                ctx.part_number, f"{item.get('title') or ''} {item.get('snippet') or ''} {item.get('link') or ''}"
            )
            > 0
            for item in results
        )

    async def _search_queries(
        self, ctx: PartContext, providers: list[SearchProvider], queries: list[str], *, fallback: bool = True
    ) -> tuple[int, str | None]:
        """Выполняет запросы параллельно у первого доступного провайдера.

        Если провайдер ничего не вернул или вернул выдачу без единого упоминания
        артикула (капча, анти-бот «мусор»), пробуется следующий. Провайдер, чья
        выдача оказалась мусором там, где другой нашёл артикул, помечается и
        после нескольких повторов временно отключается.
        Возвращает (кол-во новых результатов, имя провайдера).
        """
        irrelevant: list[SearchProvider] = []
        for provider in providers:
            if not provider.available:
                continue
            pending = [query for query in dict.fromkeys(queries) if (provider.name, query.lower()) not in ctx.executed_queries]
            if not pending:
                return 0, provider.name
            for query in pending:
                ctx.executed_queries.add((provider.name, query.lower()))
            responses = await asyncio.gather(
                *(provider.search(query, max_results=MAX_HITS_PER_QUERY) for query in pending),
                return_exceptions=True,
            )
            added = 0
            relevant = False
            junk = False
            for query, response in zip(pending, responses):
                if isinstance(response, BaseException):
                    logger.warning("Provider {name} failed: {exc!r}", name=provider.name, exc=response)
                    continue
                if not response:
                    continue
                if self._is_relevant(ctx, response):
                    relevant = True
                    added += ctx.add_hits(provider.name, query, response)
                else:
                    junk = True
                    provider.forget(query, MAX_HITS_PER_QUERY)
            if relevant:
                provider.mark_relevant()
                for failed in irrelevant:
                    failed.mark_irrelevant()
                return added, provider.name
            if junk:
                irrelevant.append(provider)
            if not fallback:
                return 0, provider.name
        return 0, None

    # --- запросы ---------------------------------------------------------------------------
    @staticmethod
    def _primary_queries(ctx: PartContext) -> list[str]:
        queries = []
        if ctx.hint:
            queries.append(f"{ctx.query_part} {ctx.hint}")
        queries.append(ctx.query_part)
        return queries

    @staticmethod
    def _secondary_queries(ctx: PartContext) -> list[str]:
        queries = [f"{ctx.query_part} datasheet"]
        if ctx.hint:
            canonical = normalize_manufacturer_name(ctx.hint)
            if canonical and canonical.lower() != ctx.hint.lower():
                queries.insert(0, f"{ctx.query_part} {canonical}")
        else:
            queries.append(f"{ctx.query_part} manufacturer")
        return queries

    # --- документы ----------------------------------------------------------------------------
    def _document_candidates(self, ctx: PartContext, limit: int) -> list[SearchHit]:
        scored: list[tuple[float, SearchHit]] = []
        for hit in ctx.hits:
            if hit.url in ctx.attempted_documents:
                continue
            host = hit.host
            if any(marker in host for marker in _MARKETPLACES + _NO_FETCH_HOSTS):
                continue
            url_lower = hit.url.lower()
            strength = part_number_strength(ctx.part_number, f"{hit.title} {hit.snippet} {hit.url}")
            if strength <= 0:
                continue
            score = 2.0 * strength
            if url_lower.split("?")[0].endswith(".pdf") or "datasheet" in url_lower or "datasheet" in hit.title.lower():
                score += 2.0
            if manufacturer_from_url(hit.url):
                score += 2.5
            elif is_distributor(hit.url):
                score -= 0.5  # тяжёлые JS-страницы, часто блокируют ботов
            score -= 0.1 * hit.rank
            scored.append((score, hit))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [hit for score, hit in scored[:limit] if score > 1.0]

    async def _analyze_documents(
        self, ctx: PartContext, limit: int = MAX_DOCUMENTS, timeout: float = DOCUMENT_TIMEOUT
    ) -> int:
        candidates = self._document_candidates(ctx, limit)
        if not candidates:
            return 0
        for hit in candidates:
            ctx.attempted_documents.add(hit.url)

        async def load(hit: SearchHit) -> tuple[SearchHit, str]:
            document = await fetch_document(hit.url, timeout=timeout - 1.0)
            if document is None:
                return hit, ""
            text = await asyncio.to_thread(document_to_text, document)
            return hit, text

        tasks = [asyncio.ensure_future(load(hit)) for hit in candidates]
        done, pending = await asyncio.wait(tasks, timeout=timeout)
        for task in pending:
            task.cancel()
        analyzed = 0
        for task in done:
            if task.cancelled() or task.exception() is not None:
                continue
            hit, text = task.result()
            if not text:
                continue
            analyzed += 1
            ctx.documents[hit.url] = text[:300_000]
            ctx.evidence.extend(evidence_from_document(hit.url, text, ctx.part_number, ctx.hint))
        return analyzed

    # --- этапы ----------------------------------------------------------------------------------
    @staticmethod
    def _stage_status(
        name: str,
        ctx: PartContext,
        threshold: float,
        *,
        providers: list[str],
        urls: int,
        message: str,
    ) -> StageStatus:
        best = ctx.best()
        if best is None or best.confidence < MIN_ACCEPT * 0.5:
            status = "no-results"
            confidence = best.confidence if best else None
        elif best.confidence >= threshold:
            status = "success"
            confidence = best.confidence
        else:
            status = "low-confidence"
            confidence = best.confidence
        if best is not None:
            message = f"{message}. Лидер: {best.manufacturer} ({best.confidence:.2f})"
        return StageStatus(
            name=name,
            status=status,
            provider=", ".join(providers) or None,
            confidence=confidence,
            urls_considered=urls,
            message=message,
        )

    async def _stage_internet(self, ctx: PartContext) -> StageStatus:
        providers = self._internet_providers()
        if not any(provider.available for provider in providers):
            return StageStatus(
                name=STAGE_INTERNET,
                status="skipped",
                message="Нет доступных поисковых провайдеров (заблокированы или отключены)",
            )
        before = len(ctx.hits)
        used: list[str] = []
        _, provider_name = await self._search_queries(ctx, providers, self._primary_queries(ctx))
        if provider_name:
            used.append(provider_name)
        documents = 0
        if ctx.best_confidence() < METADATA_THRESHOLD:
            # Второй заход: даташит/каноническое имя + скачивание документов параллельно
            secondary = asyncio.ensure_future(self._search_queries(ctx, providers, self._secondary_queries(ctx)))
            documents = await self._analyze_documents(ctx)
            _, provider_name = await secondary
            if provider_name and provider_name not in used:
                used.append(provider_name)
            if ctx.best_confidence() < INTERNET_THRESHOLD:
                documents += await self._analyze_documents(ctx, limit=2, timeout=FOLLOWUP_DOCUMENT_TIMEOUT)
        found = len(ctx.hits) - before
        message = f"Результатов поиска: {found}"
        if documents:
            message += f", проанализировано документов: {documents}"
        if not found:
            message = "Поиск не вернул релевантных результатов"
        return self._stage_status(STAGE_INTERNET, ctx, INTERNET_THRESHOLD, providers=used, urls=found, message=message)

    async def _stage_google(self, ctx: PartContext) -> StageStatus:
        provider = self.google_provider
        if provider is None or not provider.configured:
            return StageStatus(name=STAGE_GOOGLE, status="skipped", message="Google Custom Search не настроен")
        if not provider.available:
            return StageStatus(name=STAGE_GOOGLE, status="skipped", message="Google Custom Search временно недоступен (лимит/ошибка)")
        before = len(ctx.hits)
        queries = self._primary_queries(ctx)
        await self._search_queries(ctx, [provider], queries, fallback=False)
        documents = 0
        if ctx.best_confidence() < GOOGLE_THRESHOLD:
            documents = await self._analyze_documents(ctx, limit=2, timeout=FOLLOWUP_DOCUMENT_TIMEOUT)
        found = len(ctx.hits) - before
        message = f"Новых результатов: {found}" if found else "Google не вернул новых результатов"
        if documents:
            message += f", проанализировано документов: {documents}"
        return self._stage_status(STAGE_GOOGLE, ctx, GOOGLE_THRESHOLD, providers=[provider.name], urls=found, message=message)

    def _ai_prompt(self, ctx: PartContext) -> list[dict[str, str]]:
        lines = [f"Part number: {ctx.part_number}"]
        if ctx.hint:
            lines.append(f"Operator's manufacturer hint: {ctx.hint}")
        relevant = sorted(
            ctx.hits,
            key=lambda hit: (-part_number_strength(ctx.part_number, f"{hit.title} {hit.snippet} {hit.url}"), hit.rank),
        )[:8]
        if relevant:
            lines.append("Search results:")
            for index, hit in enumerate(relevant, 1):
                snippet = " ".join(hit.snippet.split())[:170]
                lines.append(f"{index}. {hit.title[:100]} | {hit.url[:110]} | {snippet}")
        excerpts: list[str] = []
        budget = 1600
        for url, text in ctx.documents.items():
            if budget <= 0:
                break
            excerpt = _document_excerpt(text, ctx.part_number, min(600, budget))
            if excerpt:
                excerpts.append(f"[{hostname(url)}] {excerpt}")
                budget -= len(excerpt)
        if excerpts:
            lines.append("Document excerpts:")
            lines.extend(excerpts)
        ranked = ctx.ranked()[:3]
        if ranked:
            lines.append("Heuristic candidates: " + ", ".join(f"{c.manufacturer} ({c.confidence:.2f})" for c in ranked))
        system = (
            "You identify the original manufacturer (brand owner) of a product by its part number. "
            "Use the provided search results and excerpts as evidence; distributors, marketplaces and datasheet "
            "archives are not manufacturers. If several manufacturers produce this part and the operator's hint "
            "is one of them, choose the hint. If the evidence is insufficient, use your own knowledge but lower "
            "the confidence. Reply with JSON only: {\"manufacturer\": string or null, \"confidence\": number 0..1, "
            "\"source_url\": string or null, \"reason\": \"short\"}."
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(lines)}]

    async def _stage_openai(self, ctx: PartContext) -> StageStatus:
        if not self.use_ai:
            return StageStatus(name=STAGE_OPENAI, status="skipped", message="OpenAI не настроен (нет OPENAI_API_KEY)")
        context_note = ""
        if not ctx.hits:
            # Этап запущен отдельно: соберём минимальный контекст одним заходом веб-поиска
            await self._search_queries(ctx, self._internet_providers(), self._primary_queries(ctx))
            if ctx.hits:
                context_note = f"; контекст: {len(ctx.hits)} результатов веб-поиска"
        messages = self._ai_prompt(ctx)
        data = await chat_json(
            messages, max_tokens=160, recorder=self.log_recorder, provider="openai", query=ctx.part_number
        )
        if data is None:
            return StageStatus(name=STAGE_OPENAI, status="no-results", provider="openai", message="OpenAI не вернул ответ (см. логи)")
        raw_name = data.get("manufacturer")
        name = normalize_manufacturer_name(str(raw_name)) if raw_name else ""
        if not name or name.lower() in {"null", "none", "unknown", "n/a"}:
            return self._stage_status(
                STAGE_OPENAI, ctx, OPENAI_THRESHOLD, providers=["openai"], urls=len(ctx.hits),
                message="OpenAI не смог определить производителя" + context_note,
            )
        try:
            ai_confidence = min(1.0, max(0.0, float(data.get("confidence", 0.6))))
        except (TypeError, ValueError):
            ai_confidence = 0.6
        supported = any(
            candidate.support >= 0.3 and manufacturer_similarity(name, candidate.manufacturer) >= 0.9
            for candidate in ctx.ranked()
        )
        if supported:
            weight = ai_confidence * 0.85
        elif ctx.hits:
            weight = ai_confidence * 0.6
        else:
            weight = min(ai_confidence, 0.75) * 0.8
        source_url = data.get("source_url")
        known_urls = {hit.url for hit in ctx.hits}
        if not isinstance(source_url, str) or source_url not in known_urls:
            source_url = None
        reason = str(data.get("reason") or "")[:200]
        ctx.evidence.append(Evidence(name, weight, source_url or "openai://analysis", "ai", reason or "ответ OpenAI"))
        ctx.notes.append(f"OpenAI: {name} ({ai_confidence:.2f}) — {reason}")
        message = f"OpenAI: {name} (уверенность модели {ai_confidence:.2f}"
        message += ", подтверждено выдачей)" if supported else ")"
        return self._stage_status(
            STAGE_OPENAI, ctx, OPENAI_THRESHOLD, providers=["openai"], urls=len(ctx.hits), message=message + context_note
        )

    # --- БД ---------------------------------------------------------------------------------------
    async def _find_existing(self, part_number: str) -> Part | None:
        stmt = (
            select(Part)
            .where(ci_equals(Part.part_number, part_number))
            .order_by(Part.manufacturer_name.is_(None), Part.id.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def _commit(self) -> None:
        self.log_recorder.flush()
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    # --- основной сценарий -----------------------------------------------------------------------------
    async def search_part(
        self,
        part: PartBase,
        *,
        debug: bool = False,
        stages: Sequence[str] | None = None,
    ) -> SearchResult:
        started = time.monotonic()
        part_number = " ".join(part.part_number.split())
        hint = " ".join((part.manufacturer_hint or "").split()) or None
        selected = normalize_stages(stages)
        forced = selected is not None

        async with self._db_lock:
            existing = await self._find_existing(part_number)

        if not forced and existing is not None and existing.manufacturer_name:
            match_status, match_confidence = evaluate_match(hint, existing.manufacturer_name)
            if not hint or match_status == "matched":
                return await self._cached_result(existing, part_number, hint, match_status, match_confidence, debug)

        ctx = PartContext(part_number=part_number, hint=hint)
        stage_history: list[StageStatus] = []
        success_stage: str | None = None
        for stage in ALL_STAGES:
            if forced and stage not in selected:
                stage_history.append(StageStatus(name=stage, status="skipped", message="Этап не выбран"))
                continue
            if success_stage and not forced:
                if stage == STAGE_OPENAI and ctx.best_confidence() < OPENAI_TRIGGER:
                    pass  # перепроверяем сомнительный результат через OpenAI
                else:
                    stage_history.append(
                        StageStatus(name=stage, status="skipped", message=f"Не требуется: результат найден на этапе {success_stage}")
                    )
                    continue
            try:
                if stage == STAGE_INTERNET:
                    status = await self._stage_internet(ctx)
                elif stage == STAGE_GOOGLE:
                    status = await self._stage_google(ctx)
                else:
                    status = await self._stage_openai(ctx)
            except Exception as exc:  # noqa: BLE001 - ошибка этапа не должна прерывать поиск
                logger.exception("Stage {stage} failed for {part}", stage=stage, part=part_number)
                status = StageStatus(name=stage, status="no-results", message=f"Ошибка этапа: {exc}")
            stage_history.append(status)
            if status.status == "success" and success_stage is None:
                success_stage = stage

        best = ctx.best()
        if best is not None and best.confidence < MIN_ACCEPT:
            best = None
        final_stage = success_stage
        if best is not None and final_stage is None:
            final_stage = next(
                (s.name for s in reversed(stage_history) if s.status in {"success", "low-confidence"}), None
            )
        elapsed = time.monotonic() - started
        logger.info(
            "Search {part}: {result} in {elapsed:.1f}s (hits={hits}, docs={docs})",
            part=part_number,
            result=f"{best.manufacturer} ({best.confidence:.2f})" if best else "not found",
            elapsed=elapsed,
            hits=len(ctx.hits),
            docs=len(ctx.documents),
        )
        debug_text = self._debug_text(ctx, best, elapsed) if debug else None

        if best is None:
            return await self._persist_not_found(existing, part_number, hint, stage_history, debug_text)

        info = await self.info_extractor.extract_info(best.manufacturer)
        return await self._persist_found(existing, part_number, hint, best, final_stage, stage_history, info, debug_text)

    async def _cached_result(
        self,
        existing: Part,
        part_number: str,
        hint: str | None,
        match_status: str | None,
        match_confidence: float | None,
        debug: bool,
    ) -> SearchResult:
        message = "Использован ранее найденный результат из БД"
        stage_history = [StageStatus(name=stage, status="skipped", message=message) for stage in ALL_STAGES]
        async with self._db_lock:
            try:
                row = await self._find_existing(part_number)
                if row is None:  # строку удалили параллельно
                    row = Part(part_number=part_number)
                    self.session.add(row)
                if hint:
                    row.submitted_manufacturer = hint
                    row.match_status = match_status
                    row.match_confidence = match_confidence
                    await self._commit()
                snapshot = _snapshot(row)
                debug_log = row.debug_log if debug else None
            except Exception:
                await self.session.rollback()
                raise
        return SearchResult(
            **snapshot,
            debug_log=debug_log,
            stage_history=stage_history,
        ).model_copy(update={"search_stage": "cache"})

    async def _persist_not_found(
        self,
        existing: Part | None,
        part_number: str,
        hint: str | None,
        stage_history: list[StageStatus],
        debug_text: str | None,
    ) -> SearchResult:
        async with self._db_lock:
            try:
                target = await self._find_existing(part_number)
                if target is None:
                    target = Part(part_number=part_number)
                    self.session.add(target)
                if hint:
                    target.submitted_manufacturer = hint
                previous = target.manufacturer_name
                match_status, match_confidence = evaluate_match(target.submitted_manufacturer, previous)
                target.match_status = match_status
                target.match_confidence = match_confidence
                target.stage_history = [stage.model_dump() for stage in stage_history]
                if previous is None:
                    target.search_stage = None
                    target.debug_log = debug_text
                await self._commit()
                snapshot = _snapshot(target)
            except Exception:
                await self.session.rollback()
                raise

        note = "Производитель не найден"
        if snapshot["manufacturer_name"]:
            note += "; сохранён ранее найденный результат"
        return SearchResult(
            part_number=snapshot["part_number"],
            manufacturer_name=snapshot["manufacturer_name"],
            alias_used=snapshot["alias_used"],
            submitted_manufacturer=snapshot["submitted_manufacturer"],
            match_status=snapshot["match_status"],
            match_confidence=snapshot["match_confidence"],
            confidence=snapshot["confidence"],
            source_url=snapshot["source_url"],
            debug_log=f"{note}\n{debug_text}" if debug_text else None,
            search_stage=snapshot["search_stage"],
            stage_history=stage_history,
            what_produces=snapshot["what_produces"],
            website=snapshot["website"],
            manufacturer_aliases=snapshot["manufacturer_aliases"],
            country=snapshot["country"],
        )

    async def _persist_found(
        self,
        existing: Part | None,
        part_number: str,
        hint: str | None,
        best: CandidateScore,
        final_stage: str | None,
        stage_history: list[StageStatus],
        info: ManufacturerInfo,
        debug_text: str | None,
    ) -> SearchResult:
        match_status, match_confidence = evaluate_match(hint, best.manufacturer)
        alias_used = hint if hint and match_status == "matched" else None
        evidence = best.best_evidence
        source_url = evidence.source_url if evidence and evidence.source_url.startswith("http") else None
        if source_url is None:
            source_url = next((item.source_url for item in best.evidence if item.source_url.startswith("http")), None)
        summary = f"{best.manufacturer}: {best.describe()}"

        async with self._db_lock:
            try:
                manufacturer_name = await self._write_found_row(
                    part_number, hint, best, alias_used, source_url, final_stage, stage_history, info,
                    debug_text or summary,
                )
            except Exception:
                await self.session.rollback()
                raise

        return SearchResult(
            part_number=part_number,
            manufacturer_name=manufacturer_name,
            alias_used=alias_used,
            submitted_manufacturer=hint,
            match_status=match_status,
            match_confidence=match_confidence,
            confidence=best.confidence,
            source_url=source_url,
            debug_log=debug_text,
            search_stage=final_stage,
            stage_history=stage_history,
            what_produces=info.what_produces,
            website=info.website,
            manufacturer_aliases=info.manufacturer_aliases,
            country=info.country,
        )

    async def _write_found_row(
        self,
        part_number: str,
        hint: str | None,
        best: CandidateScore,
        alias_used: str | None,
        source_url: str | None,
        final_stage: str | None,
        stage_history: list[StageStatus],
        info: ManufacturerInfo,
        debug_log: str,
    ) -> str:
        """Сохраняет найденного производителя (вызывать под ``_db_lock``)."""
        manufacturer = await self.resolver.resolve(best.manufacturer)
        if alias_used and alias_used.lower() != manufacturer.name.lower():
            await self.resolver.sync_aliases(manufacturer, [alias_used])
        target = await self._find_existing(part_number)
        if target is None:
            target = Part(part_number=part_number)
            self.session.add(target)
        target.manufacturer_id = manufacturer.id
        target.manufacturer_name = manufacturer.name
        target.alias_used = alias_used
        if hint:
            target.submitted_manufacturer = hint
        status_for_row, confidence_for_row = evaluate_match(target.submitted_manufacturer, manufacturer.name)
        target.match_status = status_for_row
        target.match_confidence = confidence_for_row
        target.confidence = best.confidence
        target.source_url = source_url
        target.debug_log = debug_log
        target.search_stage = final_stage
        target.stage_history = [stage.model_dump() for stage in stage_history]
        target.what_produces = info.what_produces
        target.website = info.website
        target.manufacturer_aliases = info.manufacturer_aliases
        target.country = info.country
        await self._commit()
        return manufacturer.name

    @staticmethod
    def _debug_text(ctx: PartContext, best: CandidateScore | None, elapsed: float) -> str:
        lines = [
            f"Артикул: {ctx.part_number}" + (f", подсказка: {ctx.hint}" if ctx.hint else ""),
            f"Время: {elapsed:.1f} с; провайдеры: {', '.join(ctx.providers_used) or '—'}",
            f"Запросы: {'; '.join(sorted({query for _, query in ctx.executed_queries})) or '—'}",
            f"Результатов: {len(ctx.hits)}, документов: {len(ctx.documents)}",
        ]
        ranked = ctx.ranked()[:5]
        if ranked:
            lines.append("Кандидаты:")
            for candidate in ranked:
                lines.append(
                    f"  • {candidate.manufacturer}: уверенность {candidate.confidence:.2f}, "
                    f"поддержка {candidate.support:.2f} — {candidate.describe(3)}"
                )
        if best is None:
            lines.append("Итог: производитель не найден")
        lines.extend(ctx.notes)
        return "\n".join(lines)

    async def search_many(
        self,
        items: Sequence[PartBase],
        *,
        debug: bool = False,
        stages: Sequence[str] | None = None,
    ) -> list[SearchResult]:
        """Поиск нескольких артикулов параллельно; одинаковые позиции ищутся один раз."""
        selected = normalize_stages(stages)
        keys: list[tuple[str, str]] = []
        unique: dict[tuple[str, str], PartBase] = {}
        for item in items:
            key = (part_number_key(item.part_number) or item.part_number.strip().lower(),
                   normalize_manufacturer_name(item.manufacturer_hint).lower())
            keys.append(key)
            unique.setdefault(key, item)

        semaphore = asyncio.Semaphore(self.concurrency)

        async def run(item: PartBase) -> SearchResult:
            async with semaphore:
                try:
                    return await self.search_part(item, debug=debug, stages=selected)
                except Exception as exc:  # noqa: BLE001 - одна позиция не должна валить весь пакет
                    logger.exception("Search failed for {part}", part=item.part_number)
                    return _error_result(item, exc)

        results = await asyncio.gather(*(run(item) for item in unique.values()))
        by_key = dict(zip(unique.keys(), results))
        output: list[SearchResult] = []
        for item, key in zip(items, keys):
            result = by_key[key]
            if result.part_number != item.part_number:
                result = result.model_copy(update={"part_number": item.part_number})
            output.append(result)
        return output


def _document_excerpt(text: str, part_number: str, limit: int) -> str:
    """Короткий фрагмент документа вокруг первого упоминания артикула."""
    key = part_number_key(part_number)
    if not key:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if part_number_strength(part_number, line) > 0:
            window = " ".join(lines[max(0, index - 2): index + 4])
            return " ".join(window.split())[:limit]
    return " ".join(" ".join(lines[:6]).split())[:limit]


def _snapshot(part: Part) -> dict[str, Any]:
    return {
        "part_number": part.part_number,
        "manufacturer_name": part.manufacturer_name,
        "alias_used": part.alias_used,
        "submitted_manufacturer": part.submitted_manufacturer,
        "match_status": part.match_status,
        "match_confidence": part.match_confidence,
        "confidence": part.confidence,
        "source_url": part.source_url,
        "search_stage": part.search_stage,
        "what_produces": part.what_produces,
        "website": part.website,
        "manufacturer_aliases": part.manufacturer_aliases,
        "country": part.country,
    }


def _error_result(item: PartBase, exc: Exception) -> SearchResult:
    hint = (item.manufacturer_hint or "").strip() or None
    return SearchResult(
        part_number=item.part_number,
        manufacturer_name=None,
        alias_used=None,
        submitted_manufacturer=hint,
        match_status="pending" if hint else None,
        match_confidence=None,
        confidence=None,
        source_url=None,
        debug_log=None,
        search_stage=None,
        stage_history=[StageStatus(name=STAGE_INTERNET, status="no-results", message=f"Ошибка поиска: {exc}")],
    )


# Совместимость: старое имя класса
PartSearchEngine = OptimizedPartSearchEngine

__all__ = [
    "ALL_STAGES",
    "OptimizedPartSearchEngine",
    "PartContext",
    "PartSearchEngine",
    "STAGE_GOOGLE",
    "STAGE_INTERNET",
    "STAGE_OPENAI",
    "normalize_stages",
]
