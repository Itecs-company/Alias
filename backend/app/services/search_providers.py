from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx
from loguru import logger
from openai import AsyncOpenAI

from app.core.config import get_settings

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
        async with httpx.AsyncClient(timeout=30.0) as client:
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
            self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def search(self, query: str, *, max_results: int = 5) -> list[dict[str, Any]]:
        if not self.client:
            return []

        system_prompt = (
            "You are a sourcing assistant. Given an electronic component part number, "
            "return reputable URLs (datasheets, manufacturer pages) containing the manufacturer name."
        )
        completion = await self.client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ],
            max_output_tokens=500,
        )
        output = completion.output[0].content[0].text  # type: ignore[index]
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


def get_default_providers() -> list[SearchProvider]:
    return [
        SerpAPISearchProvider(settings.serpapi_search_engine),
        SerpAPISearchProvider(settings.serpapi_yahoo_engine),
    ]


def get_fallback_provider() -> SearchProvider:
    return OpenAISearchProvider()
