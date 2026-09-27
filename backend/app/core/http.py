from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import httpx

from app.core.config import get_settings

if TYPE_CHECKING:  # pragma: no cover
    from openai import AsyncOpenAI

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
}


def httpx_client_kwargs(**kwargs: Any) -> dict[str, Any]:
    """Return shared httpx.AsyncClient kwargs honoring the configured proxy."""
    settings = get_settings()
    client_kwargs = dict(kwargs)
    if "timeout" not in client_kwargs:
        client_kwargs["timeout"] = httpx.Timeout(30.0)
    if settings.proxy_url:
        client_kwargs.setdefault("proxies", settings.proxy_url)
    if settings.allow_insecure_ssl:
        client_kwargs.setdefault("verify", False)
    return client_kwargs


# Клиенты переиспользуются между запросами (пул соединений, keep-alive, TLS),
# но привязаны к event loop, в котором были созданы.
_web_client: tuple[asyncio.AbstractEventLoop, httpx.AsyncClient] | None = None
_openai_client: tuple[asyncio.AbstractEventLoop, "AsyncOpenAI"] | None = None


def get_http_client() -> httpx.AsyncClient:
    """Общий HTTP-клиент для поисковых запросов и загрузки страниц."""
    global _web_client
    loop = asyncio.get_running_loop()
    if _web_client and _web_client[0] is loop and not _web_client[1].is_closed:
        return _web_client[1]
    client = httpx.AsyncClient(
        **httpx_client_kwargs(
            timeout=httpx.Timeout(12.0, connect=6.0),
            follow_redirects=True,
            headers=BROWSER_HEADERS,
            limits=httpx.Limits(max_connections=40, max_keepalive_connections=20, keepalive_expiry=30.0),
        )
    )
    _web_client = (loop, client)
    return client


def get_openai_client() -> "AsyncOpenAI | None":
    """Общий клиент OpenAI (None, если ключ не настроен)."""
    global _openai_client
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    loop = asyncio.get_running_loop()
    if _openai_client and _openai_client[0] is loop:
        return _openai_client[1]
    from openai import AsyncOpenAI

    http_client = httpx.AsyncClient(**httpx_client_kwargs(timeout=httpx.Timeout(45.0, connect=10.0)))
    client = AsyncOpenAI(api_key=settings.openai_api_key, http_client=http_client, max_retries=1)
    _openai_client = (loop, client)
    return client


async def close_http_clients() -> None:
    """Закрывает общие клиенты (вызывается при остановке приложения)."""
    global _web_client, _openai_client
    loop = asyncio.get_running_loop()
    if _web_client and _web_client[0] is loop:
        await _web_client[1].aclose()
    if _openai_client and _openai_client[0] is loop:
        await _openai_client[1].close()
    _web_client = None
    _openai_client = None
