from __future__ import annotations
import httpx
import structlog
from app.providers.metrics.base import MetricsBase

log = structlog.get_logger()


class PrometheusProvider(MetricsBase):
    def __init__(self, url: str):
        self._url = url.rstrip("/")

    async def query_instant(self, query: str) -> list[dict]:
        from app.config import settings
        async with httpx.AsyncClient(timeout=settings.prometheus_query_timeout) as client:
            resp = await client.get(
                f"{self._url}/api/v1/query",
                params={"query": query},
            )
            resp.raise_for_status()
            return resp.json().get("data", {}).get("result", [])

    async def query_range(self, query: str, start: str, end: str, step: str = "5m") -> list[dict]:
        from app.config import settings
        async with httpx.AsyncClient(timeout=settings.prometheus_range_timeout) as client:
            resp = await client.get(
                f"{self._url}/api/v1/query_range",
                params={"query": query, "start": start, "end": end, "step": step},
            )
            resp.raise_for_status()
            return resp.json().get("data", {}).get("result", [])
