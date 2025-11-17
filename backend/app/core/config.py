import json
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "AliasFinder"
    debug: bool = False
    database_url: str = Field(default="sqlite+aiosqlite:///./alias.db")
    serpapi_key: str | None = None
    serpapi_search_engine: str = Field(default="google")
    google_cse_api_key: str | None = None
    google_cse_cx: str | None = None
    openai_api_key: str | None = None
    openai_model_default: str = Field(default="gpt-4.1")
    openai_balance_threshold_usd: float | None = None
    proxy_host: str | None = None
    proxy_port: int | None = None
    proxy_username: str | None = None
    proxy_password: str | None = None
    allowed_origins: List[str] = Field(default_factory=lambda: ["*"])
    storage_dir: Path = Field(default=Path("storage"))

    class Config:
        env_file = ".env"
        case_sensitive = False

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, value: str | List[str]) -> List[str]:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        return [str(origin).strip() for origin in parsed if str(origin).strip()]
                except json.JSONDecodeError:
                    pass
            return [origin.strip().strip("'\"") for origin in value.split(",") if origin.strip()]
        return value

    @property
    def proxy_url(self) -> str | None:
        if not (self.proxy_host and self.proxy_port):
            return None
        credentials = ""
        if self.proxy_username and self.proxy_password:
            credentials = f"{self.proxy_username}:{self.proxy_password}@"
        return f"socks5://{credentials}{self.proxy_host}:{self.proxy_port}"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    return settings
