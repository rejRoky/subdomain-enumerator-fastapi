from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator

_DOMAIN_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$"
)


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class EnumerateRequest(BaseModel):
    domain: str = Field(..., examples=["example.com"])
    vt_api_key: Optional[str] = Field(
        default=None, description="Optional VirusTotal API key (overrides server default)"
    )
    resolve_dns: bool = Field(
        default=True, description="Resolve DNS for each discovered subdomain"
    )

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        v = v.lower().strip().lstrip("*.")
        if not _DOMAIN_RE.match(v):
            raise ValueError(f"'{v}' is not a valid domain name")
        return v


class SourceSummary(BaseModel):
    name: str
    count: int


class EnumerationResult(BaseModel):
    domain: str
    live: dict[str, str] = Field(description="Subdomain → IP for resolved hosts")
    dead: list[str] = Field(description="Subdomains that did not resolve")
    sources: dict[str, list[str]] = Field(description="Subdomains discovered per source")
    source_summary: list[SourceSummary]
    total: int
    live_count: int
    dead_count: int


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    domain: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    progress: Optional[str] = None
    result: Optional[EnumerationResult] = None
    error: Optional[str] = None


class JobListResponse(BaseModel):
    jobs: list[JobResponse]
    total: int
