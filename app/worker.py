from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone

import httpx

from .celery_app import celery_app
from .config import settings
from .db import db_purge_expired_jobs, db_update_job
from .fetchers import PASSIVE_SOURCES, fetch_virustotal
from .models import EnumerationResult, JobStatus, SourceSummary
from .resolver import resolve_all

logger = logging.getLogger(__name__)


# ─── Celery tasks ─────────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="app.worker.enumerate_subdomains",
    max_retries=0,
)
def enumerate_subdomains(
    self,  # noqa: ANN001
    job_id: str,
    domain: str,
    vt_api_key: str,
    do_resolve: bool,
) -> None:
    asyncio.run(_enumerate_async(job_id, domain, vt_api_key, do_resolve))


@celery_app.task(name="app.worker.purge_expired_jobs")
def purge_expired_jobs() -> int:
    return asyncio.run(db_purge_expired_jobs(settings.job_ttl_seconds))


# ─── Async implementation ─────────────────────────────────────────────────────

async def _enumerate_async(
    job_id: str,
    domain: str,
    vt_api_key: str,
    do_resolve: bool,
) -> None:
    await db_update_job(
        job_id,
        status=JobStatus.running,
        progress="Starting passive DNS enumeration…",
    )
    logger.info("Job %s started for %s", job_id, domain)

    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": settings.http_user_agent},
            follow_redirects=True,
        ) as client:
            await db_update_job(job_id, progress="Querying passive DNS sources…")

            source_tasks = {
                name: fetcher(client, domain)  # type: ignore[operator]
                for name, fetcher in PASSIVE_SOURCES.items()
            }
            source_tasks["virustotal"] = fetch_virustotal(
                client, domain, vt_api_key or settings.vt_api_key
            )

            raw_results = await asyncio.gather(*source_tasks.values(), return_exceptions=True)

            name_results: dict[str, set[str]] = {}
            for name, result in zip(source_tasks.keys(), raw_results):
                if isinstance(result, Exception):
                    logger.warning("Source %s raised: %s", name, result)
                    name_results[name] = set()
                else:
                    name_results[name] = result  # type: ignore[assignment]

            source_map: dict[str, set[str]] = defaultdict(set)
            all_subs: set[str] = set()
            for name, subs in name_results.items():
                cleaned = {s for s in subs if s.endswith(f".{domain}") and s != domain}
                source_map[name] = cleaned
                all_subs |= cleaned
                logger.debug("Source %s → %d subdomains", name, len(cleaned))

            resolved: dict[str, str | None]
            if do_resolve and all_subs:
                await db_update_job(
                    job_id, progress=f"Resolving DNS for {len(all_subs)} subdomains…"
                )
                resolved = await resolve_all(all_subs)
            else:
                resolved = {h: None for h in all_subs}

            live = {h: ip for h, ip in resolved.items() if ip}
            dead = sorted(h for h, ip in resolved.items() if not ip)

            result_obj = EnumerationResult(
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

            await db_update_job(
                job_id,
                status=JobStatus.completed,
                completed_at=datetime.now(timezone.utc),
                progress="Done",
                result=result_obj.model_dump(),
            )
            logger.info(
                "Job %s completed — total=%d live=%d dead=%d",
                job_id, len(all_subs), len(live), len(dead),
            )

    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        await db_update_job(
            job_id,
            status=JobStatus.failed,
            completed_at=datetime.now(timezone.utc),
            progress="Failed",
            error=str(exc),
        )
