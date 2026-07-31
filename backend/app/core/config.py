from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """应用设置。

    环境变量保持无前缀，便于 Docker Compose 直接注入约定变量。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "AI 文档出题平台"
    environment: str = "development"
    app_timezone: str = "Asia/Shanghai"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./data/app.db"
    celery_broker_url: str = ""
    celery_result_backend: str = ""
    storage_dir: Path = Path("./data/storage")
    app_secret: str = "development-only-change-me"
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:5173"]
    )
    max_upload_mb: int = 200
    max_document_pages: int = 2000
    sse_poll_interval_seconds: float = 0.5
    model_request_timeout_seconds: float = Field(default=300, ge=10, le=1800)
    model_request_max_retries: int = Field(default=2, ge=0, le=5)
    visual_enrichment_max_new_assets_per_job: int = Field(default=8, ge=0, le=100)
    strict_local_mode: bool = False
    log_level: str = "INFO"

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("api_v1_prefix")
    @classmethod
    def normalize_prefix(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith("/"):
            value = f"/{value}"
        return value.rstrip("/")

    @field_validator("app_timezone")
    @classmethod
    def validate_app_timezone(cls, value: str) -> str:
        normalized = value.strip()
        try:
            ZoneInfo(normalized)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"未知时区：{normalized}") from exc
        return normalized

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_storage_dirs(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
