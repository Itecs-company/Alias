from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


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
    part_number: str = Field(..., min_length=1, max_length=255, description="Article number to search")
    manufacturer_hint: Optional[str] = Field(
        default=None, max_length=255, description="Possible manufacturer name or alias"
    )

    @field_validator("part_number", mode="before")
    @classmethod
    def _clean_part_number(cls, value: object) -> object:
        if isinstance(value, (int, float)):
            value = str(value)
        if isinstance(value, str):
            return " ".join(value.split())
        return value

    @field_validator("manufacturer_hint", mode="before")
    @classmethod
    def _clean_hint(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = " ".join(value.split())
            return cleaned or None
        return value


class PartCreate(PartBase):
    pass


class StageStatus(BaseModel):
    name: str = Field(..., description="Имя этапа (Internet, googlesearch, OpenAI)")
    status: str = Field(..., description="Статус этапа (success, low-confidence, no-results, skipped)")
    provider: Optional[str] = Field(default=None, description="Задействованные провайдеры поиска")
    confidence: Optional[float] = Field(default=None, description="Достоверность результата на этапе")
    urls_considered: int = Field(default=0, description="Количество обработанных ссылок")
    message: Optional[str] = Field(default=None, description="Дополнительные комментарии")


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
    search_stage: Optional[str] = None
    stage_history: Optional[List[StageStatus]] = None
    # Новые поля
    what_produces: Optional[str] = None
    website: Optional[str] = None
    manufacturer_aliases: Optional[str] = None
    country: Optional[str] = None
    created_at: datetime

    @field_validator("stage_history", mode="before")
    @classmethod
    def _stage_history_list(cls, value: object) -> object:
        # В старых записях поле может быть пустым или иметь другой формат
        if not isinstance(value, list):
            return None
        return [item for item in value if isinstance(item, dict) and item.get("name") and item.get("status")]

    class Config:
        from_attributes = True


class SearchRequest(BaseModel):
    items: List[PartBase] = Field(..., max_length=1000)
    debug: bool = False
    stages: Optional[List[str]] = Field(
        default=None,
        description=(
            "Список этапов поиска (Internet, googlesearch, OpenAI). Если не указан — выполняются все "
            "необходимые этапы с использованием кеша; если указан — кеш игнорируется и выполняются только они."
        ),
    )


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
    # Новые поля
    what_produces: Optional[str] = None
    website: Optional[str] = None
    manufacturer_aliases: Optional[str] = None
    country: Optional[str] = None


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
