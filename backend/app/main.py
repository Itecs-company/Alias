from __future__ import annotations

import logging

from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import router
from app.core.config import get_settings
from passlib.exc import UnknownHashError

from app.core.security import get_password_hash, verify_password
from app.models import base  # noqa: F401
from app.models.part import Base
from app.models.search_log import SearchLog  # noqa: F401
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


def _upgrade_schema(connection) -> None:  # pragma: no cover - runtime bootstrap
    """Best-effort schema alignment for existing SQLite volumes.

    Compose deployments re-use the same SQLite volume across iterations. When new
    columns are added we need to gently upgrade the tables without requiring a
    manual reset. This routine adds any missing columns with NULL defaults and,
    for the users table, ensures a role column exists with a sane default.
    """

    if connection.dialect.name != "sqlite":
        return

    parts_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(parts)"))}
    for name, ddl in {
        "submitted_manufacturer": "VARCHAR(255)",
        "match_status": "VARCHAR(50)",
        "match_confidence": "FLOAT",
    }.items():
        if not name:
            continue
        if name in parts_columns:
            continue
        try:
            connection.execute(text(f"ALTER TABLE parts ADD COLUMN {name} {ddl}"))
        except OperationalError as exc:  # pragma: no cover - defensive boot fix
            logging.warning("Skipping column %s during schema upgrade: %s", name, exc)

    user_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(users)"))}
    if "role" not in user_columns:
        connection.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(50) NOT NULL DEFAULT 'user'"))
    connection.execute(text("UPDATE users SET role='user' WHERE role IS NULL"))


@app.on_event("startup")
async def on_startup() -> None:
    logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)
    from app.core.database import async_session_factory, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_upgrade_schema)

    async with async_session_factory() as session:
        stmt = select(User).where(User.username == settings.default_user_username)
        user = (await session.execute(stmt)).scalar_one_or_none()
        needs_update = False

        if user is None:
            user = User(
                username=settings.default_user_username,
                password_hash=get_password_hash(settings.default_user_password),
                role="user",
            )
            session.add(user)
            needs_update = True
        else:
            try:
                if not verify_password(settings.default_user_password, user.password_hash):
                    needs_update = True
            except UnknownHashError:
                needs_update = True

            if user.role != "user":
                user.role = "user"
                needs_update = True

        if needs_update:
            user.password_hash = get_password_hash(settings.default_user_password)
            await session.commit()


app.mount("/storage", StaticFiles(directory=settings.storage_dir), name="storage")
