from __future__ import annotations
from dataclasses import dataclass
import httpx
import structlog

log = structlog.get_logger()


@dataclass
class ProbeResult:
    url: str
    reachable: bool
    latency_ms: int
    error: str | None = None


async def probe_http(url: str, path: str = "/") -> ProbeResult:
    """HTTP liveness check with configurable timeout."""
    import time
    from app.config import settings
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=settings.service_probe_timeout, verify=False) as client:
            resp = await client.get(f"{url.rstrip('/')}{path}")
            latency = int((time.monotonic() - start) * 1000)
            return ProbeResult(url=url, reachable=resp.status_code < 500, latency_ms=latency)
    except Exception as e:
        latency = int((time.monotonic() - start) * 1000)
        return ProbeResult(url=url, reachable=False, latency_ms=latency, error=str(e))
