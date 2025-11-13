from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.part import Part
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

from .deps import get_db

settings = get_settings()

router = APIRouter()


@router.get("/parts", response_model=list[PartRead])
async def list_parts(session: AsyncSession = Depends(get_db)) -> list[PartRead]:
    stmt = select(Part)
    result = await session.execute(stmt)
    return [PartRead.model_validate(part) for part in result.scalars().all()]


@router.post("/parts", response_model=PartRead)
async def create_part(part: PartCreate, session: AsyncSession = Depends(get_db)) -> PartRead:
    engine = PartSearchEngine(session)
    await engine.search_part(part, debug=True)
    await session.commit()
    stmt = select(Part).where(Part.part_number == part.part_number)
    db_part = (await session.execute(stmt)).scalar_one()
    return PartRead.model_validate(db_part)


@router.post("/search", response_model=SearchResponse)
async def search_parts(request: SearchRequest, session: AsyncSession = Depends(get_db)) -> SearchResponse:
    engine = PartSearchEngine(session)
    results = await engine.search_many(request.items, debug=request.debug)
    await session.commit()
    return SearchResponse(results=results, debug=request.debug)


@router.post("/upload", response_model=UploadResponse)
async def upload_excel(
    file: UploadFile = File(...),
    debug: bool = Form(False),
    session: AsyncSession = Depends(get_db),
) -> UploadResponse:
    imported, skipped, errors = await import_parts_from_excel(session, file, debug=debug)
    return UploadResponse(imported=imported, skipped=skipped, errors=errors)


@router.get("/export/excel", response_model=ExportResponse)
async def export_excel(session: AsyncSession = Depends(get_db)) -> ExportResponse:
    path = await export_parts_to_excel(session)
    return ExportResponse(url=f"/download/{path.name}")


@router.get("/export/pdf", response_model=ExportResponse)
async def export_pdf(session: AsyncSession = Depends(get_db)) -> ExportResponse:
    path = await export_parts_to_pdf(session)
    return ExportResponse(url=f"/download/{path.name}")


@router.get("/download/{filename}")
async def download_file(filename: str) -> FileResponse:
    path = settings.storage_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)
