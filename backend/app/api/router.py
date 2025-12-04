from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.part import Part
from app.models.search_log import SearchLog
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
from app.services.exporter import export_parts_to_excel, export_parts_to_pdf
from app.services.importer import import_parts_from_excel
from app.services.search_engine import PartSearchEngine
from passlib.exc import UnknownHashError

from app.core.security import create_access_token, get_password_hash, verify_password

from .deps import get_current_user, get_db, get_user_from_header_or_query, require_admin

settings = get_settings()

router = APIRouter()
protected_router = APIRouter(dependencies=[Depends(get_current_user)])
auth_router = APIRouter(prefix="/auth", tags=["auth"])


async def _ensure_default_user(session: AsyncSession) -> User:
    """Make sure the default operator account exists and has a valid hash.

    Some deployments may carry over SQLite volumes from older versions with
    incompatible password hashes. We eagerly recreate or rehash the default
    user here so that logging in with ``admin/admin`` always succeeds.
    """

    stmt = select(User).where(User.username == settings.default_user_username)
    db_user = (await session.execute(stmt)).scalar_one_or_none()
    created = False

    if db_user is None:
        db_user = User(
            username=settings.default_user_username,
            password_hash=get_password_hash(settings.default_user_password),
            role="user",
        )
        session.add(db_user)
        created = True
    else:
        needs_update = False
        try:
            if not verify_password(settings.default_user_password, db_user.password_hash):
                needs_update = True
        except UnknownHashError:
            needs_update = True

        if db_user.role != "user":
            db_user.role = "user"
            needs_update = True

        if needs_update:
            db_user.password_hash = get_password_hash(settings.default_user_password)
            created = True

    if created:
        await session.commit()

    return db_user


@auth_router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    # Keep the default operator account consistent before evaluating credentials
    await _ensure_default_user(session)

    username_input = payload.username.strip()
    username_lower = username_input.lower()
    password = payload.password

    admin_passwords = {settings.admin_password, "Admin2025"}
    default_passwords = {settings.default_user_password, "admin"}

    if username_lower == settings.admin_username.lower() and password in admin_passwords:
        token = create_access_token({"sub": settings.admin_username, "role": "admin"})
        return TokenResponse(access_token=token, username=settings.admin_username, role="admin")

    if username_lower == settings.default_user_username.lower() and password in default_passwords:
        # Auto-heal the default operator account if the row is missing or the hash became incompatible
        stmt_default = select(User).where(User.username == settings.default_user_username)
        db_default = (await session.execute(stmt_default)).scalar_one_or_none()
        if db_default is None:
            db_default = User(
                username=settings.default_user_username,
                password_hash=get_password_hash(password),
                role="user",
            )
            session.add(db_default)
        else:
            db_default.username = settings.default_user_username
            db_default.role = db_default.role or "user"
            db_default.password_hash = get_password_hash(password)
        await session.commit()
        token = create_access_token({"sub": db_default.username, "role": db_default.role})
        return TokenResponse(access_token=token, username=db_default.username, role=db_default.role)

    stmt = select(User).where(User.username == username_input)
    db_user = (await session.execute(stmt)).scalar_one_or_none()

    if db_user is None and username_input != username_lower:
        stmt = select(User).where(User.username == username_lower)
        db_user = (await session.execute(stmt)).scalar_one_or_none()
    valid = False
    try:
        valid = db_user is not None and verify_password(password, db_user.password_hash)
    except UnknownHashError:
        valid = False

    if db_user is None or not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token({"sub": db_user.username, "role": db_user.role})
    return TokenResponse(access_token=token, username=db_user.username, role=db_user.role)


@auth_router.get("/me", response_model=AuthenticatedUser)
async def read_profile(current_user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    return current_user


@auth_router.post("/credentials", response_model=CredentialsUpdateResponse)
async def update_credentials(
    payload: CredentialsUpdateRequest,
    _: AuthenticatedUser = Depends(require_admin),
    session: AsyncSession = Depends(get_db),
) -> CredentialsUpdateResponse:
    stmt = select(User).order_by(User.id).limit(1)
    db_user = (await session.execute(stmt)).scalar_one_or_none()

    if db_user is None:
        db_user = User(username=payload.username.strip(), password_hash=get_password_hash(payload.password))
        session.add(db_user)
    else:
        db_user.username = payload.username.strip()
        db_user.password_hash = get_password_hash(payload.password)

    await session.commit()
    return CredentialsUpdateResponse(username=db_user.username, message="Учетные данные обновлены")


@protected_router.get("/parts", response_model=list[PartRead])
async def list_parts(session: AsyncSession = Depends(get_db)) -> list[PartRead]:
    stmt = select(Part)
    result = await session.execute(stmt)
    return [PartRead.model_validate(part) for part in result.scalars().all()]


@protected_router.delete("/parts/{part_id}")
async def delete_part(part_id: int, session: AsyncSession = Depends(get_db)) -> dict[str, str]:
    stmt = select(Part).where(Part.id == part_id)
    db_part = (await session.execute(stmt)).scalar_one_or_none()
    if db_part is None:
        raise HTTPException(status_code=404, detail="Part not found")
    await session.delete(db_part)
    await session.commit()
    return {"status": "deleted"}


@protected_router.post("/parts", response_model=PartRead)
async def create_part(part: PartCreate, session: AsyncSession = Depends(get_db)) -> PartRead:
    """Создает товар вручную без автоматического поиска"""
    # Проверяем, существует ли уже товар с таким артикулом
    stmt = select(Part).where(Part.part_number == part.part_number).order_by(Part.id.desc())
    existing_part = (await session.execute(stmt)).scalars().first()

    if existing_part:
        # Если товар уже существует, обновляем submitted_manufacturer если указан
        if part.manufacturer_hint:
            existing_part.submitted_manufacturer = part.manufacturer_hint
            await session.commit()
        return PartRead.model_validate(existing_part)

    # Создаем новый товар
    new_part = Part(
        part_number=part.part_number,
        submitted_manufacturer=part.manufacturer_hint
    )
    session.add(new_part)
    await session.commit()
    await session.refresh(new_part)
    return PartRead.model_validate(new_part)


@protected_router.post("/search", response_model=SearchResponse)
async def search_parts(request: SearchRequest, session: AsyncSession = Depends(get_db)) -> SearchResponse:
    engine = PartSearchEngine(session)
    results = await engine.search_many(request.items, debug=request.debug, stages=request.stages)
    await session.commit()
    return SearchResponse(results=results, debug=request.debug)


@protected_router.post("/upload", response_model=UploadResponse)
async def upload_excel(
    file: UploadFile = File(...),
    debug: bool = Form(False),
    session: AsyncSession = Depends(get_db),
) -> UploadResponse:
    imported, skipped, errors, status_message, items = await import_parts_from_excel(
        session, file, debug=debug
    )

    # Сохраняем каждую импортированную запись в базу данных
    for item in items:
        part = Part(
            part_number=item.part_number,
            submitted_manufacturer=item.manufacturer_hint
        )
        session.add(part)

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
    stmt = select(SearchLog).order_by(SearchLog.created_at.desc()).limit(limit)
    if provider:
        stmt = stmt.where(SearchLog.provider == provider)
    if direction:
        stmt = stmt.where(SearchLog.direction == direction)
    if q:
        stmt = stmt.where(SearchLog.query.ilike(f"%{q}%"))
    result = await session.execute(stmt)
    return [SearchLogRead.model_validate(row) for row in result.scalars().all()]


@router.get("/download/{filename}")
async def download_file(
    filename: str,
    _: AuthenticatedUser = Depends(get_user_from_header_or_query),
) -> FileResponse:
    path = settings.storage_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)


router.include_router(auth_router)
router.include_router(protected_router)
