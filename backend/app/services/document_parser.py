from __future__ import annotations

import asyncio
import io
from typing import Iterable

import httpx
from bs4 import BeautifulSoup
from loguru import logger
from pypdf import PdfReader
from pypdf.errors import PdfReadError, PdfStreamError

from app.core.http import httpx_client_kwargs


async def fetch_bytes(
    url: str, *, client: httpx.AsyncClient | None = None
) -> tuple[bytes, str | None] | None:
    timeout = httpx.Timeout(12.0, connect=8.0)
    owns_client = client is None
    base_kwargs = httpx_client_kwargs(timeout=timeout, follow_redirects=True)
    client = client or httpx.AsyncClient(**base_kwargs)

    async def _get(verify_override: bool | None = None) -> httpx.Response:
        kwargs = base_kwargs if client else base_kwargs
        if verify_override is not None:
            kwargs = {**kwargs, "verify": verify_override}
        inner_client = client or httpx.AsyncClient(**kwargs)
        try:
            response = await inner_client.get(url)
            response.raise_for_status()
            return response
        finally:
            if client is None:
                await inner_client.aclose()

    try:
        return await _attempt_fetch(_get)
    finally:
        if owns_client:
            await client.aclose()


async def _attempt_fetch(getter) -> tuple[bytes, str | None] | None:
    for attempt in range(2):
        try:
            response = await getter()
            return response.content, response.headers.get("content-type")
        except httpx.HTTPError as exc:
            message = str(exc)
            if any(keyword in message for keyword in ("CERTIFICATE_VERIFY_FAILED", "certificate verify failed")):
                logger.warning("Retrying without SSL verification for {url}", url=getattr(exc, "request", None).url if hasattr(exc, "request") else "unknown")
                try:
                    response = await getter(False)
                    return response.content, response.headers.get("content-type")
                except Exception as inner_exc:  # noqa: BLE001
                    logger.warning("Retry without SSL verification failed for {url}: {exc}", url=getattr(exc, "request", None).url if hasattr(exc, "request") else "unknown", exc=inner_exc)
                    return None
            if attempt == 0:
                await asyncio.sleep(1.0)
                continue
            logger.warning("Failed to download {url}: {exc}", url=getattr(exc, "request", None).url if hasattr(exc, "request") else "unknown", exc=exc)
            return None
        except Exception as exc:  # noqa: BLE001
            if attempt == 0:
                await asyncio.sleep(1.0)
                continue
            logger.warning("Failed to download {url}: {exc}", url=getattr(exc, "request", None).url if hasattr(exc, "request") else "unknown", exc=exc)
            return None
    return None


def extract_text_from_pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_text_from_html(data: bytes) -> str:
    soup = BeautifulSoup(data, "html.parser")
    for script in soup(["script", "style"]):
        script.extract()
    return "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())


async def extract_text(url: str, *, client: httpx.AsyncClient | None = None) -> str | None:
    fetched = await fetch_bytes(url, client=client)
    if not fetched:
        return None
    data, content_type = fetched

    looks_like_pdf = data.lstrip().startswith(b"%PDF")
    hinted_pdf = bool(content_type and "pdf" in content_type.lower())
    if looks_like_pdf or hinted_pdf:
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, extract_text_from_pdf, data)
        except (PdfReadError, PdfStreamError, ValueError) as exc:
            logger.warning("Failed to parse PDF {url}: {exc}", url=url, exc=exc)
            # Fallback to treating the response as HTML so we can still inspect
            # landing pages that masquerade as PDFs but return HTML payloads.
            return extract_text_from_html(data)

    return extract_text_from_html(data)


async def extract_from_urls(urls: Iterable[str]) -> dict[str, str]:
    timeout = httpx.Timeout(12.0, connect=8.0)
    semaphore = asyncio.Semaphore(5)
    async with httpx.AsyncClient(
        **httpx_client_kwargs(timeout=timeout, follow_redirects=True)
    ) as client:
        async def wrapped(url: str) -> tuple[str, str | None]:
            async with semaphore:
                content = await extract_text(url, client=client)
                return url, content

        tasks = [wrapped(url) for url in urls]
        contents = await asyncio.gather(*tasks)
    return {url: content for url, content in contents if content}
