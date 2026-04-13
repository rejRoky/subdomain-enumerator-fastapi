from __future__ import annotations

from typing import Optional

from .db import db_create_job, db_delete_job, db_get_job, db_list_jobs
from .models import EnumerationResult, JobResponse, JobStatus
from .worker import enumerate_subdomains


def _to_response(record) -> JobResponse:
    return JobResponse(
        job_id=record.job_id,
        status=JobStatus(record.status),
        domain=record.domain,
        created_at=record.created_at,
        completed_at=record.completed_at,
        progress=record.progress,
        result=EnumerationResult.model_validate(record.result) if record.result else None,
        error=record.error,
    )


async def create_job(domain: str, vt_api_key: str, do_resolve: bool) -> JobResponse:
    job_id = await db_create_job(domain)
    enumerate_subdomains.delay(
        job_id=job_id,
        domain=domain,
        vt_api_key=vt_api_key,
        do_resolve=do_resolve,
    )
    record = await db_get_job(job_id)
    return _to_response(record)  # type: ignore[arg-type]


async def get_job(job_id: str) -> Optional[JobResponse]:
    record = await db_get_job(job_id)
    return _to_response(record) if record else None


async def list_jobs(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
) -> tuple[list[JobResponse], int]:
    records, total = await db_list_jobs(limit=limit, offset=offset, status=status)
    return [_to_response(r) for r in records], total


async def delete_job(job_id: str) -> bool:
    return await db_delete_job(job_id)
