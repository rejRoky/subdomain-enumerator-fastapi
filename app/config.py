from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "Subdomain Enumerator API"
    api_version: str = "v1"
    debug: bool = False
    log_level: str = "INFO"

    # Optional API keys
    vt_api_key: str = ""

    # Job TTL — completed/failed jobs older than this are purged
    job_ttl_seconds: int = 86400  # 24 hours

    # HTTP client
    http_timeout: float = 30.0
    http_user_agent: str = "Mozilla/5.0 SubdomainEnumerator/1.0"

    # CORS — override: CORS_ORIGINS='["https://app.example.com"]'
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    # PostgreSQL (asyncpg driver)
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/subdomain_enumerator"

    # Redis (Celery broker + result backend)
    redis_url: str = "redis://localhost:6379/0"


settings = Settings()
