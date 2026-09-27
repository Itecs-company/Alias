"""Общие фикстуры: изолированная БД/хранилище и отключённые внешние сервисы."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Настройки читаются при импорте модулей приложения, поэтому окружение
# задаётся до первого импорта ``app``.
_TMP = Path(tempfile.mkdtemp(prefix="aliasfinder-tests-"))
os.environ.update(
    {
        "DATABASE_URL": f"sqlite+aiosqlite:///{_TMP / 'test.db'}",
        "STORAGE_DIR": str(_TMP / "storage"),
        "OPENAI_API_KEY": "",
        "SERPAPI_KEY": "",
        "GOOGLE_CSE_API_KEY": "",
        "GOOGLE_CSE_CX": "",
        "PROXY_HOST": "",
        "PROXY_PORT": "",
        "AUTH_SECRET_KEY": "test-secret",
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "S3cure-admin",
        "DEFAULT_USER_USERNAME": "operator",
        "DEFAULT_USER_PASSWORD": "operator-pass",
        "WEB_SEARCH_PROVIDERS": "bing",
    }
)

from typing import Any  # noqa: E402

import pytest  # noqa: E402

from app.services.search_providers import SearchProvider  # noqa: E402


class FakeProvider(SearchProvider):
    """Провайдер с заранее заданной выдачей: {подстрока запроса: [результаты]}."""

    def __init__(self, name: str, responses: dict[str, list[dict[str, Any]]] | None = None, *, kind: str = "web"):
        super().__init__()
        self.name = name
        self.kind = kind
        self.responses = responses or {}
        self.default: list[dict[str, Any]] = []
        self.calls: list[str] = []

    async def _search(self, query: str, max_results: int):
        self.calls.append(query)
        lowered = query.lower()
        for key, results in self.responses.items():
            if key.lower() == lowered:
                return list(results), 200
        return list(self.default), 200


@pytest.fixture(autouse=True)
def _reset_provider_state():
    SearchProvider.reset_state()
    yield
    SearchProvider.reset_state()


@pytest.fixture
async def db_session():
    from app.core.database import async_session_factory, engine
    from app.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with async_session_factory() as session:
        yield session
    await engine.dispose()


def hit(title: str, link: str, snippet: str = "") -> dict[str, Any]:
    return {"title": title, "link": link, "snippet": snippet}
