from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import BaseSettings, Field, field_validator


class Settings(BaseSettings):
    app_name: str = "AliasFinder"
    debug: bool = False
    database_url: str = Field(default="sqlite+aiosqlite:///./alias.db")
    serpapi_key: str | None = None
    serpapi_search_engine: str = Field(default="google")
    serpapi_yahoo_engine: str = Field(default="yahoo")
    openai_api_key: str | None = None
    allowed_origins: List[str] = Field(default_factory=lambda: ["*"])
    storage_dir: Path = Field(default=Path("storage"))

    class Config:
        env_file = ".env"
        case_sensitive = False

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, value: str | List[str]) -> List[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    return settings
