# Subdomain Enumerator

A production-grade passive subdomain enumeration platform built with **FastAPI**, **Celery**, **PostgreSQL**, **Redis**, and a **Streamlit** frontend — all wired together behind an **Nginx** reverse proxy.

## Features

- **Passive-only enumeration** — queries public data sources, no active scanning
- **Async job queue** — submit a job and poll for results; Celery workers handle the heavy lifting
- **6 data sources** aggregated per scan:
  - [crt.sh](https://crt.sh) — Certificate Transparency logs
  - [HackerTarget](https://hackertarget.com) — Passive DNS (no key required)
  - [RapidDNS](https://rapiddns.io) — Passive DNS
  - [AlienVault OTX](https://otx.alienvault.com) — Passive DNS
  - [urlscan.io](https://urlscan.io) — Web scan history
  - [VirusTotal](https://www.virustotal.com) — Subdomain intelligence *(optional free API key)*
- **DNS resolution** — optionally resolves each discovered subdomain to an IP
- **Streamlit UI** — submit jobs, track progress, view live/dead subdomains, download CSVs
- **Interactive API docs** — Swagger UI and ReDoc served at `/docs` and `/redoc`
- **Flower** — Celery task monitoring dashboard
- **Alembic** migrations — schema versioned from day one

## Architecture

```
Browser
  │
  ▼
Nginx :80          ← single entry point
  ├── /            → Streamlit frontend :8501
  ├── /api/v1/*    → FastAPI :8000
  ├── /docs        → FastAPI Swagger UI
  └── /health      → FastAPI health probe

FastAPI ──► PostgreSQL   (job persistence)
        ──► Redis        (Celery broker & result backend)
        ──► Celery Worker (enumeration tasks)
        ──► Celery Beat   (scheduled cleanup)
        ──► Flower :5555  (worker monitoring)
```

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/)

### 1. Clone and configure

```bash
git clone https://github.com/rejroky/subdomain-enumerator-fastapi.git
cd subdomain-enumerator-fastapi

cp .env.example .env
# Edit .env — at minimum set POSTGRES_PASSWORD
```

### 2. Start all services

```bash
docker compose up -d --build
```

Wait ~30 seconds for the health checks to pass, then open:

| URL | Service |
|-----|---------|
| `http://localhost` | Streamlit UI |
| `http://localhost/docs` | FastAPI Swagger UI |
| `http://localhost/redoc` | FastAPI ReDoc |
| `http://localhost:5555` | Flower (Celery monitor) |

### 3. Stop

```bash
docker compose down          # keep data volumes
docker compose down -v       # also remove data volumes
```

## API Usage

### Start an enumeration job

```bash
curl -X POST http://localhost/api/v1/enumerate \
  -H "Content-Type: application/json" \
  -d '{"domain": "example.com", "resolve_dns": true}'
```

Response (`202 Accepted`):

```json
{
  "job_id": "a1b2c3d4-...",
  "status": "pending",
  "domain": "example.com",
  "created_at": "2026-04-13T12:00:00Z"
}
```

### Poll for results

```bash
curl http://localhost/api/v1/jobs/a1b2c3d4-...
```

Poll until `status` is `completed` or `failed`. The completed response includes:

```json
{
  "status": "completed",
  "result": {
    "total": 42,
    "live_count": 38,
    "dead_count": 4,
    "live": { "api.example.com": "93.184.216.34", "..." : "..." },
    "dead": ["old.example.com"],
    "sources": { "crt.sh": ["..."], "hackertarget": ["..."] },
    "source_summary": [{ "name": "crt.sh", "count": 30 }]
  }
}
```

### Other endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/enumerate` | Start a new job |
| `GET` | `/api/v1/jobs` | List jobs (paginated, filterable by status) |
| `GET` | `/api/v1/jobs/{job_id}` | Get job status and results |
| `DELETE` | `/api/v1/jobs/{job_id}` | Delete a job |
| `GET` | `/health` | Liveness probe |

## Configuration

All settings are controlled via environment variables (or `.env`):

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `DEBUG` | `false` | FastAPI debug mode |
| `CORS_ORIGINS` | `["*"]` | Allowed CORS origins |
| `VT_API_KEY` | *(empty)* | Optional VirusTotal free API key |
| `JOB_TTL_SECONDS` | `86400` | Seconds before completed jobs are purged (24 h) |
| `POSTGRES_DB` | `subdomain_enumerator` | Database name |
| `POSTGRES_USER` | `postgres` | Database user |
| `POSTGRES_PASSWORD` | `changeme` | **Change this in production** |
| `DATABASE_URL` | *(derived)* | Full asyncpg connection string |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection string |
| `NGINX_PORT` | `80` | Host port for Nginx |
| `FLOWER_PORT` | `5555` | Host port for Flower |
| `POSTGRES_PORT` | `5432` | Host port for PostgreSQL |
| `REDIS_PORT` | `6379` | Host port for Redis |

## Project Structure

```
.
├── app/
│   ├── main.py          # FastAPI app, routes
│   ├── models.py        # Pydantic request/response schemas
│   ├── jobs.py          # Job CRUD (database layer)
│   ├── worker.py        # Celery task — orchestrates enumeration
│   ├── fetchers.py      # Per-source async fetch functions
│   ├── resolver.py      # DNS resolution
│   ├── celery_app.py    # Celery + Beat configuration
│   ├── db.py            # SQLAlchemy async engine & session
│   └── config.py        # Pydantic settings
├── frontend/
│   └── app.py           # Streamlit UI
├── alembic/
│   └── versions/        # Database migrations
├── nginx/
│   └── nginx.conf       # Reverse proxy configuration
├── Dockerfile           # API + worker image
├── Dockerfile.frontend  # Streamlit image
├── docker-compose.yml   # Full stack definition
├── entrypoint.sh        # Runs migrations then starts Uvicorn
├── requirements.txt     # Python dependencies (API)
└── .env.example         # Environment variable template
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI, Uvicorn, Pydantic v2 |
| Task queue | Celery 5, Redis |
| Database | PostgreSQL 16, SQLAlchemy (async), Alembic |
| Frontend | Streamlit, Plotly |
| Proxy | Nginx |
| Monitoring | Flower |
| Packaging | Docker, Docker Compose |

## License

This project is licensed under the [MIT License](LICENSE).
