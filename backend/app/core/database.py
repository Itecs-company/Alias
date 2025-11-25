from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from .config import get_settings


settings = get_settings()

engine = create_async_engine(settings.database_url, future=True, echo=settings.debug)
async_session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def get_session():
    session: AsyncSession = async_session_factory()
    try:
        yield session
    finally:
        await session.close()
