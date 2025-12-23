from __future__ import annotations

import asyncio
import json
import random
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from loguru import logger
from openai import AsyncOpenAI
from bs4 import BeautifulSoup

from app.core.config import get_settings
from app.core.http import httpx_client_kwargs
from app.services.log_recorder import SearchLogRecorder, serialize_payload

settings = get_settings()


class SearchProvider(ABC):
    name: str

    def __init__(self) -> None:
        self.log_recorder: SearchLogRecorder | None = None

    def set_recorder(self, recorder: SearchLogRecorder | None) -> None:
        self.log_recorder = recorder

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
        except Exception:
            logger.debug("Failed to record search log for %s", self.name)

    @abstractmethod
    async def search(self, query: str, *, max_results: int = 5) -> list[dict[str, Any]]:
        """Return a list of results with at least `title`, `link`, `snippet`."""


class SerpAPISearchProvider(SearchProvider):
    base_url = "https://serpapi.com/search"

    def __init__(self, engine: str):
        super().__init__()
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
        # Full request logging
        request_log = {
            "method": "GET",
            "url": self.base_url,
            "params": {k: v for k, v in params.items() if k != "api_key"},
            "headers": {"User-Agent": "httpx"},
            "engine": self.engine,
            "max_results": max_results,
        }
        await self._log("request", query, payload=request_log)

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
                        await asyncio.sleep(1.0 + random.random() * (attempt + 1))
                        continue
                    logger.warning(
                        "SerpAPI returned %s for query '%s'",
                        status_code,
                        query,
                    )
                    code = int(status_code) if isinstance(status_code, int) or str(status_code).isdigit() else None
                    await self._log("response", query, status_code=code, payload="error")
                    return []
                except httpx.HTTPError as exc:
                    if attempt < 2:
                        await asyncio.sleep(1.0 + random.random() * (attempt + 1))
                        continue
                    logger.warning("SerpAPI request failed for '%s': %s", query, exc)
                    await self._log("response", query, status_code=None, payload=str(exc))
                    return []
            if response is None:
                return []
            payload = response.json()

        organic_results = payload.get("organic_results", [])
        news_results = payload.get("news_results", [])
        results_used = organic_results if organic_results else news_results

        # Full response logging
        response_log = {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "engine": self.engine,
            "full_response": payload,  # Complete API response
            "organic_results_count": len(organic_results),
            "news_results_count": len(news_results),
        }
        await self._log("response", query, status_code=response.status_code, payload=response_log)

        if "organic_results" in payload:
            return payload["organic_results"][:max_results]
        if "news_results" in payload:
            return payload["news_results"][:max_results]
        return []


class OpenAISearchProvider(SearchProvider):
    def __init__(self):
        super().__init__()
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
            "Sourcing assistant. Return JSON array: [{'title':'...', 'url':'...', 'summary':'...'}]. "
            "Find datasheet/manufacturer URLs for electronic components."
        )
        user_message = f"URLs for: {query}"

        # Full request logging for OpenAI
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        request_log = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 300,
            "max_results": max_results,
        }
        await self._log("request", query, payload=request_log)

        completion = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0,
            max_tokens=300,
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

        # Full response logging for OpenAI
        response_log = {
            "status_code": 200,
            "model": self.model,
            "completion": {
                "id": completion.id if hasattr(completion, "id") else None,
                "model": completion.model if hasattr(completion, "model") else None,
                "usage": completion.usage.model_dump() if hasattr(completion, "usage") and completion.usage else None,
                "finish_reason": choice.finish_reason if hasattr(choice, "finish_reason") else None,
            },
            "raw_content": output,  # Full text response from OpenAI
            "parsed_data": data,  # Parsed JSON data
            "results": results,  # All results (not truncated)
            "results_count": len(results),
        }
        await self._log("response", query, status_code=200, payload=response_log)

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
    _rate_limit = asyncio.Semaphore(1)

    def __init__(self) -> None:
        super().__init__()
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
        # Full request logging
        request_log = {
            "method": "GET",
            "url": self.base_url,
            "params": {k: v for k, v in params.items() if k != "key"},
            "cx": self.cx,
            "max_results": max_results,
        }
        await self._log("request", query, payload=request_log)
        async with httpx.AsyncClient(**httpx_client_kwargs()) as client:
            async with self._rate_limit:
                response: httpx.Response | None = None
                for attempt in range(3):
                    try:
                        response = await client.get(self.base_url, params=params)
                        response.raise_for_status()
                        break
                    except httpx.HTTPStatusError as exc:
                        status_code = exc.response.status_code if exc.response else "?"
                        # Treat 429/503 as a signal to pause briefly, but avoid hammering the API.
                        if status_code in {429, 503, "429", "503"} and attempt < 2:
                            await asyncio.sleep(2.5 * (attempt + 1) + random.random())
                            continue
                        logger.warning(
                            "Google Custom Search error %s for query '%s': %s",
                            status_code,
                            query,
                            exc.response.text if exc.response else exc,
                        )
                        await self._log(
                            "response",
                            query,
                            status_code=int(status_code) if isinstance(status_code, int) or str(status_code).isdigit() else None,
                            payload=exc.response.text if exc.response else None,
                        )
                        return []
                    except httpx.HTTPError as exc:
                        if attempt < 2:
                            await asyncio.sleep(2.0 * (attempt + 1) + random.random())
                            continue
                        logger.warning("Google Custom Search request failed for '%s': %s", query, exc)
                        await self._log("response", query, status_code=None, payload=str(exc))
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

        # Full response logging
        response_log = {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "full_response": payload,  # Complete API response
            "results": results,  # All parsed results
            "results_count": len(results),
            "total_items": len(items),
        }
        await self._log("response", query, status_code=response.status_code, payload=response_log)

        return results[:max_results]


class GoogleWebSearchProvider(SearchProvider):
    search_url = "https://www.google.com/search"
    _rate_limit = asyncio.Semaphore(2)

    def __init__(self) -> None:
        super().__init__()
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
        # Full request logging
        request_log = {
            "method": "GET",
            "url": self.search_url,
            "params": params,
            "headers": self.headers,
            "max_results": max_results,
        }
        await self._log("request", query, payload=request_log)
        async with httpx.AsyncClient(**httpx_client_kwargs()) as client:
            async with self._rate_limit:
                response: httpx.Response | None = None
                for attempt in range(4):
                    try:
                        response = await client.get(self.search_url, params=params, headers=self.headers)
                        response.raise_for_status()
                        break
                    except httpx.HTTPStatusError as exc:
                        status_code = exc.response.status_code if exc.response else "?"
                        if status_code in {429, 503, "429", "503"} and attempt < 3:
                            await asyncio.sleep(1.4 * (attempt + 1) + random.random())
                            continue
                        logger.warning(
                            "Google web search returned %s for query '%s'",
                            status_code,
                            query,
                        )
                        await self._log(
                            "response",
                            query,
                            status_code=int(status_code) if isinstance(status_code, int) or str(status_code).isdigit() else None,
                            payload="error",
                        )
                        return []
                    except httpx.HTTPError as exc:
                        if attempt < 3:
                            await asyncio.sleep(1.4 * (attempt + 1) + random.random())
                            continue
                        logger.warning("Google web search failed for '%s': %s", query, exc)
                        await self._log("response", query, status_code=None, payload=str(exc))
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

        # Full response logging
        response_log = {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "html_length": len(response.text),
            "parsed_blocks": len(soup.select("div.g")),
            "results": results,  # All parsed results
            "results_count": len(results),
        }
        await self._log("response", query, status_code=response.status_code, payload=response_log)

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
