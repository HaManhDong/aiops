from __future__ import annotations
import httpx
import structlog
from app.providers.metrics.base import MetricsBase

log = structlog.get_logger()

_METRICBEAT_INDEX = "metricbeat-*"


class MetricbeatProvider(MetricsBase):
    def __init__(self, es_url: str, api_key: str | None = None):
        self._es_url = es_url.rstrip("/")
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"ApiKey {api_key}"

    async def query_instant(self, query: str) -> list[dict]:
        # Metricbeat does not use PromQL — use query_hosts() instead
        raise NotImplementedError("Use query_hosts() for metricbeat")

    async def query_range(self, query: str, start: str, end: str, step: str = "5m") -> list[dict]:
        raise NotImplementedError("Use query_hosts() for metricbeat")

    async def query_hosts(self, time_range: str = "now-5m") -> list[dict]:
        """
        Single ES request for all hosts — fetches avg CPU/RAM/disk.
        Returns list[{host: str, cpu_pct: float, ram_pct: float, disk_pct: float}]
        """
        from app.config import settings
        body = {
            "size": 0,
            "query": {"range": {"@timestamp": {"gte": time_range}}},
            "aggs": {
                "by_host": {
                    "terms": {"field": "host.name", "size": 100},
                    "aggs": {
                        "cpu_pct":  {"avg": {"field": "system.cpu.total.pct"}},
                        "ram_pct":  {"avg": {"field": "system.memory.actual.used.pct"}},
                        "disk_pct": {"avg": {"field": "system.filesystem.used.pct"}},
                    },
                }
            },
        }
        async with httpx.AsyncClient(timeout=settings.es_logs_timeout, verify=False) as client:
            resp = await client.post(
                f"{self._es_url}/{_METRICBEAT_INDEX}/_search",
                headers=self._headers,
                json=body,
            )
            resp.raise_for_status()
        buckets = resp.json().get("aggregations", {}).get("by_host", {}).get("buckets", [])
        return [
            {
                "host": b["key"],
                "cpu_pct":  round(b["cpu_pct"]["value"] or 0, 1),
                "ram_pct":  round(b["ram_pct"]["value"] or 0, 1),
                "disk_pct": round(b["disk_pct"]["value"] or 0, 1),
            }
            for b in buckets
        ]
