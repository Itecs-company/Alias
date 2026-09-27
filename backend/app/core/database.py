from contextlib import asynccontextmanager

from sqlalchemy import event, func, or_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings


settings = get_settings()

_is_sqlite = settings.database_url.startswith("sqlite")
engine = create_async_engine(
    settings.database_url,
    future=True,
    echo=settings.debug,
    connect_args={"timeout": 30} if _is_sqlite else {},
)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


if _is_sqlite:

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record) -> None:  # pragma: no cover - driver specific
        # WAL позволяет читать таблицу во время записи результатов поиска,
        # busy_timeout — ждать освобождения блокировки вместо "database is locked".
        cursor = dbapi_connection.cursor()
        try:
            if ":memory:" not in settings.database_url:
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
        finally:
            cursor.close()


def ci_equals(column, value: str):
    """Сравнение без учёта регистра.

    SQLite ``lower()`` работает только с ASCII, поэтому дополнительно проверяется
    точное совпадение — иначе кириллические значения никогда не находились бы.
    """
    return or_(column == value, func.lower(column) == value.lower())


@asynccontextmanager
async def get_session():
    session: AsyncSession = async_session_factory()
    try:
        yield session
    finally:
        await session.close()
