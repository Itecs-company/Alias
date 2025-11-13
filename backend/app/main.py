from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import router
from app.core.config import get_settings
from app.models import base  # noqa: F401
from app.models.part import Base

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
    from app.core.database import engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


app.mount("/storage", StaticFiles(directory=settings.storage_dir), name="storage")
