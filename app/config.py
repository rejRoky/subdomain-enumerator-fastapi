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

    # Job store
    max_jobs: int = 100
    job_ttl_seconds: int = 3600  # prune jobs older than 1 hour

    # HTTP client
    http_timeout: float = 30.0
    http_user_agent: str = "Mozilla/5.0 SubdomainEnumerator/1.0"

    # CORS — override via env: CORS_ORIGINS='["https://app.example.com"]'
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])


settings = Settings()
