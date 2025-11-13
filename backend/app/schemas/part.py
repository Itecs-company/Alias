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
    confidence: Optional[float]
    source_url: Optional[str]
    debug_log: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class SearchRequest(BaseModel):
    items: List[PartBase]
    debug: bool = False


class SearchResult(BaseModel):
    part_number: str
    manufacturer_name: Optional[str]
    alias_used: Optional[str]
    confidence: Optional[float]
    source_url: Optional[str]
    debug_log: Optional[str]


class SearchResponse(BaseModel):
    results: List[SearchResult]
    debug: bool = False


class UploadResponse(BaseModel):
    imported: int
    skipped: int
    errors: List[str] = Field(default_factory=list)


class ExportResponse(BaseModel):
    url: str
