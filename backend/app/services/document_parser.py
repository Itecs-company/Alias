from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass
from typing import Iterable

import httpx
from bs4 import BeautifulSoup
from loguru import logger
from pypdf import PdfReader

from app.core.http import get_http_client

# Лимиты загрузки: HTML-страницы обрезаются, PDF нужен целиком (xref в конце файла)
MAX_HTML_BYTES = 1_500_000
MAX_PDF_BYTES = 12 * 1024 * 1024
# Производитель почти всегда указан на первых страницах и в колонтитуле последней
PDF_HEAD_PAGES = 3
PDF_TAIL_PAGES = 1

_SKIP_CONTENT_TYPES = ("image/", "video/", "audio/", "application/zip", "application/octet-stream+zip", "font/")


@dataclass
class FetchedDocument:
    url: str
    data: bytes
    content_type: str | None

    @property
    def is_pdf(self) -> bool:
        return self.data.lstrip()[:5].startswith(b"%PDF") or bool(
            self.content_type and "pdf" in self.content_type.lower()
        )


async def fetch_document(url: str, *, timeout: float = 10.0) -> FetchedDocument | None:
    """Скачивает страницу/документ потоково, не превышая лимиты размера."""
    client = get_http_client()
    try:
        async with client.stream("GET", url, timeout=httpx.Timeout(timeout, connect=5.0)) as response:
            if response.status_code >= 400:
                logger.debug("Document {url} returned HTTP {code}", url=url, code=response.status_code)
                return None
            content_type = response.headers.get("content-type")
            if content_type and content_type.lower().startswith(_SKIP_CONTENT_TYPES):
                return None
            looks_pdf = bool(content_type and "pdf" in content_type.lower()) or url.lower().split("?")[0].endswith(".pdf")
            limit = MAX_PDF_BYTES if looks_pdf else MAX_HTML_BYTES
            declared = response.headers.get("content-length")
            if looks_pdf and declared and declared.isdigit() and int(declared) > limit:
                logger.debug("Skipping large document {url} ({size} bytes)", url=url, size=declared)
                return None
            chunks: list[bytes] = []
            received = 0
            async for chunk in response.aiter_bytes():
                chunks.append(chunk)
                received += len(chunk)
                if received >= limit:
                    if looks_pdf:
                        return None  # обрезанный PDF всё равно не разобрать
                    break
            return FetchedDocument(url=str(response.url), data=b"".join(chunks), content_type=content_type)
    except (httpx.HTTPError, asyncio.TimeoutError) as exc:
        logger.debug("Failed to download {url}: {exc!r}", url=url, exc=exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unexpected error downloading {url}: {exc!r}", url=url, exc=exc)
        return None


# Совместимость со старым API
async def fetch_bytes(url: str, *, client: httpx.AsyncClient | None = None) -> tuple[bytes, str | None] | None:
    document = await fetch_document(url)
    if document is None:
        return None
    return document.data, document.content_type


def extract_text_from_pdf(data: bytes, *, max_pages: int | None = None) -> str:
    reader = PdfReader(io.BytesIO(data))
    pages = reader.pages
    total = len(pages)
    if max_pages is None or total <= max_pages:
        indexes = list(range(total))
    else:
        head = list(range(min(PDF_HEAD_PAGES, total)))
        tail = list(range(max(len(head), total - PDF_TAIL_PAGES), total))
        indexes = head + tail
    texts = []
    for index in indexes:
        try:
            texts.append(pages[index].extract_text() or "")
        except Exception:  # noqa: BLE001 - битые страницы не должны ломать разбор
            continue
    return "\n".join(texts)


def extract_text_from_html(data: bytes) -> str:
    soup = BeautifulSoup(data, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "template", "iframe"]):
        tag.decompose()
    parts: list[str] = []
    if soup.title and soup.title.string:
        parts.append(soup.title.string.strip())
    for meta in soup.find_all("meta", attrs={"name": ["description", "author"]}):
        if meta.get("content"):
            parts.append(meta["content"].strip())
    for meta in soup.find_all("meta", attrs={"property": ["og:title", "og:description", "og:site_name", "product:brand"]}):
        if meta.get("content"):
            parts.append(meta["content"].strip())
    text = soup.get_text("\n")
    parts.extend(line.strip() for line in text.splitlines() if line.strip())
    return "\n".join(parts)


def document_to_text(document: FetchedDocument) -> str:
    """Синхронный разбор документа (вызывать через ``asyncio.to_thread``)."""
    if document.is_pdf:
        try:
            return extract_text_from_pdf(document.data, max_pages=PDF_HEAD_PAGES + PDF_TAIL_PAGES)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to parse PDF {url}: {exc!r}", url=document.url, exc=exc)
            if document.data.lstrip()[:5].startswith(b"%PDF"):
                return ""
    try:
        return extract_text_from_html(document.data)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to parse HTML {url}: {exc!r}", url=document.url, exc=exc)
        return ""


async def extract_text(url: str, *, client: httpx.AsyncClient | None = None) -> str | None:
    document = await fetch_document(url)
    if document is None:
        return None
    text = await asyncio.to_thread(document_to_text, document)
    return text or None


async def extract_from_urls(urls: Iterable[str], *, concurrency: int = 5) -> dict[str, str]:
    semaphore = asyncio.Semaphore(concurrency)

    async def wrapped(url: str) -> tuple[str, str | None]:
        async with semaphore:
            return url, await extract_text(url)

    contents = await asyncio.gather(*(wrapped(url) for url in dict.fromkeys(urls)))
    return {url: content for url, content in contents if content}
