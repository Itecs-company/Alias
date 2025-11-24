from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SearchLogRead(BaseModel):
    id: int
    provider: str
    direction: str
    query: str
    status_code: Optional[int]
    payload: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
