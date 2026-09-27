from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from passlib.exc import UnknownHashError
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError

from app.api.router import router
from app.core.config import get_settings
from app.core.http import close_http_clients
from app.core.security import get_password_hash, verify_password
from app.models import Base  # noqa: F401 - регистрирует все модели в metadata
from app.models.user import User

settings = get_settings()

app = FastAPI(title=settings.app_name)
app.include_router(router, prefix="/api")

# Браузеры не принимают allow_credentials вместе с Origin "*"
_allow_all_origins = "*" in settings.allowed_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _allow_all_origins else settings.allowed_origins,
    allow_credentials=not _allow_all_origins,
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
        "what_produces": "TEXT",
        "website": "VARCHAR(500)",
        "manufacturer_aliases": "TEXT",
        "country": "VARCHAR(255)",
        "search_stage": "VARCHAR(100)",
        "stage_history": "JSON",
    }.items():
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
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_parts_part_number ON parts (part_number)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_search_logs_created_at ON search_logs (created_at)"))


async def _ensure_default_user() -> None:
    """Создаёт учётную запись оператора при первом запуске.

    Пароль существующего оператора не сбрасывается: иначе смена учётных данных
    администратором «откатывалась» бы при каждом перезапуске.
    """
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        users_count = (await session.execute(select(func.count()).select_from(User))).scalar_one()
        if users_count == 0:
            session.add(
                User(
                    username=settings.default_user_username,
                    password_hash=get_password_hash(settings.default_user_password),
                    role="user",
                )
            )
            await session.commit()
            return

        # Хеши из старых версий (например, bcrypt) passlib не распознаёт — перехешируем
        stmt = select(User).where(User.username == settings.default_user_username)
        user = (await session.execute(stmt)).scalar_one_or_none()
        if user is None:
            return
        try:
            verify_password(settings.default_user_password, user.password_hash)
        except (UnknownHashError, ValueError):
            user.password_hash = get_password_hash(settings.default_user_password)
            await session.commit()


@app.on_event("startup")
async def on_startup() -> None:
    logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)
    from app.core.database import engine

    if settings.auth_secret_key == "change-me":
        logger.warning("AUTH_SECRET_KEY is not set: using the insecure default. Set it in backend/.env")
    if settings.admin_password == "Admin2025" or settings.default_user_password == "admin":
        logger.warning("Default credentials are in use. Change ADMIN_PASSWORD / DEFAULT_USER_PASSWORD in backend/.env")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_upgrade_schema)

    await _ensure_default_user()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await close_http_clients()


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}
