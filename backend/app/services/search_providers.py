from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx
from loguru import logger
from openai import AsyncOpenAI

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
            response = await client.get(self.base_url, params=params)
            response.raise_for_status()
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
            try:
                response = await client.get(self.base_url, params=params)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "Google Custom Search error %s for query '%s': %s",
                    exc.response.status_code if exc.response else "?",
                    query,
                    exc.response.text if exc.response else exc,
                )
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


def get_default_providers() -> list[SearchProvider]:
    return [
        SerpAPISearchProvider(settings.serpapi_search_engine),
        SerpAPISearchProvider(settings.serpapi_yahoo_engine),
    ]


def get_google_provider() -> SearchProvider:
    return GoogleCustomSearchProvider()


def get_fallback_provider() -> SearchProvider:
    return OpenAISearchProvider()
