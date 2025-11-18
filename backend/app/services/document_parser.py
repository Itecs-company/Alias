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


async def fetch_bytes(url: str) -> tuple[bytes, str | None] | None:
    timeout = httpx.Timeout(20.0, connect=10.0)
    async with httpx.AsyncClient(
        **httpx_client_kwargs(timeout=timeout, follow_redirects=True)
    ) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to download {url}: {exc}", url=url, exc=exc)
            return None
    return response.content, response.headers.get("content-type")


def extract_text_from_pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_text_from_html(data: bytes) -> str:
    soup = BeautifulSoup(data, "html.parser")
    for script in soup(["script", "style"]):
        script.extract()
    return "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())


async def extract_text(url: str) -> str | None:
    fetched = await fetch_bytes(url)
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
    tasks = [extract_text(url) for url in urls]
    contents = await asyncio.gather(*tasks)
    return {url: content for url, content in zip(urls, contents, strict=False) if content}
