from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from passlib.exc import UnknownHashError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import ci_equals
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.part import Part
from app.models.search_log import SearchLog
from app.models.settings import Settings
from app.models.user import User
from app.schemas.auth import (
    AuthenticatedUser,
    CredentialsUpdateRequest,
    CredentialsUpdateResponse,
    LoginRequest,
    TokenResponse,
)
from app.schemas.logs import SearchLogRead
from app.schemas.part import (
    ExportResponse,
    PartCreate,
    PartRead,
    SearchRequest,
    SearchResponse,
    UploadResponse,
)
from app.schemas.settings import SettingsRead, SettingsUpdate, TelegramTestRequest
from app.services.exporter import export_parts_to_excel, export_parts_to_pdf
from app.services.importer import import_parts_from_excel
from app.services.manufacturers import evaluate_match
from app.services.optimized_search_engine import OptimizedPartSearchEngine
from app.services.telegram_notifier import TelegramNotifier

from .deps import get_current_user, get_db, get_user_from_header_or_query, require_admin

settings = get_settings()

router = APIRouter()
protected_router = APIRouter(dependencies=[Depends(get_current_user)])
auth_router = APIRouter(prefix="/auth", tags=["auth"])


def _constant_time_equals(first: str, second: str) -> bool:
    return hmac.compare_digest(first.encode("utf-8"), second.encode("utf-8"))


async def _find_user(session: AsyncSession, username: str) -> User | None:
    stmt = select(User).where(User.username == username)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None:
        stmt = select(User).where(ci_equals(User.username, username)).order_by(User.id).limit(1)
        user = (await session.execute(stmt)).scalars().first()
    return user


@auth_router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    username = payload.username.strip()
    password = payload.password

    # Администратор задаётся только через переменные окружения
    if username.lower() == settings.admin_username.lower() and _constant_time_equals(password, settings.admin_password):
        token = create_access_token({"sub": settings.admin_username, "role": "admin"})
        return TokenResponse(access_token=token, username=settings.admin_username, role="admin")

    db_user = await _find_user(session, username)
    try:
        valid = db_user is not None and verify_password(password, db_user.password_hash)
    except (UnknownHashError, ValueError):
        valid = False

    if db_user is None or not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    role = db_user.role or "user"
    token = create_access_token({"sub": db_user.username, "role": role})
    return TokenResponse(access_token=token, username=db_user.username, role=role)


@auth_router.get("/me", response_model=AuthenticatedUser)
async def read_profile(current_user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    return current_user


@auth_router.post("/credentials", response_model=CredentialsUpdateResponse)
async def update_credentials(
    payload: CredentialsUpdateRequest,
    _: AuthenticatedUser = Depends(require_admin),
    session: AsyncSession = Depends(get_db),
) -> CredentialsUpdateResponse:
    new_username = payload.username.strip()
    if len(new_username) < 3:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Логин слишком короткий")

    stmt = select(User).where(User.role != "admin").order_by(User.id).limit(1)
    db_user = (await session.execute(stmt)).scalars().first()

    conflict = await _find_user(session, new_username)
    if conflict is not None and (db_user is None or conflict.id != db_user.id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Пользователь с таким логином уже существует")

    if db_user is None:
        db_user = User(username=new_username, password_hash=get_password_hash(payload.password), role="user")
        session.add(db_user)
    else:
        db_user.username = new_username
        db_user.password_hash = get_password_hash(payload.password)

    await session.commit()
    return CredentialsUpdateResponse(username=db_user.username, message="Учетные данные обновлены")


@protected_router.get("/parts", response_model=list[PartRead])
async def list_parts(session: AsyncSession = Depends(get_db)) -> list[PartRead]:
    stmt = select(Part).order_by(Part.id)
    result = await session.execute(stmt)
    return [PartRead.model_validate(part) for part in result.scalars().all()]


@protected_router.delete("/parts/{part_id}")
async def delete_part(part_id: int, session: AsyncSession = Depends(get_db)) -> dict[str, str]:
    db_part = await session.get(Part, part_id)
    if db_part is None:
        raise HTTPException(status_code=404, detail="Part not found")
    await session.delete(db_part)
    await session.commit()
    return {"status": "deleted"}


async def _upsert_part(session: AsyncSession, item: PartCreate) -> Part:
    """Одна строка на артикул: повторное добавление обновляет подсказку производителя."""
    stmt = (
        select(Part)
        .where(ci_equals(Part.part_number, item.part_number))
        .order_by(Part.manufacturer_name.is_(None), Part.id.desc())
        .limit(1)
    )
    existing = (await session.execute(stmt)).scalars().first()
    if existing is not None:
        if item.manufacturer_hint and item.manufacturer_hint != existing.submitted_manufacturer:
            # Подсказка изменилась — пересчитываем статус сверки с найденным производителем
            existing.submitted_manufacturer = item.manufacturer_hint
            existing.match_status, existing.match_confidence = evaluate_match(
                item.manufacturer_hint, existing.manufacturer_name
            )
        return existing
    part = Part(
        part_number=item.part_number,
        submitted_manufacturer=item.manufacturer_hint,
        match_status="pending" if item.manufacturer_hint else None,
    )
    session.add(part)
    return part


@protected_router.post("/parts", response_model=PartRead)
async def create_part(part: PartCreate, session: AsyncSession = Depends(get_db)) -> PartRead:
    """Создает товар вручную без автоматического поиска"""
    db_part = await _upsert_part(session, part)
    await session.commit()
    await session.refresh(db_part)
    return PartRead.model_validate(db_part)


@protected_router.post("/search", response_model=SearchResponse)
async def search_parts(
    request: SearchRequest,
    session: AsyncSession = Depends(get_db),
    use_optimized: bool = True,
) -> SearchResponse:
    """
    Поиск производителей по артикулам.

    * без ``stages`` — выполняются нужные этапы (Internet → googlesearch → OpenAI),
      ранее найденные результаты берутся из БД;
    * с ``stages`` — кеш игнорируется, выполняются только указанные этапы.

    Параметр ``use_optimized`` оставлен для совместимости: используется единый движок.
    """
    engine = OptimizedPartSearchEngine(session)
    results = await engine.search_many(request.items, debug=request.debug, stages=request.stages)
    engine.log_recorder.flush()
    await session.commit()
    return SearchResponse(results=results, debug=request.debug)


@protected_router.post("/upload", response_model=UploadResponse)
async def upload_excel(
    file: UploadFile = File(...),
    debug: bool = Form(False),
    session: AsyncSession = Depends(get_db),
) -> UploadResponse:
    try:
        imported, skipped, errors, status_message, items = await import_parts_from_excel(session, file, debug=debug)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    for item in items:
        await _upsert_part(session, item)
        await session.flush()
    await session.commit()

    return UploadResponse(
        imported=imported,
        skipped=skipped,
        errors=errors,
        status_message=status_message,
        items=items,
    )


@protected_router.get("/export/excel", response_model=ExportResponse)
async def export_excel(session: AsyncSession = Depends(get_db)) -> ExportResponse:
    path = await export_parts_to_excel(session)
    return ExportResponse(url=f"/api/download/{path.name}")


@protected_router.get("/export/pdf", response_model=ExportResponse)
async def export_pdf(session: AsyncSession = Depends(get_db)) -> ExportResponse:
    path = await export_parts_to_pdf(session)
    return ExportResponse(url=f"/api/download/{path.name}")


@protected_router.get("/logs", response_model=list[SearchLogRead])
async def list_logs(
    provider: str | None = None,
    direction: str | None = None,
    q: str | None = None,
    limit: int = 200,
    session: AsyncSession = Depends(get_db),
) -> list[SearchLogRead]:
    limit = max(1, min(limit, 1000))
    stmt = select(SearchLog)
    if provider:
        stmt = stmt.where(SearchLog.provider == provider)
    if direction:
        stmt = stmt.where(SearchLog.direction == direction)
    if q:
        stmt = stmt.where(SearchLog.query.ilike(f"%{q}%"))
    stmt = stmt.order_by(SearchLog.id.desc()).limit(limit)
    result = await session.execute(stmt)
    return [SearchLogRead.model_validate(row) for row in result.scalars().all()]


@router.get("/download/{filename}")
async def download_file(
    filename: str,
    _: AuthenticatedUser = Depends(get_user_from_header_or_query),
) -> FileResponse:
    storage = settings.storage_dir.resolve()
    path = (storage / filename).resolve()
    # Защита от выхода за пределы каталога экспорта (../)
    if path.parent != storage or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=path.name)


async def _get_or_create_settings(session: AsyncSession) -> Settings:
    stmt = select(Settings).order_by(Settings.id).limit(1)
    settings_obj = (await session.execute(stmt)).scalars().first()
    if settings_obj is None:
        settings_obj = Settings(
            telegram_enabled=False,
            openai_balance_threshold=5.0,
            google_balance_threshold=10.0,
            notify_on_errors=True,
            notify_on_low_balance=True,
        )
        session.add(settings_obj)
        await session.commit()
        await session.refresh(settings_obj)
    return settings_obj


@protected_router.get("/settings", response_model=SettingsRead)
async def get_settings_endpoint(
    session: AsyncSession = Depends(get_db),
    _: AuthenticatedUser = Depends(require_admin),
) -> SettingsRead:
    """Получить настройки системы (только для администраторов)"""
    settings_obj = await _get_or_create_settings(session)
    return SettingsRead.model_validate(settings_obj)


@protected_router.put("/settings", response_model=SettingsRead)
async def update_settings_endpoint(
    settings_update: SettingsUpdate,
    session: AsyncSession = Depends(get_db),
    _: AuthenticatedUser = Depends(require_admin),
) -> SettingsRead:
    """Обновить настройки системы (только для администраторов)"""
    settings_obj = await _get_or_create_settings(session)

    # Обновляем только переданные поля
    update_data = settings_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if isinstance(value, str):
            value = value.strip() or None
        setattr(settings_obj, field, value)

    await session.commit()
    await session.refresh(settings_obj)
    return SettingsRead.model_validate(settings_obj)


@protected_router.post("/settings/test-telegram")
async def test_telegram_endpoint(
    test_request: TelegramTestRequest | None = None,
    session: AsyncSession = Depends(get_db),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, str]:
    """Тестировать отправку сообщения в Telegram (только для администраторов)"""
    notifier = TelegramNotifier(session)
    success, message = await notifier.test_connection(test_request.message if test_request else None)
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    return {"status": "success", "message": message}


router.include_router(auth_router)
router.include_router(protected_router)
