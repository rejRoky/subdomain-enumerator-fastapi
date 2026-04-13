from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone

import httpx

from .config import settings
from .fetchers import PASSIVE_SOURCES, fetch_virustotal
from .models import EnumerationResult, JobResponse, JobStatus, SourceSummary
from .resolver import resolve_all

logger = logging.getLogger(__name__)

# In-memory job store — replace with Redis for multi-worker deployments
_jobs: dict[str, JobResponse] = {}
_lock = asyncio.Lock()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─── Public API ───────────────────────────────────────────────────────────────


async def create_job(domain: str) -> str:
    job_id = str(uuid.uuid4())
    job = JobResponse(
        job_id=job_id,
        status=JobStatus.pending,
        domain=domain,
        created_at=_utcnow(),
        progress="Queued",
    )
    async with _lock:
        # Evict the oldest job when at capacity
        if len(_jobs) >= settings.max_jobs:
            oldest = min(_jobs.values(), key=lambda j: j.created_at)
            del _jobs[oldest.job_id]
            logger.debug("Evicted oldest job %s (store at capacity)", oldest.job_id)
        _jobs[job_id] = job
    return job_id


async def get_job(job_id: str) -> JobResponse | None:
    return _jobs.get(job_id)


async def list_jobs() -> list[JobResponse]:
    return sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)


async def delete_job(job_id: str) -> bool:
    async with _lock:
        if job_id not in _jobs:
            return False
        del _jobs[job_id]
        return True


async def purge_expired_jobs() -> int:
    """Remove completed/failed jobs older than job_ttl_seconds. Returns count removed."""
    cutoff = _utcnow().timestamp() - settings.job_ttl_seconds
    to_remove = [
        jid
        for jid, job in _jobs.items()
        if job.status in (JobStatus.completed, JobStatus.failed)
        and job.created_at.timestamp() < cutoff
    ]
    async with _lock:
        for jid in to_remove:
            _jobs.pop(jid, None)
    if to_remove:
        logger.info("Purged %d expired jobs", len(to_remove))
    return len(to_remove)


# ─── Internal helpers ─────────────────────────────────────────────────────────


async def _update(job_id: str, **kwargs) -> None:
    async with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            _jobs[job_id] = job.model_copy(update=kwargs)


# ─── Core enumeration task ────────────────────────────────────────────────────


async def run_enumeration(
    job_id: str,
    domain: str,
    vt_api_key: str,
    do_resolve: bool,
) -> None:
    await _update(job_id, status=JobStatus.running, progress="Starting passive DNS enumeration…")
    logger.info("Job %s started for %s", job_id, domain)

    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": settings.http_user_agent},
            follow_redirects=True,
        ) as client:
            # ── Query all passive sources concurrently ──
            await _update(job_id, progress="Querying passive DNS sources…")

            source_tasks = {
                name: fetcher(client, domain)  # type: ignore[operator]
                for name, fetcher in PASSIVE_SOURCES.items()
            }
            source_tasks["virustotal"] = fetch_virustotal(
                client, domain, vt_api_key or settings.vt_api_key
            )

            raw_results = await asyncio.gather(
                *source_tasks.values(), return_exceptions=True
            )
            name_results: dict[str, set[str]] = {}
            for name, result in zip(source_tasks.keys(), raw_results):
                if isinstance(result, Exception):
                    logger.warning("Source %s raised: %s", name, result)
                    name_results[name] = set()
                else:
                    name_results[name] = result  # type: ignore[assignment]

            # ── Normalise: keep only subdomains of the target ──
            source_map: dict[str, set[str]] = defaultdict(set)
            all_subs: set[str] = set()
            for name, subs in name_results.items():
                cleaned = {s for s in subs if s.endswith(f".{domain}") and s != domain}
                source_map[name] = cleaned
                all_subs |= cleaned
                logger.debug("Source %s → %d subdomains", name, len(cleaned))

            # ── DNS resolution ──
            resolved: dict[str, str | None]
            if do_resolve and all_subs:
                await _update(
                    job_id,
                    progress=f"Resolving DNS for {len(all_subs)} subdomains…",
                )
                resolved = await resolve_all(all_subs)
            else:
                resolved = {h: None for h in all_subs}

            live = {h: ip for h, ip in resolved.items() if ip}
            dead = sorted(h for h, ip in resolved.items() if not ip)

            result = EnumerationResult(
                domain=domain,
                live=dict(sorted(live.items())),
                dead=dead,
                sources={name: sorted(subs) for name, subs in source_map.items()},
                source_summary=[
                    SourceSummary(name=name, count=len(subs))
                    for name, subs in sorted(source_map.items())
                ],
                total=len(all_subs),
                live_count=len(live),
                dead_count=len(dead),
            )

            await _update(
                job_id,
                status=JobStatus.completed,
                completed_at=_utcnow(),
                progress="Done",
                result=result,
            )
            logger.info(
                "Job %s completed — total=%d live=%d dead=%d",
                job_id,
                len(all_subs),
                len(live),
                len(dead),
            )

    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        await _update(
            job_id,
            status=JobStatus.failed,
            completed_at=_utcnow(),
            progress="Failed",
            error=str(exc),
        )
