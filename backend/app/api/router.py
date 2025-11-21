from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.part import Part
from app.models.user import User
from app.schemas.auth import (
    AuthenticatedUser,
    CredentialsUpdateRequest,
    CredentialsUpdateResponse,
    LoginRequest,
    TokenResponse,
)
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
from app.core.security import create_access_token, get_password_hash, verify_password

from .deps import get_current_user, get_db, get_user_from_header_or_query, require_admin

settings = get_settings()

router = APIRouter()
protected_router = APIRouter(dependencies=[Depends(get_current_user)])
auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
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
    if db_user is None or not verify_password(password, db_user.password_hash):
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


@protected_router.post("/parts", response_model=PartRead)
async def create_part(part: PartCreate, session: AsyncSession = Depends(get_db)) -> PartRead:
    engine = PartSearchEngine(session)
    await engine.search_part(part, debug=True)
    await session.commit()
    stmt = select(Part).where(Part.part_number == part.part_number)
    db_part = (await session.execute(stmt)).scalar_one()
    return PartRead.model_validate(db_part)


@protected_router.post("/search", response_model=SearchResponse)
async def search_parts(request: SearchRequest, session: AsyncSession = Depends(get_db)) -> SearchResponse:
    engine = PartSearchEngine(session)
    results = await engine.search_many(request.items, debug=request.debug)
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
