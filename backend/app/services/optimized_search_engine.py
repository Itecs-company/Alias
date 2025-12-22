"""
Оптимизированный поисковый движок с минимальным расходом токенов OpenAI.

Логика поиска:
1. Простой поиск в интернете (без OpenAI)
2. Если ничего не найдено → поиск документов/datasheets
3. Скачивание документа
4. Анализ документа через OpenAI (оптимизированный)
5. Извлечение данных (артикул + производитель)
6. Удаление документа после обработки
"""
from __future__ import annotations

import asyncio
import io
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from loguru import logger
from openai import AsyncOpenAI
from pypdf import PdfReader
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.http import httpx_client_kwargs
from app.models.part import Part
from app.schemas.part import PartBase, SearchResult, StageStatus
from app.services.document_parser import extract_text_from_html, extract_text_from_pdf, fetch_bytes
from app.services.log_recorder import SearchLogRecorder
from app.services.search_engine import (
    DOMAIN_MANUFACTURER_HINTS,
    KNOWN_MANUFACTURERS,
    ManufacturerInfoExtractor,
    ManufacturerResolver,
    normalize_manufacturer_name,
)
from app.services.search_providers import (
    SearchProvider,
    get_default_providers,
    get_fallback_provider,
    get_google_provider,
)

settings = get_settings()


@dataclass
class SearchCandidate:
    """Кандидат результата поиска"""
    manufacturer: str
    confidence: float
    source_url: str
    debug_info: str
    alias_used: str | None = None


@dataclass
class DocumentInfo:
    """Информация о скачанном документе"""
    url: str
    file_path: Path
    content_type: str | None
    size_bytes: int


class OptimizedPartSearchEngine:
    """
    Оптимизированный движок поиска с минимальным использованием токенов.

    Стратегия:
    1. Быстрый поиск по интернету через эвристики (без AI)
    2. Поиск документов, если первый этап не дал результатов
    3. Анализ документов через OpenAI с оптимизированными промптами
    """

    # Ключевые слова для поиска документов
    DATASHEET_KEYWORDS = ["datasheet", "pdf", "specification", "spec sheet"]

    # Максимальный размер текста для отправки в OpenAI (символы)
    MAX_TEXT_SIZE_FOR_AI = 3000

    # Максимальный размер документа для скачивания (10 MB)
    MAX_DOCUMENT_SIZE = 10 * 1024 * 1024

    def __init__(self, session: AsyncSession):
        self.session = session
        self.log_recorder = SearchLogRecorder(session)

        # Инициализируем все доступные провайдеры
        self.providers = get_default_providers()  # GoogleWebSearch + optional SerpAPI
        self.google_provider = get_google_provider()  # Google Custom Search
        self.fallback_provider = get_fallback_provider()  # OpenAI

        self.resolver = ManufacturerResolver(session)
        self.info_extractor = ManufacturerInfoExtractor()

        # Подключаем логирование к провайдерам
        self._attach_recorder()

        # Логируем доступные провайдеры
        all_providers = self._get_all_providers()
        logger.info(f"Initialized OptimizedPartSearchEngine with {len(all_providers)} providers:")
        for provider in all_providers:
            logger.info(f"  - {provider.name}")

        # OpenAI client для анализа документов
        self.openai_client: AsyncOpenAI | None = None
        if settings.openai_api_key:
            http_client = httpx.AsyncClient(**httpx_client_kwargs())
            self.openai_client = AsyncOpenAI(
                api_key=settings.openai_api_key,
                http_client=http_client
            )

        # Временная директория для документов
        self.temp_dir = Path(tempfile.gettempdir()) / "aliasfinder_docs"
        self.temp_dir.mkdir(exist_ok=True)

    def _attach_recorder(self) -> None:
        """Подключает логирование к всем провайдерам."""
        all_providers = [*self.providers, self.google_provider, self.fallback_provider]
        for provider in all_providers:
            if hasattr(provider, "set_recorder"):
                provider.set_recorder(self.log_recorder)

    def _get_all_providers(self) -> list[SearchProvider]:
        """Возвращает все доступные провайдеры для поиска."""
        return [*self.providers, self.google_provider, self.fallback_provider]

    async def _simple_web_search(
        self,
        part: PartBase,
        providers: list[SearchProvider]
    ) -> SearchCandidate | None:
        """
        Этап 1: Простой поиск в интернете без использования AI.
        Использует эвристики и базу данных производителей.
        """
        logger.info(f"Stage 1: Simple web search for {part.part_number}")

        if not providers:
            logger.warning("No search providers available")
            return None

        # Фильтруем провайдеров: НЕ используем OpenAI для веб-поиска
        # OpenAI используется только для анализа документов (Stage 3)
        web_providers = [p for p in providers if p.name != "openai"]

        if not web_providers:
            logger.warning("No web search providers available (OpenAI excluded)")
            return None

        logger.debug(f"Using {len(web_providers)} providers for web search (excluding OpenAI)")

        # Формируем простые запросы
        queries = []
        if part.manufacturer_hint:
            latin_hint = normalize_manufacturer_name(part.manufacturer_hint)
            queries.append(f"{part.part_number} {part.manufacturer_hint}")
            if latin_hint != part.manufacturer_hint:
                queries.append(f"{part.part_number} {latin_hint}")
        queries.append(part.part_number)

        logger.debug(f"Generated {len(queries)} search queries: {queries}")

        # Собираем результаты с метаданными (title, snippet)
        search_results = []
        for provider in web_providers:
            logger.debug(f"Using provider: {provider.name}")
            for query in queries:
                try:
                    logger.debug(f"Searching: {query}")
                    results = await provider.search(query, max_results=5)
                    logger.debug(f"Provider {provider.name} returned {len(results)} results")

                    # Логируем первый результат для отладки
                    if results:
                        first_result = results[0]
                        logger.debug(f"First result: title='{first_result.get('title', '')[:80]}', link='{first_result.get('link', '')}'")

                    search_results.extend(results)
                    if len(search_results) >= 10:
                        break
                except Exception as e:
                    logger.error(f"Provider {provider.name} failed: {e}", exc_info=True)
            if len(search_results) >= 10:
                break

        logger.info(f"Collected {len(search_results)} search results from {len(web_providers)} web providers")

        # ЭТАП 1: Анализ метаданных (title + snippet) БЕЗ скачивания страниц
        for result in search_results[:10]:
            url = result.get("link")
            if not url:
                continue

            title = result.get("title", "")
            snippet = result.get("snippet", "")
            metadata_text = f"{title} {snippet}".lower()

            # Проверяем домен
            manufacturer = self._get_manufacturer_from_domain(url)
            if manufacturer:
                logger.info(f"Found manufacturer from domain: {manufacturer}")
                return SearchCandidate(
                    manufacturer=manufacturer,
                    confidence=0.95,
                    source_url=url,
                    debug_info=f"Identified from domain: {urlparse(url).hostname}",
                    alias_used=part.manufacturer_hint if part.manufacturer_hint else None
                )

            # Анализируем метаданные (title + snippet)
            candidate = self._analyze_text_heuristically(metadata_text, part, url)
            if candidate and candidate.confidence >= 0.80:
                logger.info(f"Found manufacturer from metadata: {candidate.manufacturer}")
                candidate.debug_info = f"Found in search result title/snippet: {title[:100]}"
                return candidate

        # ЭТАП 2: Скачиваем контент только если метаданные не дали результата
        logger.debug("Metadata analysis failed, fetching page content...")
        for result in search_results[:5]:  # Ограничиваем до 5 URL
            url = result.get("link")
            if not url:
                continue

            try:
                async with httpx.AsyncClient(**httpx_client_kwargs()) as client:
                    response = await client.get(url, follow_redirects=True, timeout=10)
                    response.raise_for_status()

                    # Анализируем только начало контента (первые 3KB)
                    text_sample = response.text[:3000]
                    candidate = self._analyze_text_heuristically(text_sample, part, url)
                    if candidate and candidate.confidence >= 0.80:
                        logger.info(f"Found manufacturer from page content: {candidate.manufacturer}")
                        return candidate
            except Exception as e:
                logger.debug(f"Failed to fetch {url}: {e}")
                continue

        return None

    async def _search_for_documents(
        self,
        part: PartBase,
        providers: list[SearchProvider]
    ) -> list[str]:
        """
        Этап 2: Поиск документов/datasheets.
        Возвращает список URL документов для загрузки.
        """
        logger.info(f"Stage 2: Searching for documents for {part.part_number}")

        # Фильтруем провайдеров: НЕ используем OpenAI для поиска документов
        web_providers = [p for p in providers if p.name != "openai"]

        if not web_providers:
            logger.warning("No web providers for document search")
            return []

        # Формируем запросы специально для поиска документов
        queries = []
        base_query = part.part_number

        if part.manufacturer_hint:
            latin_hint = normalize_manufacturer_name(part.manufacturer_hint)
            for keyword in self.DATASHEET_KEYWORDS:
                queries.append(f"{base_query} {part.manufacturer_hint} {keyword}")
                if latin_hint != part.manufacturer_hint:
                    queries.append(f"{base_query} {latin_hint} {keyword}")
        else:
            for keyword in self.DATASHEET_KEYWORDS:
                queries.append(f"{base_query} {keyword}")

        logger.debug(f"Document search queries: {queries[:3]}...")  # Log first 3

        # Собираем URLs документов
        doc_urls = []
        for provider in web_providers:
            for query in queries:
                try:
                    results = await provider.search(query, max_results=3)
                    for result in results:
                        url = result.get("link")
                        if url and self._is_likely_document(url, result.get("title", "")):
                            doc_urls.append(url)
                    if len(doc_urls) >= 5:
                        break
                except Exception as e:
                    logger.debug(f"Provider {provider.name} failed during document search: {e}")
            if len(doc_urls) >= 5:
                break

        # Удаляем дубликаты
        unique_urls = list(dict.fromkeys(doc_urls))
        logger.info(f"Found {len(unique_urls)} potential document URLs")

        return unique_urls[:3]  # Ограничиваем до 3 документов для экономии

    async def _download_document(self, url: str) -> DocumentInfo | None:
        """
        Скачивает документ во временный файл.
        Возвращает информацию о документе или None при ошибке.
        """
        logger.info(f"Downloading document from {url}")

        try:
            # Используем существующую функцию fetch_bytes
            result = await fetch_bytes(url)
            if not result:
                return None

            data, content_type = result

            # Проверяем размер
            if len(data) > self.MAX_DOCUMENT_SIZE:
                logger.warning(f"Document too large: {len(data)} bytes")
                return None

            # Сохраняем во временный файл
            file_path = self.temp_dir / f"doc_{hash(url)}.tmp"
            file_path.write_bytes(data)

            return DocumentInfo(
                url=url,
                file_path=file_path,
                content_type=content_type,
                size_bytes=len(data)
            )
        except Exception as e:
            logger.error(f"Failed to download document from {url}: {e}")
            return None

    async def _analyze_document_with_ai(
        self,
        doc_info: DocumentInfo,
        part: PartBase
    ) -> SearchCandidate | None:
        """
        Этап 3: Анализ документа через OpenAI с оптимизацией токенов.

        Стратегия оптимизации:
        1. Извлекаем только важные части документа
        2. Используем краткий промпт
        3. Ограничиваем размер контекста
        4. Используем JSON mode для точного парсинга
        """
        if not self.openai_client:
            logger.warning("OpenAI client not available")
            return None

        logger.info(f"Stage 3: Analyzing document with AI")

        try:
            # Извлекаем текст из документа
            data = doc_info.file_path.read_bytes()

            # Определяем тип и извлекаем текст
            is_pdf = data.lstrip().startswith(b"%PDF") or (
                doc_info.content_type and "pdf" in doc_info.content_type.lower()
            )

            if is_pdf:
                text = extract_text_from_pdf(data)
            else:
                text = extract_text_from_html(data)

            logger.debug(f"Extracted {len(text)} characters from document")

            # Оптимизация: извлекаем только релевантные части
            optimized_text = self._extract_relevant_text(text, part)

            # Ограничиваем размер текста для экономии токенов
            if len(optimized_text) > self.MAX_TEXT_SIZE_FOR_AI:
                optimized_text = optimized_text[:self.MAX_TEXT_SIZE_FOR_AI]
                logger.info(f"Text truncated from {len(text)} to {self.MAX_TEXT_SIZE_FOR_AI} characters (~{self.MAX_TEXT_SIZE_FOR_AI//4} tokens)")
            else:
                logger.debug(f"Optimized text: {len(optimized_text)} chars (~{len(optimized_text)//4} tokens)")

            logger.debug(f"Text preview: {optimized_text[:150]}...")

            # Оптимизированный промпт (минимум токенов)
            system_prompt = (
                "Extract manufacturer and part number from datasheet. "
                "Return JSON: {\"manufacturer\": \"name\", \"part_number\": \"number\", \"confidence\": 0.0-1.0}"
            )

            user_prompt = f"Datasheet text:\n{optimized_text}\n\nTarget part: {part.part_number}"

            # Логируем запрос
            await self.log_recorder.record(
                provider="openai-document",
                direction="request",
                query=part.part_number,
                payload=json.dumps({
                    "model": settings.openai_model_default,
                    "text_length": len(optimized_text),
                    "document_url": doc_info.url
                })
            )

            # Вызываем OpenAI
            completion = await self.openai_client.chat.completions.create(
                model=settings.openai_model_default,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0,
                max_tokens=150,  # Минимум токенов для ответа
                response_format={"type": "json_object"}
            )

            # Парсим ответ
            if not completion.choices[0].message or not completion.choices[0].message.content:
                return None

            response_text = completion.choices[0].message.content
            result = json.loads(response_text)

            # Логируем ответ
            await self.log_recorder.record(
                provider="openai-document",
                direction="response",
                query=part.part_number,
                status_code=200,
                payload=response_text
            )

            manufacturer = result.get("manufacturer")
            confidence = float(result.get("confidence", 0.7))

            if not manufacturer:
                return None

            # Нормализуем название производителя
            normalized = normalize_manufacturer_name(manufacturer)

            logger.info(f"AI identified manufacturer: {normalized} (confidence: {confidence})")

            return SearchCandidate(
                manufacturer=normalized,
                confidence=confidence,
                source_url=doc_info.url,
                debug_info=f"Extracted from document via AI (tokens used: ~{len(optimized_text)//4})",
                alias_used=part.manufacturer_hint if part.manufacturer_hint else None
            )

        except Exception as e:
            logger.error(f"Failed to analyze document with AI: {e}")
            return None

    async def _cleanup_document(self, doc_info: DocumentInfo) -> None:
        """Удаляет временный документ после обработки."""
        try:
            if doc_info.file_path.exists():
                doc_info.file_path.unlink()
                logger.debug(f"Cleaned up document: {doc_info.file_path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup document {doc_info.file_path}: {e}")

    def _get_manufacturer_from_domain(self, url: str) -> str | None:
        """Определяет производителя по домену URL."""
        try:
            hostname = urlparse(url).hostname
            if not hostname:
                return None

            hostname = hostname.lower()
            for domain, manufacturer in DOMAIN_MANUFACTURER_HINTS.items():
                if hostname == domain or hostname.endswith(f".{domain}"):
                    return manufacturer
        except Exception:
            return None
        return None

    def _analyze_text_heuristically(
        self,
        text: str,
        part: PartBase,
        url: str
    ) -> SearchCandidate | None:
        """Анализирует текст с помощью эвристик без AI."""
        text_lower = text.lower()

        # Нормализуем артикул для сравнения (убираем пробелы, дефисы)
        part_number_normalized = part.part_number.replace(" ", "").replace("-", "").replace("_", "").lower()

        # Проверяем известных производителей в тексте
        for known_mfr in KNOWN_MANUFACTURERS:
            if known_mfr.lower() in text_lower:
                # Проверяем артикул в разных форматах
                # 1. Точное совпадение
                if part.part_number.lower() in text_lower:
                    return SearchCandidate(
                        manufacturer=known_mfr,
                        confidence=0.90,
                        source_url=url,
                        debug_info=f"Found '{known_mfr}' with exact part number match",
                        alias_used=part.manufacturer_hint
                    )

                # 2. Нормализованное совпадение (без пробелов/дефисов)
                text_normalized = text_lower.replace(" ", "").replace("-", "").replace("_", "")
                if part_number_normalized in text_normalized:
                    return SearchCandidate(
                        manufacturer=known_mfr,
                        confidence=0.85,
                        source_url=url,
                        debug_info=f"Found '{known_mfr}' with normalized part number match",
                        alias_used=part.manufacturer_hint
                    )

        # Если manufacturer_hint указан, проверяем его в тексте
        if part.manufacturer_hint:
            hint_lower = part.manufacturer_hint.lower()
            if hint_lower in text_lower:
                # Проверяем совпадение артикула
                if part.part_number.lower() in text_lower or part_number_normalized in text_lower.replace(" ", "").replace("-", ""):
                    return SearchCandidate(
                        manufacturer=part.manufacturer_hint,
                        confidence=0.80,
                        source_url=url,
                        debug_info=f"Found manufacturer hint '{part.manufacturer_hint}' with part number",
                        alias_used=part.manufacturer_hint
                    )

        return None

    def _is_likely_document(self, url: str, title: str) -> bool:
        """Проверяет, является ли URL вероятно документом."""
        url_lower = url.lower()
        title_lower = title.lower()

        # Проверяем расширение файла
        if any(url_lower.endswith(ext) for ext in [".pdf", ".doc", ".docx"]):
            return True

        # Проверяем ключевые слова
        for keyword in self.DATASHEET_KEYWORDS:
            if keyword in url_lower or keyword in title_lower:
                return True

        return False

    def _extract_relevant_text(self, text: str, part: PartBase) -> str:
        """
        Извлекает только релевантные части текста для экономии токенов.

        Стратегия:
        1. Ищем упоминания артикула
        2. Берем контекст вокруг упоминаний
        3. Добавляем первые строки (обычно там header/title)
        """
        lines = text.splitlines()
        relevant_lines = []

        # Добавляем первые 10 строк (обычно содержат заголовок и производителя)
        relevant_lines.extend(lines[:10])

        # Ищем строки с упоминанием артикула
        part_lower = part.part_number.lower()
        for i, line in enumerate(lines):
            if part_lower in line.lower():
                # Берем контекст: 2 строки до и 2 после
                start = max(0, i - 2)
                end = min(len(lines), i + 3)
                relevant_lines.extend(lines[start:end])

        # Если есть подсказка производителя, ищем его упоминания
        if part.manufacturer_hint:
            hint_lower = part.manufacturer_hint.lower()
            for i, line in enumerate(lines):
                if hint_lower in line.lower():
                    start = max(0, i - 1)
                    end = min(len(lines), i + 2)
                    relevant_lines.extend(lines[start:end])

        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_lines = []
        for line in relevant_lines:
            if line not in seen and line.strip():
                seen.add(line)
                unique_lines.append(line)

        return "\n".join(unique_lines)

    def _evaluate_match(
        self,
        submitted: str | None,
        resolved: str | None
    ) -> tuple[str | None, float | None]:
        """Оценивает совпадение между поданным и найденным производителем."""
        if not submitted:
            return None, None
        if not resolved:
            return "pending", None

        score = fuzz.WRatio(submitted, resolved)
        status = "matched" if score >= 70 else "mismatch"
        return status, score / 100

    async def search_part(
        self,
        part: PartBase,
        *,
        debug: bool = False
    ) -> SearchResult:
        """
        Основной метод поиска с оптимизированной логикой.

        Порядок выполнения:
        1. Простой веб-поиск (эвристики)
        2. Поиск документов
        3. Анализ документов через OpenAI (если нужно)
        """
        stage_history: list[StageStatus] = []
        final_candidate: SearchCandidate | None = None
        final_stage: str | None = None

        # Проверяем, есть ли уже результат в базе
        stmt = select(Part).where(Part.part_number == part.part_number).order_by(Part.id.desc())
        existing_part = (await self.session.execute(stmt)).scalars().first()

        if existing_part and existing_part.manufacturer_name:
            match_status, match_confidence = self._evaluate_match(
                part.manufacturer_hint,
                existing_part.manufacturer_name
            )

            if not part.manufacturer_hint or match_status == "matched":
                stage_history.append(
                    StageStatus(
                        name="Internet",
                        status="skipped",
                        message="Использован ранее найденный результат из БД"
                    )
                )
                stage_history.append(
                    StageStatus(
                        name="Document Search",
                        status="skipped",
                        message="Использован ранее найденный результат из БД"
                    )
                )
                stage_history.append(
                    StageStatus(
                        name="AI Analysis",
                        status="skipped",
                        message="Использован ранее найденный результат из БД"
                    )
                )

                return SearchResult(
                    part_number=part.part_number,
                    manufacturer_name=existing_part.manufacturer_name,
                    alias_used=existing_part.alias_used,
                    confidence=existing_part.confidence,
                    source_url=existing_part.source_url,
                    debug_log=existing_part.debug_log if debug else None,
                    search_stage="cache",
                    stage_history=stage_history,
                    submitted_manufacturer=part.manufacturer_hint,
                    match_status=match_status,
                    match_confidence=match_confidence
                )

        # Этап 1: Простой веб-поиск
        try:
            candidate = await self._simple_web_search(part, self._get_all_providers())
            if candidate:
                final_candidate = candidate
                final_stage = "Internet"
                stage_history.append(
                    StageStatus(
                        name="Internet",
                        status="success",
                        confidence=candidate.confidence,
                        provider="heuristics",
                        message="Производитель найден через простой поиск"
                    )
                )
                # Пропускаем остальные этапы
                stage_history.append(
                    StageStatus(
                        name="Document Search",
                        status="skipped",
                        message="Не требуется, результат найден на предыдущем этапе"
                    )
                )
                stage_history.append(
                    StageStatus(
                        name="AI Analysis",
                        status="skipped",
                        message="Не требуется, результат найден на предыдущем этапе"
                    )
                )
            else:
                stage_history.append(
                    StageStatus(
                        name="Internet",
                        status="no-results",
                        message="Простой поиск не дал результатов, переход к поиску документов"
                    )
                )
        except Exception as e:
            logger.error(f"Stage 1 (Simple Search) failed: {e}")
            stage_history.append(
                StageStatus(
                    name="Internet",
                    status="no-results",
                    message=f"Ошибка поиска: {str(e)}"
                )
            )

        # Этап 2: Поиск и анализ документов (только если этап 1 не дал результатов)
        if not final_candidate:
            try:
                doc_urls = await self._search_for_documents(part, self._get_all_providers())

                if doc_urls:
                    stage_history.append(
                        StageStatus(
                            name="Document Search",
                            status="success",
                            urls_considered=len(doc_urls),
                            message=f"Найдено {len(doc_urls)} документов для анализа"
                        )
                    )

                    # Этап 3: Анализ документов через AI
                    for doc_url in doc_urls:
                        doc_info = await self._download_document(doc_url)
                        if not doc_info:
                            continue

                        try:
                            candidate = await self._analyze_document_with_ai(doc_info, part)
                            if candidate:
                                final_candidate = candidate
                                final_stage = "AI Analysis"
                                stage_history.append(
                                    StageStatus(
                                        name="AI Analysis",
                                        status="success",
                                        confidence=candidate.confidence,
                                        provider="openai-document",
                                        message=f"Производитель извлечен из документа: {doc_url}"
                                    )
                                )
                                break
                        finally:
                            # Всегда удаляем документ после обработки
                            await self._cleanup_document(doc_info)

                    if not final_candidate:
                        stage_history.append(
                            StageStatus(
                                name="AI Analysis",
                                status="no-results",
                                message="AI не смог извлечь производителя из документов"
                            )
                        )
                else:
                    stage_history.append(
                        StageStatus(
                            name="Document Search",
                            status="no-results",
                            message="Документы не найдены"
                        )
                    )
                    stage_history.append(
                        StageStatus(
                            name="AI Analysis",
                            status="skipped",
                            message="Нет документов для анализа"
                        )
                    )
            except Exception as e:
                logger.error(f"Stage 2/3 (Document Search/AI) failed: {e}")
                stage_history.append(
                    StageStatus(
                        name="Document Search",
                        status="no-results",
                        message=f"Ошибка: {str(e)}"
                    )
                )
                stage_history.append(
                    StageStatus(
                        name="AI Analysis",
                        status="no-results",
                        message="Не выполнен из-за ошибки на предыдущем этапе"
                    )
                )

        # Если ничего не найдено
        if not final_candidate:
            submitted = part.manufacturer_hint
            match_status: str | None = None
            match_confidence: float | None = None

            if submitted:
                target = existing_part or Part(part_number=part.part_number)
                if not existing_part:
                    self.session.add(target)
                target.submitted_manufacturer = submitted
                target.match_status = "pending"
                target.match_confidence = None
                target.debug_log = "No manufacturer found after all stages"
                target.stage_history = [stage.dict() for stage in stage_history]  # Сохраняем историю этапов
                await self.session.flush()

            return SearchResult(
                part_number=part.part_number,
                manufacturer_name=None,
                alias_used=part.manufacturer_hint,
                confidence=None,
                source_url=None,
                debug_log="No manufacturer found" if debug else None,
                search_stage=None,
                stage_history=stage_history,
                submitted_manufacturer=submitted,
                match_status="pending",
                match_confidence=None
            )

        # Сохраняем результат
        normalized_manufacturer = normalize_manufacturer_name(final_candidate.manufacturer)
        manufacturer = await self.resolver.resolve(normalized_manufacturer)

        if final_candidate.alias_used:
            await self.resolver.sync_aliases(manufacturer, [final_candidate.alias_used])

        manufacturer_name = manufacturer.name

        # Извлекаем дополнительную информацию о производителе
        manufacturer_info = await self.info_extractor.extract_info(manufacturer_name)

        if existing_part:
            target = existing_part
            target.manufacturer = manufacturer
        else:
            target = Part(part_number=part.part_number, manufacturer=manufacturer)
            self.session.add(target)

        match_status, match_confidence = self._evaluate_match(
            part.manufacturer_hint,
            manufacturer_name
        )

        target.manufacturer_name = manufacturer_name
        target.alias_used = final_candidate.alias_used
        target.submitted_manufacturer = part.manufacturer_hint
        target.match_status = match_status
        target.match_confidence = match_confidence
        target.confidence = final_candidate.confidence
        target.source_url = final_candidate.source_url
        target.debug_log = final_candidate.debug_info if debug else None
        target.search_stage = final_stage
        target.stage_history = [stage.dict() for stage in stage_history]  # Сохраняем историю этапов
        target.what_produces = manufacturer_info.what_produces
        target.website = manufacturer_info.website
        target.manufacturer_aliases = manufacturer_info.manufacturer_aliases
        target.country = manufacturer_info.country

        await self.session.flush()

        return SearchResult(
            part_number=part.part_number,
            manufacturer_name=manufacturer_name,
            alias_used=final_candidate.alias_used,
            confidence=final_candidate.confidence,
            source_url=final_candidate.source_url,
            debug_log=final_candidate.debug_info if debug else None,
            search_stage=final_stage,
            stage_history=stage_history,
            submitted_manufacturer=part.manufacturer_hint,
            match_status=match_status,
            match_confidence=match_confidence,
            what_produces=manufacturer_info.what_produces,
            website=manufacturer_info.website,
            manufacturer_aliases=manufacturer_info.manufacturer_aliases,
            country=manufacturer_info.country
        )

    async def search_many(
        self,
        items: list[PartBase],
        *,
        debug: bool = False
    ) -> list[SearchResult]:
        """Поиск множества деталей с ограничением параллельности."""
        semaphore = asyncio.Semaphore(3)  # Ограничиваем 3 параллельными запросами

        async def run(item: PartBase) -> SearchResult:
            async with semaphore:
                return await self.search_part(item, debug=debug)

        return await asyncio.gather(*(run(item) for item in items))
