"""Поисковые провайдеры.

* ``yahoo`` / ``bing`` / ``duckduckgo`` / ``googlesearch`` — бесплатный поиск через HTML-выдачу;
  провайдер, упёршийся в капчу/заглушку, временно отключается и не тратит время;
* ``serpapi:<engine>`` и ``google-custom-search`` — платные API (при наличии ключей).

Все провайдеры используют общий HTTP-клиент (keep-alive, прокси из настроек),
кешируют удачные ответы и пишут компактные логи запросов/ответов.
"""
from __future__ import annotations

import asyncio
import base64
import random
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Any, ClassVar
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from app.core.config import get_settings
from app.core.http import get_http_client
from app.services.log_recorder import SearchLogRecorder, serialize_payload
from app.services.telegram_notifier import notify_admins

settings = get_settings()


class ProviderBlocked(Exception):
    """Поисковик вернул капчу/заглушку или исчерпан лимит — провайдер временно отключается."""

    def __init__(self, reason: str, cooldown: float | None = None) -> None:
        super().__init__(reason)
        self.cooldown = cooldown


class SearchProvider(ABC):
    name: str = "provider"
    #: "web" — бесплатная выдача, "api" — платный API
    kind: str = "web"
    concurrency: int = 2
    block_cooldown: float = 900.0
    cache_ttl: float = 3600.0
    cache_size: ClassVar[int] = 2000

    _blocked_until: ClassVar[dict[str, float]] = {}
    _semaphores: ClassVar[dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Semaphore]]] = {}
    _cache: ClassVar["OrderedDict[tuple[str, str, int], tuple[float, list[dict[str, Any]]]]"] = OrderedDict()
    _irrelevant_streak: ClassVar[dict[str, int]] = {}
    #: после стольких подряд «мусорных» выдач (когда другой поисковик нашёл артикул)
    #: провайдер считается заблокированным — так ведёт себя Bing при анти-бот защите
    irrelevant_limit: int = 2

    def __init__(self) -> None:
        self.log_recorder: SearchLogRecorder | None = None

    # --- служебное ---------------------------------------------------------------
    def set_recorder(self, recorder: SearchLogRecorder | None) -> None:
        self.log_recorder = recorder

    @property
    def configured(self) -> bool:
        """Есть ли всё необходимое (ключи) для работы провайдера."""
        return True

    @property
    def available(self) -> bool:
        return self.configured and time.monotonic() >= self._blocked_until.get(self.name, 0.0)

    def block(self, reason: str, cooldown: float | None = None) -> None:
        duration = cooldown if cooldown is not None else self.block_cooldown
        now = time.monotonic()
        already_blocked = self._blocked_until.get(self.name, 0.0) > now
        self._blocked_until[self.name] = max(self._blocked_until.get(self.name, 0.0), now + duration)
        if already_blocked:
            return  # параллельные запросы упёрлись в ту же блокировку — не дублируем предупреждения
        logger.warning("Search provider {name} disabled for {sec:.0f}s: {reason}", name=self.name, sec=duration, reason=reason)
        if self.kind == "api":
            # Платный API перестал отвечать: неверный ключ или исчерпана квота
            quota = any(word in reason.lower() for word in ("429", "quota", "limit", "run out", "searches"))
            notify_admins(f"provider:{self.name}", f"{self.name}: {reason}", low_balance=quota)

    @classmethod
    def reset_state(cls) -> None:
        """Сбрасывает блокировки и кеш (используется в тестах)."""
        cls._blocked_until.clear()
        cls._cache.clear()
        cls._semaphores.clear()
        cls._irrelevant_streak.clear()

    def forget(self, query: str, max_results: int) -> None:
        """Удаляет ответ из кеша (например, если выдача оказалась нерелевантной)."""
        self._cache.pop((self.name, " ".join(query.split()).lower(), max_results), None)

    def mark_relevant(self) -> None:
        self._irrelevant_streak.pop(self.name, None)

    def mark_irrelevant(self) -> None:
        """Поисковик вернул мусор там, где другой нашёл артикул."""
        if self.kind != "web":
            return
        streak = self._irrelevant_streak.get(self.name, 0) + 1
        self._irrelevant_streak[self.name] = streak
        if streak >= self.irrelevant_limit:
            self._irrelevant_streak.pop(self.name, None)
            self.block("нерелевантная выдача (анти-бот защита)")

    def _semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        cached = self._semaphores.get(self.name)
        if cached is None or cached[0] is not loop:
            cached = (loop, asyncio.Semaphore(self.concurrency))
            self._semaphores[self.name] = cached
        return cached[1]

    def _cache_get(self, key: tuple[str, str, int]) -> list[dict[str, Any]] | None:
        item = self._cache.get(key)
        if not item:
            return None
        stored_at, results = item
        if time.monotonic() - stored_at > self.cache_ttl:
            self._cache.pop(key, None)
            return None
        self._cache.move_to_end(key)
        return [dict(result) for result in results]

    def _cache_put(self, key: tuple[str, str, int], results: list[dict[str, Any]]) -> None:
        self._cache[key] = (time.monotonic(), [dict(result) for result in results])
        self._cache.move_to_end(key)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)

    async def _log(
        self,
        direction: str,
        query: str,
        *,
        status_code: int | None = None,
        payload: Any | None = None,
    ) -> None:
        if not self.log_recorder:
            return
        try:
            await self.log_recorder.record(
                provider=self.name,
                direction=direction,
                query=query,
                status_code=status_code,
                payload=serialize_payload(payload) if payload is not None else None,
            )
        except Exception:  # noqa: BLE001 - логирование не должно ломать поиск
            logger.debug("Failed to record search log for {name}", name=self.name)

    async def _get(self, url: str, *, params: dict[str, Any], headers: dict[str, str] | None = None) -> httpx.Response:
        """GET с одной повторной попыткой при сетевых ошибках, 429 и 5xx."""
        client = get_http_client()
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                response = await client.get(url, params=params, headers=headers)
                if response.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                    await asyncio.sleep(0.6 + random.random() * 0.6)
                    continue
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError:
                raise
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt == 0:
                    await asyncio.sleep(0.4 + random.random() * 0.4)
                    continue
                raise
        if last_exc:
            raise last_exc
        raise httpx.HTTPError("Request failed")  # pragma: no cover

    def _request_meta(self, query: str, max_results: int) -> dict[str, Any]:
        return {}

    def _is_block_response(self, response: httpx.Response) -> bool:
        """Признак анти-бот страницы в ответе с HTTP-ошибкой."""
        return False

    # --- публичный API --------------------------------------------------------------
    async def search(self, query: str, *, max_results: int = 10) -> list[dict[str, Any]]:
        """Возвращает список результатов ``{"title", "link", "snippet"}``."""
        query = " ".join(query.split())
        if not query or not self.available:
            return []
        cache_key = (self.name, query.lower(), max_results)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        started = time.monotonic()
        await self._log(
            "request",
            query,
            payload={"provider": self.name, "max_results": max_results, **self._request_meta(query, max_results)},
        )
        try:
            async with self._semaphore():
                results, status_code = await self._search(query, max_results)
        except ProviderBlocked as exc:
            self.block(str(exc), exc.cooldown)
            await self._log("response", query, payload={"error": "blocked", "reason": str(exc)})
            return []
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if self._is_block_response(exc.response):
                self.block(f"anti-bot page (HTTP {code})", 300.0)
            elif code in (401, 403, 429):
                self.block(f"HTTP {code}", 300.0 if code == 429 else None)
            logger.warning("{name} returned HTTP {code} for '{query}'", name=self.name, code=code, query=query)
            await self._log("response", query, status_code=code, payload={"error": exc.response.text[:2000]})
            return []
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            logger.warning("{name} request failed for '{query}': {exc!r}", name=self.name, query=query, exc=exc)
            await self._log("response", query, payload={"error": repr(exc)})
            return []
        except Exception as exc:  # noqa: BLE001
            logger.exception("{name} failed for '{query}'", name=self.name, query=query)
            await self._log("response", query, payload={"error": repr(exc)})
            return []

        results = [item for item in results if item.get("link")][:max_results]
        if results:
            self._cache_put(cache_key, results)
        await self._log(
            "response",
            query,
            status_code=status_code,
            payload={
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "results_count": len(results),
                "results": results,
            },
        )
        return results

    @abstractmethod
    async def _search(self, query: str, max_results: int) -> tuple[list[dict[str, Any]], int | None]:
        """Выполняет запрос; возвращает (результаты, HTTP-статус)."""


# --- Бесплатные провайдеры (HTML-выдача) ------------------------------------------------

_CAPTCHA_MARKERS = ("captcha", "unusual traffic", "are you a robot", "verify you are human", "solve the challenge")


def _text(node: Any) -> str:
    return node.get_text(" ", strip=True) if node is not None else ""


def decode_bing_url(href: str | None) -> str | None:
    """Раскрывает редирект Bing ``/ck/a?...&u=a1<base64>`` в исходный URL."""
    if not href:
        return None
    if "bing.com/ck/a" in href or href.startswith("/ck/a"):
        encoded = parse_qs(urlparse(href).query).get("u", [None])[0]
        if not encoded:
            return None
        if encoded.startswith("a1"):
            encoded = encoded[2:]
        try:
            decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8", "ignore")
        except (ValueError, UnicodeDecodeError):
            return None
        return decoded if decoded.startswith("http") else None
    return href if href.startswith("http") else None


def parse_bing_html(html: str, max_results: int) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict[str, Any]] = []
    for block in soup.select("li.b_algo"):
        anchor = block.select_one("h2 a")
        if anchor is None:
            continue
        link = decode_bing_url(anchor.get("href"))
        if not link:
            continue
        snippet_node = (
            block.select_one("div.b_caption p")
            or block.select_one("p.b_lineclamp2, p.b_lineclamp3, p.b_lineclamp4, p.b_algoSlug")
            or block.select_one("p")
        )
        results.append({"title": _text(anchor), "link": link, "snippet": _text(snippet_node) or None})
        if len(results) >= max_results:
            break
    return results


class BingWebSearchProvider(SearchProvider):
    name = "bing"
    search_url = "https://www.bing.com/search"
    concurrency = 3
    block_cooldown = 600.0

    async def _search(self, query: str, max_results: int) -> tuple[list[dict[str, Any]], int | None]:
        params = {"q": query, "setlang": "en", "count": str(min(max(max_results, 10), 30))}
        response = await self._get(self.search_url, params=params)
        results = parse_bing_html(response.text, max_results)
        if not results:
            lowered = response.text.lower()
            if any(marker in lowered for marker in _CAPTCHA_MARKERS) or "b_captcha" in lowered:
                raise ProviderBlocked("Bing captcha")
        return results, response.status_code


def decode_yahoo_url(href: str | None) -> str | None:
    """Раскрывает редирект Yahoo ``r.search.yahoo.com/.../RU=<url>/RK=...``."""
    if not href:
        return None
    if "r.search.yahoo.com" in href and "/RU=" in href:
        encoded = href.split("/RU=", 1)[1].split("/RK=", 1)[0].split("/RS=", 1)[0]
        target = unquote(encoded)
        return target if target.startswith("http") else None
    if "yahoo.com" in (urlparse(href).hostname or ""):
        return None  # внутренние ссылки Yahoo
    return href if href.startswith("http") else None


def parse_yahoo_html(html: str, max_results: int) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict[str, Any]] = []
    for block in soup.select("div.algo"):
        anchor = block.select_one("h3 a") or block.select_one("div.compTitle a")
        if anchor is None:
            continue
        link = decode_yahoo_url(anchor.get("href"))
        if not link:
            continue
        title_node = block.select_one("h3")
        # В заголовке Yahoo иногда есть «хлебные крошки» домена — берём aria-label при наличии
        title = anchor.get("aria-label") or _text(title_node) or _text(anchor)
        snippet = _text(block.select_one("div.compText")) or None
        results.append({"title": title, "link": link, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


class YahooSearchProvider(SearchProvider):
    name = "yahoo"
    search_url = "https://search.yahoo.com/search"
    concurrency = 3
    block_cooldown = 600.0

    def _is_block_response(self, response: httpx.Response) -> bool:
        # Yahoo перенаправляет подозрительные запросы на /_bv/ (bot verification)
        return "/_bv/" in response.url.path or any("/_bv/" in item.url.path for item in response.history)

    async def _search(self, query: str, max_results: int) -> tuple[list[dict[str, Any]], int | None]:
        response = await self._get(self.search_url, params={"p": query, "ei": "UTF-8"})
        results = parse_yahoo_html(response.text, max_results)
        if not results:
            lowered = response.text.lower()
            if "consent" in str(response.url) or any(marker in lowered for marker in _CAPTCHA_MARKERS):
                raise ProviderBlocked("Yahoo consent/captcha page")
        return results, response.status_code


def decode_duckduckgo_url(href: str | None) -> str | None:
    if not href:
        return None
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com"):
        if parsed.path.startswith("/y.js"):
            return None  # реклама
        target = parse_qs(parsed.query).get("uddg", [None])[0]
        return target if target and target.startswith("http") else None
    return href if href.startswith("http") else None


def parse_duckduckgo_lite_html(html: str, max_results: int) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict[str, Any]] = []
    for anchor in soup.select("a.result-link"):
        link = decode_duckduckgo_url(anchor.get("href"))
        if not link:
            continue
        snippet = None
        row = anchor.find_parent("tr")
        if row is not None:
            for sibling in row.find_next_siblings("tr", limit=2):
                cell = sibling.select_one("td.result-snippet")
                if cell is not None:
                    snippet = _text(cell)
                    break
        results.append({"title": _text(anchor), "link": link, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


class DuckDuckGoSearchProvider(SearchProvider):
    name = "duckduckgo"
    search_url = "https://lite.duckduckgo.com/lite/"
    concurrency = 1
    block_cooldown = 900.0

    async def _search(self, query: str, max_results: int) -> tuple[list[dict[str, Any]], int | None]:
        response = await self._get(self.search_url, params={"q": query, "kl": "wt-wt"})
        results = parse_duckduckgo_lite_html(response.text, max_results)
        if not results:
            lowered = response.text.lower()
            if "bots use duckduckgo" in lowered or "anomaly" in lowered or "challenge" in lowered:
                raise ProviderBlocked("DuckDuckGo bot challenge")
        return results, response.status_code


def _clean_google_link(url: str | None) -> str | None:
    if not url:
        return None
    if url.startswith("/url"):
        return parse_qs(urlparse(url).query).get("q", [None])[0]
    if url.startswith("/"):
        return None
    return url if url.startswith("http") else None


def parse_google_html(html: str, max_results: int) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for title_tag in soup.select("a h3"):
        anchor = title_tag.find_parent("a")
        link = _clean_google_link(anchor.get("href") if anchor else None)
        if not link or link in seen or "google." in (urlparse(link).hostname or ""):
            continue
        seen.add(link)
        container = anchor.find_parent("div", class_="g") or anchor.find_parent("div", attrs={"data-hveid": True})
        snippet_node = None
        if container is not None:
            snippet_node = container.select_one("div.VwiC3b, span.aCOpRe, div.IsZvec, div[data-sncf]")
        results.append({"title": _text(title_tag), "link": link, "snippet": _text(snippet_node) or None})
        if len(results) >= max_results:
            break
    return results


class GoogleWebSearchProvider(SearchProvider):
    """Скрейпинг google.com. С 2025 года Google требует JavaScript и обычно отдаёт
    заглушку — в этом случае провайдер отключается на час, не замедляя поиск."""

    name = "googlesearch"
    search_url = "https://www.google.com/search"
    concurrency = 2
    block_cooldown = 3600.0

    async def _search(self, query: str, max_results: int) -> tuple[list[dict[str, Any]], int | None]:
        params = {"q": query, "num": str(min(max_results + 5, 20)), "hl": "en"}
        response = await self._get(self.search_url, params=params)
        lowered = response.text.lower()
        if "/sorry/" in str(response.url) or "enablejs" in lowered or "unusual traffic" in lowered:
            raise ProviderBlocked("Google requires JavaScript / captcha")
        return parse_google_html(response.text, max_results), response.status_code


# --- Платные API -------------------------------------------------------------------------------


class SerpAPISearchProvider(SearchProvider):
    base_url = "https://serpapi.com/search"
    kind = "api"
    concurrency = 4
    block_cooldown = 1800.0

    def __init__(self, engine: str):
        super().__init__()
        self.engine = engine
        self.name = f"serpapi:{engine}"

    @property
    def configured(self) -> bool:
        return bool(settings.serpapi_key)

    def _request_meta(self, query: str, max_results: int) -> dict[str, Any]:
        return {"url": self.base_url, "engine": self.engine}

    async def _search(self, query: str, max_results: int) -> tuple[list[dict[str, Any]], int | None]:
        params = {"engine": self.engine, "q": query, "num": max_results, "api_key": settings.serpapi_key}
        response = await self._get(self.base_url, params=params)
        payload = response.json()
        error = payload.get("error")
        if error:
            if "hasn't returned any results" in error:
                return [], response.status_code
            raise ProviderBlocked(f"SerpAPI error: {error}")
        items = payload.get("organic_results") or payload.get("news_results") or []
        results = [
            {"title": item.get("title") or item.get("link"), "link": item.get("link"), "snippet": item.get("snippet")}
            for item in items
            if item.get("link")
        ]
        return results, response.status_code


class GoogleCustomSearchProvider(SearchProvider):
    base_url = "https://www.googleapis.com/customsearch/v1"
    name = "google-custom-search"
    kind = "api"
    concurrency = 2
    block_cooldown = 3600.0

    @property
    def configured(self) -> bool:
        return bool(settings.google_cse_api_key and settings.google_cse_cx)

    def _request_meta(self, query: str, max_results: int) -> dict[str, Any]:
        return {"url": self.base_url, "cx": settings.google_cse_cx}

    async def _search(self, query: str, max_results: int) -> tuple[list[dict[str, Any]], int | None]:
        params = {
            "key": settings.google_cse_api_key,
            "cx": settings.google_cse_cx,
            "q": query,
            "num": max(1, min(max_results, 10)),  # API принимает не больше 10
        }
        response = await self._get(self.base_url, params=params)
        payload = response.json()
        results = [
            {"title": item.get("title") or item.get("link"), "link": item.get("link"), "snippet": item.get("snippet")}
            for item in payload.get("items", [])
            if item.get("link")
        ]
        return results, response.status_code


# --- Фабрики ------------------------------------------------------------------------------------

_WEB_PROVIDER_FACTORIES = {
    "yahoo": YahooSearchProvider,
    "bing": BingWebSearchProvider,
    "duckduckgo": DuckDuckGoSearchProvider,
    "google": GoogleWebSearchProvider,
    "googlesearch": GoogleWebSearchProvider,
}


def get_web_providers() -> list[SearchProvider]:
    """Бесплатные провайдеры в порядке приоритета (настройка WEB_SEARCH_PROVIDERS)."""
    providers: list[SearchProvider] = []
    seen: set[type] = set()
    for raw_name in settings.web_search_providers.split(","):
        factory = _WEB_PROVIDER_FACTORIES.get(raw_name.strip().lower())
        if factory and factory not in seen:
            seen.add(factory)
            providers.append(factory())
    return providers


def get_serpapi_provider() -> SearchProvider | None:
    if not settings.serpapi_key:
        return None
    return SerpAPISearchProvider(settings.serpapi_search_engine)


def get_google_provider() -> SearchProvider:
    return GoogleCustomSearchProvider()


def get_default_providers() -> list[SearchProvider]:
    """Совместимость: бесплатные провайдеры + SerpAPI (если настроен)."""
    providers = get_web_providers()
    serpapi = get_serpapi_provider()
    if serpapi:
        providers.append(serpapi)
    return providers


__all__ = [
    "BingWebSearchProvider",
    "DuckDuckGoSearchProvider",
    "GoogleCustomSearchProvider",
    "GoogleWebSearchProvider",
    "ProviderBlocked",
    "SearchProvider",
    "SerpAPISearchProvider",
    "YahooSearchProvider",
    "decode_bing_url",
    "decode_yahoo_url",
    "decode_duckduckgo_url",
    "get_default_providers",
    "get_google_provider",
    "get_serpapi_provider",
    "get_web_providers",
    "parse_bing_html",
    "parse_duckduckgo_lite_html",
    "parse_google_html",
    "parse_yahoo_html",
]
