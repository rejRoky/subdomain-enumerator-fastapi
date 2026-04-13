from __future__ import annotations

from celery import Celery

from .config import settings

celery_app = Celery(
    "subdomain_enumerator",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.worker"],
)

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,

    # Reliability
    task_acks_late=True,               # ack only after task finishes
    task_reject_on_worker_lost=True,   # requeue if worker crashes mid-task
    worker_prefetch_multiplier=1,      # one task at a time per worker thread

    # Timeouts (enumeration can take ~60 s)
    task_soft_time_limit=180,          # raises SoftTimeLimitExceeded
    task_time_limit=240,               # SIGKILL after this

    # Periodic tasks (Celery Beat)
    beat_schedule={
        "purge-expired-jobs": {
            "task": "app.worker.purge_expired_jobs",
            "schedule": 300.0,  # every 5 minutes
        },
    },
)
