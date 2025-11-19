from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from loguru import logger
from openai import AsyncOpenAI
from bs4 import BeautifulSoup

from app.core.config import get_settings
from app.core.http import httpx_client_kwargs

settings = get_settings()


class SearchProvider(ABC):
    name: str

    @abstractmethod
    async def search(self, query: str, *, max_results: int = 5) -> list[dict[str, Any]]:
        """Return a list of results with at least `title`, `link`, `snippet`."""


class SerpAPISearchProvider(SearchProvider):
    base_url = "https://serpapi.com/search"

    def __init__(self, engine: str):
        self.name = f"serpapi:{engine}"
        self.engine = engine
        if not settings.serpapi_key:
            logger.warning("SerpAPI key is missing. {name} will not return results.", name=self.name)

    async def search(self, query: str, *, max_results: int = 5) -> list[dict[str, Any]]:
        if not settings.serpapi_key:
            return []

        params = {
            "engine": self.engine,
            "q": query,
            "num": max_results,
            "api_key": settings.serpapi_key,
        }
        async with httpx.AsyncClient(**httpx_client_kwargs()) as client:
            try:
                response = await client.get(self.base_url, params=params)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "SerpAPI returned %s for query '%s'", 
                    exc.response.status_code if exc.response else "?",
                    query,
                )
                return []
            except httpx.HTTPError as exc:
                logger.warning("SerpAPI request failed for '%s': %s", query, exc)
                return []
            payload = response.json()

        if "organic_results" in payload:
            return payload["organic_results"][:max_results]
        if "news_results" in payload:
            return payload["news_results"][:max_results]
        return []


class OpenAISearchProvider(SearchProvider):
    def __init__(self):
        self.name = "openai"
        if not settings.openai_api_key:
            logger.warning("OpenAI API key is missing. openai provider will not return results.")
            self.client: AsyncOpenAI | None = None
        else:
            http_client = httpx.AsyncClient(**httpx_client_kwargs())
            self.client = AsyncOpenAI(api_key=settings.openai_api_key, http_client=http_client)
        self.model = settings.openai_model_default
        self._balance_checked = False

    async def search(self, query: str, *, max_results: int = 5) -> list[dict[str, Any]]:
        if not self.client:
            return []

        await self._maybe_warn_low_balance()

        system_prompt = (
            "You are a sourcing assistant. Given an electronic component part number, "
            "return reputable URLs (datasheets, manufacturer pages) containing the manufacturer name. "
            "Respond strictly with a JSON array where each item has 'title', 'url', and optional 'summary' fields."
        )
        completion = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Return JSON: {query}"},
            ],
            temperature=0,
            max_tokens=500,
        )
        choice = completion.choices[0]
        output: str | list[dict[str, str]] | None = None
        if choice.message:
            output = choice.message.content
        if isinstance(output, list):
            output = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in output)
        elif output is None:
            output = ""
        if not output:
            logger.debug("OpenAI search returned empty content for query '%s'", query)
            return []
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            logger.debug("OpenAI response is not valid JSON: {output}", output=output)
            return []

        results = []
        for item in data if isinstance(data, list) else []:
            url = item.get("url") or item.get("link")
            if url:
                results.append({"title": item.get("title", url), "link": url, "snippet": item.get("summary")})
        return results[:max_results]

    async def _maybe_warn_low_balance(self) -> None:
        if self._balance_checked or settings.openai_balance_threshold_usd is None:
            return
        if not settings.openai_api_key:
            return
        self._balance_checked = True
        url = "https://api.openai.com/dashboard/billing/credit_grants"
        headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
        try:
            async with httpx.AsyncClient(**httpx_client_kwargs(timeout=httpx.Timeout(15.0))) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to check OpenAI balance: {exc}", exc=exc)
            return
        available = payload.get("total_available")
        threshold = settings.openai_balance_threshold_usd
        if isinstance(available, (int, float)) and threshold is not None and available <= threshold:
            logger.warning(
                "OpenAI remaining balance {balance:.2f} USD is below configured threshold {threshold:.2f} USD",
                balance=available,
                threshold=threshold,
            )


class GoogleCustomSearchProvider(SearchProvider):
    base_url = "https://www.googleapis.com/customsearch/v1"

    def __init__(self) -> None:
        self.name = "google-custom-search"
        self.api_key = settings.google_cse_api_key
        self.cx = settings.google_cse_cx
        if not (self.api_key and self.cx):
            logger.warning(
                "Google Custom Search credentials are missing. {name} will not return results.",
                name=self.name,
            )

    async def search(self, query: str, *, max_results: int = 5) -> list[dict[str, Any]]:
        if not (self.api_key and self.cx):
            return []

        params = {"key": self.api_key, "cx": self.cx, "q": query, "num": max_results}
        async with httpx.AsyncClient(**httpx_client_kwargs()) as client:
            response: httpx.Response | None = None
            for attempt in range(3):
                try:
                    response = await client.get(self.base_url, params=params)
                    response.raise_for_status()
                    break
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code if exc.response else "?"
                    if status_code in {429, 503, "429", "503"} and attempt < 2:
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    logger.warning(
                        "Google Custom Search error %s for query '%s': %s",
                        status_code,
                        query,
                        exc.response.text if exc.response else exc,
                    )
                    return []
                except httpx.HTTPError as exc:
                    if attempt < 2:
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    logger.warning("Google Custom Search request failed for '%s': %s", query, exc)
                    return []
            if response is None:
                return []
            payload = response.json()

        items = payload.get("items", [])
        results: list[dict[str, Any]] = []
        for item in items:
            link = item.get("link")
            if link:
                results.append(
                    {
                        "title": item.get("title", link),
                        "link": link,
                        "snippet": item.get("snippet"),
                    }
                )
        return results[:max_results]


class GoogleWebSearchProvider(SearchProvider):
    search_url = "https://www.google.com/search"

    def __init__(self) -> None:
        self.name = "googlesearch"
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/121.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }

    async def search(self, query: str, *, max_results: int = 5) -> list[dict[str, Any]]:
        params = {
            "q": query,
            "num": str(max_results * 2),  # fetch a few extras so we can filter redirects
            "hl": "en",
        }
        async with httpx.AsyncClient(**httpx_client_kwargs()) as client:
            response: httpx.Response | None = None
            for attempt in range(3):
                try:
                    response = await client.get(self.search_url, params=params, headers=self.headers)
                    response.raise_for_status()
                    break
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code if exc.response else "?"
                    if status_code in {429, 503, "429", "503"} and attempt < 2:
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    logger.warning(
                        "Google web search returned %s for query '%s'",
                        status_code,
                        query,
                    )
                    return []
                except httpx.HTTPError as exc:
                    if attempt < 2:
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    logger.warning("Google web search failed for '%s': %s", query, exc)
                    return []
            if response is None:
                return []

        soup = BeautifulSoup(response.text, "html.parser")
        results: list[dict[str, Any]] = []
        for block in soup.select("div.g"):
            anchor = block.select_one("a")
            title_tag = block.select_one("h3")
            if not anchor or not title_tag:
                continue
            href = self._clean_link(anchor.get("href"))
            if not href:
                continue
            snippet_tag = block.select_one("div.IsZvec")
            snippet = snippet_tag.get_text(strip=True) if snippet_tag else None
            results.append({"title": title_tag.get_text(strip=True), "link": href, "snippet": snippet})
            if len(results) >= max_results:
                break
        return results

    def _clean_link(self, url: str | None) -> str | None:
        if not url:
            return None
        if url.startswith("/url"):
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            link = qs.get("q", [None])[0]
            return link
        if url.startswith("/imgres"):
            return None
        return url


def get_default_providers() -> list[SearchProvider]:
    providers: list[SearchProvider] = [GoogleWebSearchProvider()]
    if settings.serpapi_key:
        providers.append(SerpAPISearchProvider(settings.serpapi_search_engine))
    return providers


def get_google_provider() -> SearchProvider:
    return GoogleCustomSearchProvider()


def get_fallback_provider() -> SearchProvider:
    return OpenAISearchProvider()
