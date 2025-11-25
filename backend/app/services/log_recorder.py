from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.search_log import SearchLog


class SearchLogRecorder:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def record(
        self,
        *,
        provider: str,
        direction: str,
        query: str,
        status_code: int | None = None,
        payload: str | None = None,
    ) -> None:
        log_entry = SearchLog(
            provider=provider,
            direction=direction,
            query=query,
            status_code=status_code,
            payload=payload,
        )
        self.session.add(log_entry)
        await self.session.flush()


def serialize_payload(data: Any) -> str:
    try:
        from json import dumps

        return dumps(data, ensure_ascii=False)[:4000]
    except Exception:  # pragma: no cover - defensive
        return str(data)[:4000]
