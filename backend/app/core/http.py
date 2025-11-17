from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings


def httpx_client_kwargs(**kwargs: Any) -> dict[str, Any]:
    """Return shared httpx.AsyncClient kwargs honoring the configured proxy."""
    settings = get_settings()
    client_kwargs = dict(kwargs)
    if "timeout" not in client_kwargs:
        client_kwargs["timeout"] = httpx.Timeout(30.0)
    if settings.proxy_url:
        client_kwargs.setdefault("proxies", settings.proxy_url)
    return client_kwargs
