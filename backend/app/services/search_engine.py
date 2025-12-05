from __future__ import annotations

import asyncio
import json
from collections import Counter
from dataclasses import dataclass
from typing import List
from urllib.parse import urlparse

import httpx
from loguru import logger
from openai import AsyncOpenAI
from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.http import httpx_client_kwargs
from app.models.part import Manufacturer, ManufacturerAlias, Part
from app.schemas.part import PartBase, SearchResult, StageStatus

from .document_parser import extract_from_urls
from .log_recorder import SearchLogRecorder
from .search_providers import (
    SearchProvider,
    get_default_providers,
    get_fallback_provider,
    get_google_provider,
)

settings = get_settings()


@dataclass
class ManufacturerInfo:
    """Дополнительная информация о производителе"""
    what_produces: str | None = None
    website: str | None = None
    manufacturer_aliases: str | None = None
    country: str | None = None


class ManufacturerInfoExtractor:
    """Извлечение дополнительной информации о производителе через OpenAI"""

    def __init__(self):
        if settings.openai_api_key:
            http_client = httpx.AsyncClient(**httpx_client_kwargs())
            self.client = AsyncOpenAI(api_key=settings.openai_api_key, http_client=http_client)
            self.model = settings.openai_model_default
        else:
            self.client = None
            logger.warning("OpenAI API key is missing. Manufacturer info extraction disabled.")

    async def extract_info(self, manufacturer_name: str) -> ManufacturerInfo:
        """Извлекает информацию о производителе"""
        if not self.client:
            return ManufacturerInfo()

        try:
            system_prompt = (
                "You are an electronics industry expert. Given a manufacturer name, "
                "provide structured information about them. "
                "Respond ONLY with valid JSON in this exact format: "
                '{"what_produces": "brief description of what they produce", '
                '"website": "official website URL", '
                '"aliases": "comma-separated alternative names/brands", '
                '"country": "country of origin"}. '
                "Keep descriptions concise (under 100 chars). If information is unknown, use null."
            )

            user_prompt = f"Provide information about manufacturer: {manufacturer_name}"

            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
                max_tokens=300,
            )

            if not completion.choices[0].message:
                return ManufacturerInfo()

            output = completion.choices[0].message.content
            if not output:
                return ManufacturerInfo()

            # Извлекаем JSON из ответа (может быть обернут в markdown)
            if "```json" in output:
                output = output.split("```json")[1].split("```")[0].strip()
            elif "```" in output:
                output = output.split("```")[1].split("```")[0].strip()

            data = json.loads(output)

            return ManufacturerInfo(
                what_produces=data.get("what_produces"),
                website=data.get("website"),
                manufacturer_aliases=data.get("aliases"),
                country=data.get("country"),
            )

        except json.JSONDecodeError:
            logger.debug(f"Failed to parse JSON from OpenAI for manufacturer: {manufacturer_name}")
            return ManufacturerInfo()
        except Exception as e:
            logger.debug(f"Error extracting manufacturer info for {manufacturer_name}: {e}")
            return ManufacturerInfo()


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
    "samsung.com": "Samsung",
    "semtech.com": "Semtech",
    "sibeco.net": "Sibeco",
    "sibeco-russia.ru": "Sibeco",
}

KNOWN_MANUFACTURERS: list[str] = [
    # Английские названия (канонические)
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
    "Samsung",
    "Samsung Semiconductor",
    "Sibeco",

    # Русские названия
    "СИБЕКО",
    "Сибеко",

    # Китайские названия (упрощенные)
    "德州仪器",  # Texas Instruments
    "亚德诺半导体",  # Analog Devices
    "意法半导体",  # STMicroelectronics
    "恩智浦",  # NXP
    "英飞凌",  # Infineon
    "瑞萨电子",  # Renesas
    "三星",  # Samsung
    "博通",  # Broadcom
    "微芯科技",  # Microchip
    "美信",  # Maxim
    "安森美",  # onsemi
    "罗姆",  # ROHM
    "威世",  # Vishay

    # Тайваньские названия (традиционный китайский)
    "意法半導體",  # STMicroelectronics
    "恩智浦半導體",  # NXP
    "英飛凌",  # Infineon
    "瑞薩電子",  # Renesas
    "三星電子",  # Samsung
    "美信半導體",  # Maxim
    "安森美半導體",  # onsemi
    "羅姆半導體",  # ROHM
    "威世半導體",  # Vishay

    # Японские названия
    "テキサス・インスツルメンツ",  # Texas Instruments
    "アナログ・デバイセズ",  # Analog Devices
    "エスティーマイクロエレクトロニクス",  # STMicroelectronics
    "エヌエックスピー",  # NXP
    "インフィニオン",  # Infineon
    "ルネサスエレクトロニクス",  # Renesas
    "サムスン",  # Samsung
    "ブロードコム",  # Broadcom
    "マイクロチップ",  # Microchip
    "マキシム",  # Maxim
    "オン・セミコンダクター",  # onsemi
    "ローム",  # ROHM
    "ヴィシェイ",  # Vishay

    # Корейские названия
    "텍사스 인스트루먼트",  # Texas Instruments
    "아날로그 디바이스",  # Analog Devices
    "에스티마이크로일렉트로닉스",  # STMicroelectronics
    "엔엑스피",  # NXP
    "인피니언",  # Infineon
    "르네사스",  # Renesas
    "삼성",  # Samsung
    "브로드컴",  # Broadcom
    "마이크로칩",  # Microchip
    "맥심",  # Maxim
    "온세미",  # onsemi
    "롬",  # ROHM
    "비셰이",  # Vishay
]

# Многоязычный словарь производителей
# Формат: {вариант_на_любом_языке: каноническое_английское_название}
MULTILINGUAL_MANUFACTURERS: dict[str, str] = {
    # Sibeco (Россия)
    "сибеко": "Sibeco",
    "сибэко": "Sibeco",
    "сибеко россия": "Sibeco",

    # Texas Instruments
    "德州仪器": "Texas Instruments",  # Китайский
    "テキサス・インスツルメンツ": "Texas Instruments",  # Японский
    "텍사스 인스트루먼트": "Texas Instruments",  # Корейский
    "ti": "Texas Instruments",

    # Analog Devices
    "亚德诺半导体": "Analog Devices",  # Китайский
    "アナログ・デバイセズ": "Analog Devices",  # Японский
    "아날로그 디바이스": "Analog Devices",  # Корейский
    "adi": "Analog Devices",

    # STMicroelectronics
    "意法半导体": "STMicroelectronics",  # Китайский
    "意法半導體": "STMicroelectronics",  # Тайваньский (традиционный китайский)
    "エスティーマイクロエレクトロニクス": "STMicroelectronics",  # Японский
    "에스티마이크로일렉트로닉스": "STMicroelectronics",  # Корейский
    "st": "STMicroelectronics",
    "stm": "STMicroelectronics",

    # NXP Semiconductors
    "恩智浦": "NXP Semiconductors",  # Китайский
    "恩智浦半導體": "NXP Semiconductors",  # Тайваньский
    "エヌエックスピー": "NXP Semiconductors",  # Японский
    "엔엑스피": "NXP Semiconductors",  # Корейский

    # Infineon Technologies
    "英飞凌": "Infineon Technologies",  # Китайский
    "英飛凌": "Infineon Technologies",  # Тайваньский
    "インフィニオン": "Infineon Technologies",  # Японский
    "인피니언": "Infineon Technologies",  # Корейский

    # Renesas Electronics
    "瑞萨电子": "Renesas Electronics",  # Китайский
    "瑞薩電子": "Renesas Electronics",  # Тайваньский
    "ルネサスエレクトロニクス": "Renesas Electronics",  # Японский
    "르네사스": "Renesas Electronics",  # Корейский

    # Samsung
    "三星": "Samsung",  # Китайский
    "三星電子": "Samsung",  # Тайваньский
    "サムスン": "Samsung",  # Японский
    "삼성": "Samsung",  # Корейский
    "samsung electronics": "Samsung",

    # Broadcom
    "博通": "Broadcom",  # Китайский
    "博通公司": "Broadcom",  # Китайский (полное)
    "ブロードコム": "Broadcom",  # Японский
    "브로드컴": "Broadcom",  # Корейский

    # Microchip Technology
    "微芯科技": "Microchip Technology",  # Китайский
    "微芯科技公司": "Microchip Technology",  # Китайский (полное)
    "マイクロチップ": "Microchip Technology",  # Японский
    "마이크로칩": "Microchip Technology",  # Корейский

    # Maxim Integrated
    "美信": "Maxim Integrated",  # Китайский
    "美信半導體": "Maxim Integrated",  # Тайваньский
    "マキシム": "Maxim Integrated",  # Японский
    "맥심": "Maxim Integrated",  # Корейский

    # ON Semiconductor / onsemi
    "安森美": "onsemi",  # Китайский
    "安森美半導體": "onsemi",  # Тайваньский
    "オン・セミコンダクター": "onsemi",  # Японский
    "온세미": "onsemi",  # Корейский
    "on semiconductor": "onsemi",

    # ROHM Semiconductor
    "罗姆": "ROHM Semiconductor",  # Китайский
    "羅姆半導體": "ROHM Semiconductor",  # Тайваньский
    "ローム": "ROHM Semiconductor",  # Японский
    "롬": "ROHM Semiconductor",  # Корейский

    # Vishay
    "威世": "Vishay Intertechnology",  # Китайский
    "威世半導體": "Vishay Intertechnology",  # Тайваньский
    "ヴィシェイ": "Vishay Intertechnology",  # Японский
    "비셰이": "Vishay Intertechnology",  # Корейский
}


def normalize_manufacturer_name(name: str) -> str:
    """
    Нормализует название производителя на любом языке к каноническому английскому названию.

    Поддерживаемые языки:
    - Английский, Русский, Немецкий, Французский, Испанский, Итальянский
    - Китайский (упрощенный и традиционный)
    - Японский, Корейский
    """
    normalized = name.strip()
    lower_name = normalized.lower()

    # Прямое совпадение в многоязычном словаре
    if lower_name in MULTILINGUAL_MANUFACTURERS:
        return MULTILINGUAL_MANUFACTURERS[lower_name]

    # Fuzzy matching для обработки опечаток и вариаций
    # Проверяем совпадение с каждым вариантом в словаре
    best_match = None
    best_score = 0

    for variant, canonical in MULTILINGUAL_MANUFACTURERS.items():
        # Для латиницы и кириллицы используем fuzzy matching
        # Для иероглифов проверяем точное совпадение или вхождение
        if any(ord(c) > 0x4E00 for c in variant):  # Китайские/японские иероглифы
            if variant in lower_name or lower_name in variant:
                return canonical
        else:
            score = fuzz.ratio(lower_name, variant)
            if score > best_score and score > 85:
                best_score = score
                best_match = canonical

    if best_match:
        return best_match

    return normalized


NOISY_PHRASES = (
    "verify you are",
    "captcha",
    "cloudflare",
    "human verification",
    "are you a robot",
)

STOPWORDS = {
    "verify",
    "you",
    "are",
    "please",
    "continue",
    "with",
    "the",
    "and",
    "this",
}

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
        stmt = (
            select(Manufacturer)
            .options(selectinload(Manufacturer.aliases))
            .where(Manufacturer.name.ilike(name))
        )
        result = await self.session.execute(stmt)
        manufacturer = result.scalar_one_or_none()
        if manufacturer:
            return manufacturer

        manufacturer = Manufacturer(name=name)
        self.session.add(manufacturer)
        await self.session.flush()
        return manufacturer

    async def sync_aliases(self, manufacturer: Manufacturer, aliases: List[str]) -> None:
        if not aliases:
            return

        stmt = select(ManufacturerAlias).where(
            ManufacturerAlias.manufacturer_id == manufacturer.id
        )
        result = await self.session.execute(stmt)
        existing = {alias.name.lower(): alias for alias in result.scalars()}

        for alias in aliases:
            key = alias.lower()
            if key not in existing:
                self.session.add(
                    ManufacturerAlias(name=alias, manufacturer_id=manufacturer.id)
                )
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
        self.log_recorder = SearchLogRecorder(session)
        self.providers = providers or get_default_providers()
        self.google_provider = google_provider or get_google_provider()
        self.fallback_provider = fallback_provider or get_fallback_provider()
        self._attach_recorder()
        self.resolver = ManufacturerResolver(session)
        self.info_extractor = ManufacturerInfoExtractor()

    def _attach_recorder(self) -> None:
        for provider in [*self.providers, self.google_provider, self.fallback_provider]:
            if hasattr(provider, "set_recorder"):
                provider.set_recorder(self.log_recorder)

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
        # Формируем запросы от простых к специфичным
        queries = []

        # Проверяем, есть ли латинский эквивалент для кириллического названия
        latin_hint = None
        if part.manufacturer_hint:
            latin_hint = normalize_manufacturer_name(part.manufacturer_hint)
            # Если нормализация дала другое название, значит была кириллица
            if latin_hint != part.manufacturer_hint:
                logger.debug(f"Normalized manufacturer hint: {part.manufacturer_hint} -> {latin_hint}")

        # Самый простой запрос - артикул + производитель (как в браузере)
        if part.manufacturer_hint:
            queries.append(f"{part.part_number} {part.manufacturer_hint}")
            # Добавляем латинский вариант, если он отличается
            if latin_hint and latin_hint != part.manufacturer_hint:
                queries.append(f"{part.part_number} {latin_hint}")

        # Просто артикул
        queries.append(part.part_number)

        # Более специфичные запросы
        if part.manufacturer_hint:
            queries.append(f"{part.part_number} {part.manufacturer_hint} datasheet")
            if latin_hint and latin_hint != part.manufacturer_hint:
                queries.append(f"{part.part_number} {latin_hint} datasheet")

        queries.extend([
            f"{part.part_number} datasheet manufacturer",
            f"{part.part_number} pdf",
        ])

        urls: list[str] = []
        for provider in providers:
            for query in filter(None, queries):
                urls.extend(await self._search_with_provider(provider, query))
                if len(urls) >= 15:  # Увеличили лимит для лучшего покрытия
                    break
            if len(urls) >= 15:
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
        # Увеличили количество анализируемых URL для лучшего покрытия
        contents = await extract_from_urls(urls[:10])
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
        candidates = [
            line
            for line in lines
            if part.part_number.lower() in line.lower()
            and not any(phrase in line.lower() for phrase in NOISY_PHRASES)
        ]
        if not candidates and part.manufacturer_hint:
            candidates = [
                line
                for line in lines
                if part.manufacturer_hint.lower() in line.lower()
                and not any(phrase in line.lower() for phrase in NOISY_PHRASES)
            ]
        if not candidates:
            keyword_lines = [
                line
                for line in lines
                if any(keyword in line.lower() for keyword in KEYWORD_HINTS)
                and not any(phrase in line.lower() for phrase in NOISY_PHRASES)
            ]
            if keyword_lines:
                candidates = keyword_lines[:20]
        if not candidates:
            candidates = [
                line
                for line in lines[:20]
                if not any(phrase in line.lower() for phrase in NOISY_PHRASES)
            ]

        manufacturer_names: list[str] = []
        for line in candidates:
            tokens = [
                token.strip(" ,.;:()[]\"'")
                for token in line.split()
                # Изменили условие: разрешаем токены с буквами и цифрами/дефисами
                if any(c.isalpha() for c in token) and len(token) > 2
            ]
            filtered_tokens = [t for t in tokens if t.lower() not in STOPWORDS]
            if not filtered_tokens:
                continue
            if tokens:
                manufacturer_names.append(" ".join(filtered_tokens[:3]))
        if not manufacturer_names:
            return None

        best_known: tuple[str, float] | None = None
        for name in manufacturer_names:
            match = process.extractOne(name, KNOWN_MANUFACTURERS, scorer=fuzz.WRatio)
            if match:
                score = match[1]
                if not best_known or score > best_known[1]:
                    best_known = (match[0], score)
        # Снизили порог с 82 до 75 для большей гибкости
        if best_known and best_known[1] >= 75:
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
            # Снизили порог с 67 до 60 для лучшего распознавания вариантов написания
            if match and match[1] >= 60:
                confidence = max(0.60, match[1] / 100)
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
        most_common = counts.most_common(1)[0][0]
        # Нормализуем название (кириллица -> латиница)
        return normalize_manufacturer_name(most_common)

    def _alias_if_similar(self, part: PartBase, manufacturer: str) -> str | None:
        if not part.manufacturer_hint:
            return None

        # Проверяем прямое сходство
        score = fuzz.WRatio(part.manufacturer_hint, manufacturer)
        if score >= 60:
            return part.manufacturer_hint

        # Проверяем сходство нормализованной подсказки с производителем
        normalized_hint = normalize_manufacturer_name(part.manufacturer_hint)
        if normalized_hint != part.manufacturer_hint:
            score_normalized = fuzz.WRatio(normalized_hint, manufacturer)
            if score_normalized >= 60:
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

    async def search_part(self, part: PartBase, *, debug: bool = False, stages: list[str] | None = None) -> SearchResult:
        stage_history: list[StageStatus] = []
        final_candidate: Candidate | None = None
        final_stage: str | None = None
        all_candidates: list[tuple[Candidate, str]] = []  # Все кандидаты (candidate, stage_name)

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

        # Требуем уверенность результата ещё на первом этапе, чтобы при сомнительных
        # совпадениях поиск продолжил работу через Google CSE и OpenAI, вместо того
        # чтобы останавливаться на эвристике с низкой достоверностью.
        all_stage_configs: list[StageConfig] = [
            StageConfig("Internet", self.providers, confidence_threshold=0.75),
            StageConfig(
                "googlesearch",
                [self.google_provider] if self.google_provider else [],
                confidence_threshold=0.67,
            )
        ]

        # Если указаны конкретные этапы, выполняем только их
        if stages:
            stage_configs = [config for config in all_stage_configs if config.name in stages]
        else:
            stage_configs = all_stage_configs

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
                # Сохраняем всех кандидатов для последующего выбора лучшего
                all_candidates.append((candidate, config.name))

                if config.confidence_threshold and candidate.confidence < config.confidence_threshold:
                    status = "low-confidence"
                    message = (
                        f"Достоверность {candidate.confidence:.2f} ниже порога "
                        f"{config.confidence_threshold:.2f}. Переход к следующему этапу"
                    )
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

        # Проверяем, нужен ли OpenAI этап
        should_run_openai = True
        if stages:
            # Если указаны конкретные этапы, проверяем, есть ли OpenAI в списке
            should_run_openai = "OpenAI" in stages
        else:
            # Иначе запускаем OpenAI только если результат недостаточно хорош
            should_run_openai = final_candidate is None or (
                final_candidate.confidence is not None and final_candidate.confidence < 0.8
            )

        if should_run_openai:
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
                # Сохраняем кандидата от OpenAI
                all_candidates.append((candidate, "OpenAI"))

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

        # Если нет финального кандидата с высокой уверенностью, выбираем лучший из всех найденных
        if not final_candidate and all_candidates:
            # Сортируем по confidence и выбираем лучший
            best_candidate, best_stage = max(all_candidates, key=lambda x: x[0].confidence)
            final_candidate = best_candidate
            final_stage = best_stage

            # Обновляем сообщение для этапа, откуда взят результат
            for idx, stage in enumerate(stage_history):
                if stage.name == best_stage and stage.status == "low-confidence":
                    extra_msg = (
                        f"Использован результат с достоверностью {best_candidate.confidence:.2f} "
                        f"как лучший из всех этапов поиска"
                    )
                    stage_history[idx] = stage.model_copy(
                        update={
                            "status": "success",
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

        # Нормализуем название производителя (преобразуем кириллицу в латиницу)
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
        # Сохраняем дополнительную информацию о производителе
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
            debug_log=final_candidate.debug_log if debug else None,
            search_stage=final_stage,
            stage_history=stage_history,
            submitted_manufacturer=part.manufacturer_hint,
            match_status=match_status,
            match_confidence=match_confidence,
            what_produces=manufacturer_info.what_produces,
            website=manufacturer_info.website,
            manufacturer_aliases=manufacturer_info.manufacturer_aliases,
            country=manufacturer_info.country,
        )

    async def search_many(self, items: list[PartBase], *, debug: bool = False, stages: list[str] | None = None) -> list[SearchResult]:
        semaphore = asyncio.Semaphore(4)

        async def run(item: PartBase) -> SearchResult:
            async with semaphore:
                return await self.search_part(item, debug=debug, stages=stages)

        return await asyncio.gather(*(run(item) for item in items))
