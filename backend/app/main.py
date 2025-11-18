from __future__ import annotations

import logging

from sqlalchemy import select

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import router
from app.core.config import get_settings
from app.core.security import get_password_hash
from app.models import base  # noqa: F401
from app.models.part import Base
from app.models.user import User

settings = get_settings()

app = FastAPI(title=settings.app_name)
app.include_router(router, prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup() -> None:
    logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)
    from app.core.database import async_session_factory, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        stmt = select(User).order_by(User.id).limit(1)
        user = (await session.execute(stmt)).scalar_one_or_none()
        if user is None:
            session.add(
                User(
                    username=settings.default_user_username,
                    password_hash=get_password_hash(settings.default_user_password),
                )
            )
            await session.commit()


app.mount("/storage", StaticFiles(directory=settings.storage_dir), name="storage")
