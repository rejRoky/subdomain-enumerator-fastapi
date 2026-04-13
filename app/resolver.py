from __future__ import annotations

import asyncio
import socket
import logging

logger = logging.getLogger(__name__)

_CONCURRENCY = 50  # max simultaneous DNS lookups


def _resolve_sync(host: str) -> str | None:
    try:
        return socket.gethostbyname(host)
    except socket.gaierror:
        return None


async def resolve_all(
    subdomains: set[str],
    concurrency: int = _CONCURRENCY,
) -> dict[str, str | None]:
    """Resolve all subdomains concurrently using a bounded thread pool."""
    loop = asyncio.get_event_loop()
    sem = asyncio.Semaphore(concurrency)
    results: dict[str, str | None] = {}

    async def resolve_one(host: str) -> None:
        async with sem:
            results[host] = await loop.run_in_executor(None, _resolve_sync, host)

    await asyncio.gather(*[resolve_one(h) for h in subdomains])
    return results
