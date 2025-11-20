from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ManufacturerAliasCreate(BaseModel):
    name: str = Field(..., description="Manufacturer alias")


class ManufacturerBase(BaseModel):
    name: str
    aliases: List[str] = Field(default_factory=list)


class ManufacturerCreate(ManufacturerBase):
    pass


class ManufacturerRead(ManufacturerBase):
    id: int

    class Config:
        from_attributes = True


class PartBase(BaseModel):
    part_number: str = Field(..., description="Article number to search")
    manufacturer_hint: Optional[str] = Field(
        default=None, description="Possible manufacturer name or alias"
    )


class PartCreate(PartBase):
    pass


class PartRead(BaseModel):
    id: int
    part_number: str
    manufacturer_name: Optional[str]
    alias_used: Optional[str]
    submitted_manufacturer: Optional[str]
    match_status: Optional[str]
    match_confidence: Optional[float]
    confidence: Optional[float]
    source_url: Optional[str]
    debug_log: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class SearchRequest(BaseModel):
    items: List[PartBase]
    debug: bool = False


class StageStatus(BaseModel):
    name: str = Field(..., description="Имя этапа (Internet, googlesearch, OpenAI)")
    status: str = Field(..., description="Статус этапа (success, low-confidence, no-results, skipped)")
    provider: Optional[str] = Field(default=None, description="Задействованные провайдеры поиска")
    confidence: Optional[float] = Field(default=None, description="Достоверность результата на этапе")
    urls_considered: int = Field(default=0, description="Количество обработанных ссылок")
    message: Optional[str] = Field(default=None, description="Дополнительные комментарии")


class SearchResult(BaseModel):
    part_number: str
    manufacturer_name: Optional[str]
    alias_used: Optional[str]
    submitted_manufacturer: Optional[str]
    match_status: Optional[str]
    match_confidence: Optional[float]
    confidence: Optional[float]
    source_url: Optional[str]
    debug_log: Optional[str]
    search_stage: Optional[str] = Field(
        default=None,
        description="Какой сервис дал финальный ответ (Internet, googlesearch, OpenAI)",
    )
    stage_history: List[StageStatus] = Field(default_factory=list, description="Ход выполнения поиска")


class SearchResponse(BaseModel):
    results: List[SearchResult]
    debug: bool = False


class UploadResponse(BaseModel):
    imported: int
    skipped: int
    errors: List[str] = Field(default_factory=list)
    status_message: Optional[str] = Field(
        default=None,
        description="Описание статуса обработки файла",
    )
    items: List[PartCreate] = Field(
        default_factory=list,
        description="Список элементов, полученных из загруженного файла",
    )


class ExportResponse(BaseModel):
    url: str
