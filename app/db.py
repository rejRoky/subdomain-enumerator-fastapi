from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Optional

from sqlalchemy import DateTime, Index, JSON, String, Text, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import settings

logger = logging.getLogger(__name__)


# ─── ORM ──────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class JobRecord(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_domain", "domain"),
        Index("ix_jobs_created_at", "created_at"),
    )

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    progress: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ─── Engine & session ─────────────────────────────────────────────────────────

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=settings.debug,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields an async session."""
    async with AsyncSessionLocal() as session:
        yield session


# ─── CRUD ─────────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


async def db_create_job(domain: str) -> str:
    job_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as session:
        session.add(JobRecord(
            job_id=job_id,
            status="pending",
            domain=domain,
            created_at=_now(),
            progress="Queued",
        ))
        await session.commit()
    return job_id


async def db_get_job(job_id: str) -> Optional[JobRecord]:
    async with AsyncSessionLocal() as session:
        return await session.get(JobRecord, job_id)


async def db_list_jobs(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
) -> tuple[list[JobRecord], int]:
    async with AsyncSessionLocal() as session:
        base = select(JobRecord)
        if status:
            base = base.where(JobRecord.status == status)

        total: int = (
            await session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()

        rows = (
            await session.execute(
                base.order_by(JobRecord.created_at.desc()).limit(limit).offset(offset)
            )
        ).scalars().all()

        return list(rows), total


async def db_update_job(job_id: str, **kwargs) -> None:
    if not kwargs:
        return
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(JobRecord).where(JobRecord.job_id == job_id).values(**kwargs)
        )
        await session.commit()


async def db_delete_job(job_id: str) -> bool:
    async with AsyncSessionLocal() as session:
        record = await session.get(JobRecord, job_id)
        if record is None:
            return False
        await session.delete(record)
        await session.commit()
        return True


async def db_purge_expired_jobs(ttl_seconds: int) -> int:
    cutoff = _now() - timedelta(seconds=ttl_seconds)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(JobRecord)
            .where(
                JobRecord.status.in_(["completed", "failed"]),
                JobRecord.created_at < cutoff,
            )
        )
        await session.commit()
        count: int = result.rowcount  # type: ignore[assignment]
    if count:
        logger.info("Purged %d expired jobs", count)
    return count
