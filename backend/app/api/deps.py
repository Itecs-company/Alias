from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session


async def get_db() -> AsyncSession:
    async with get_session() as session:
        yield session
