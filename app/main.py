from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .jobs import create_job, delete_job, get_job, list_jobs, purge_expired_jobs, run_enumeration
from .models import EnumerateRequest, JobListResponse, JobResponse

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger(__name__)


# ─── Lifespan ─────────────────────────────────────────────────────────────────


async def _cleanup_loop() -> None:
    """Periodically purge expired jobs from the in-memory store."""
    while True:
        await asyncio.sleep(300)  # run every 5 minutes
        await purge_expired_jobs()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Starting %s", settings.app_name)
    task = asyncio.create_task(_cleanup_loop())
    try:
        yield
    finally:
        task.cancel()
        logger.info("Shutdown complete")


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.app_name,
    version=settings.api_version,
    description=(
        "Passive subdomain enumeration API.\n\n"
        "**Flow**: `POST /api/v1/enumerate` → receive `job_id` → poll "
        "`GET /api/v1/jobs/{job_id}` until `status` is `completed` or `failed`."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ─── Middleware ────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# ─── Exception handlers ───────────────────────────────────────────────────────


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": f"HTTP_{exc.status_code}"},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "code": "INTERNAL_ERROR"},
    )


# ─── Routes ───────────────────────────────────────────────────────────────────

API = f"/api/{settings.api_version}"


@app.get("/health", tags=["System"], summary="Liveness probe")
async def health():
    return {"status": "ok"}


@app.get("/", tags=["System"], summary="API info")
async def root():
    return {
        "name": settings.app_name,
        "version": settings.api_version,
        "docs": "/docs",
    }


@app.post(
    f"{API}/enumerate",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Enumeration"],
    summary="Start a subdomain enumeration job",
    responses={
        202: {"description": "Job accepted — poll /jobs/{job_id} for results"},
        422: {"description": "Invalid domain"},
    },
)
async def start_enumeration(body: EnumerateRequest, background_tasks: BackgroundTasks):
    job_id = await create_job(body.domain)
    background_tasks.add_task(
        run_enumeration,
        job_id=job_id,
        domain=body.domain,
        vt_api_key=body.vt_api_key or "",
        do_resolve=body.resolve_dns,
    )
    logger.info(
        "Accepted job %s for domain %s (resolve_dns=%s)",
        job_id, body.domain, body.resolve_dns,
    )
    return await get_job(job_id)


@app.get(
    f"{API}/jobs",
    response_model=JobListResponse,
    tags=["Jobs"],
    summary="List all jobs (newest first)",
)
async def list_all_jobs():
    jobs = await list_jobs()
    return JobListResponse(jobs=jobs, total=len(jobs))


@app.get(
    f"{API}/jobs/{{job_id}}",
    response_model=JobResponse,
    tags=["Jobs"],
    summary="Get job status and results",
    responses={404: {"description": "Job not found"}},
)
async def get_job_status(job_id: str):
    job = await get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job


@app.delete(
    f"{API}/jobs/{{job_id}}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Jobs"],
    summary="Delete a job",
    responses={404: {"description": "Job not found"}},
)
async def remove_job(job_id: str):
    if not await delete_job(job_id):
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
