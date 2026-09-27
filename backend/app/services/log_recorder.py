from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.search_log import SearchLog

# Полные ответы поисковиков могут весить сотни килобайт; в БД храним разумный объём.
MAX_PAYLOAD_CHARS = 20_000


class SearchLogRecorder:
    """Буферизует логи поиска и записывает их в сессию одной пачкой.

    Поиск нескольких артикулов идёт параллельно, а ``AsyncSession`` не допускает
    конкурентных операций, поэтому запись в БД выполняет владелец сессии через
    :meth:`flush` (под блокировкой), а не каждый провайдер самостоятельно.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self._pending: list[SearchLog] = []

    async def record(
        self,
        *,
        provider: str,
        direction: str,
        query: str,
        status_code: int | None = None,
        payload: str | None = None,
    ) -> None:
        self._pending.append(
            SearchLog(
                provider=provider,
                direction=direction,
                query=query[:2000],
                status_code=status_code,
                payload=payload,
            )
        )

    @property
    def pending(self) -> int:
        return len(self._pending)

    def flush(self) -> None:
        """Добавляет накопленные записи в сессию (коммит выполняет вызывающий код)."""
        if not self._pending:
            return
        self.session.add_all(self._pending)
        self._pending = []


def serialize_payload(data: Any) -> str:
    """Serialize payload to JSON, truncating very large responses."""
    if isinstance(data, str):
        text = data
    else:
        try:
            text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        except Exception:  # pragma: no cover - defensive
            text = str(data)
    if len(text) > MAX_PAYLOAD_CHARS:
        text = text[:MAX_PAYLOAD_CHARS] + f"\n… [обрезано, всего {len(text)} символов]"
    return text
