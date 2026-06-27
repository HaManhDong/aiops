from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from app.services.config_service import ConfigService, DatasourceSettings
from app.agents.server_registry import ServerInfo

log = structlog.get_logger()


@dataclass
class ServerMetricsResult:
    ip: str
    hostname: str
    es_log_count: int
    es_top_errors: list[str]
    cpu_pct: float | None
    ram_pct: float | None
    disk_pct: float | None
    http_error_rate: float | None
    source_available: dict[str, bool]


class ServerMetricsAggregator:
    def __init__(self, config_svc: ConfigService):
        self._config_svc = config_svc

    async def aggregate(
        self,
        app_id: str,
        servers: list[ServerInfo],
        time_range: str,
    ) -> dict[str, ServerMetricsResult]:
        if not servers:
            return {}
        cfg = await self._config_svc.get_datasource(app_id)
        tasks = [self._get_server_metrics(server, cfg, time_range) for server in servers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = {}
        for server, result in zip(servers, results):
            if isinstance(result, Exception):
                log.warning("server_metrics_failed", ip=server.ip, error=str(result))
                output[server.ip] = ServerMetricsResult(
                    ip=server.ip, hostname=server.hostname,
                    es_log_count=0, es_top_errors=[],
                    cpu_pct=None, ram_pct=None, disk_pct=None, http_error_rate=None,
                    source_available={"es": False, "prometheus": False},
                )
            else:
                output[server.ip] = result
        return output

    async def _get_server_metrics(
        self, server: ServerInfo, cfg: DatasourceSettings, time_range: str
    ) -> ServerMetricsResult:
        (es_data, es_ok), (prom_data, prom_ok) = await asyncio.gather(
            _safe(self._query_es_for_server(server.ip, server.hostname, cfg, time_range)),
            _safe(self._query_prometheus_for_server(server.ip, cfg)),
        )
        return ServerMetricsResult(
            ip=server.ip,
            hostname=server.hostname,
            es_log_count=es_data.get("total", 0) if es_ok else 0,
            es_top_errors=es_data.get("top_errors", []) if es_ok else [],
            cpu_pct=prom_data.get("cpu_pct") if prom_ok else None,
            ram_pct=prom_data.get("ram_pct") if prom_ok else None,
            disk_pct=prom_data.get("disk_pct") if prom_ok else None,
            http_error_rate=prom_data.get("http_error_rate") if prom_ok else None,
            source_available={"es": es_ok, "prometheus": prom_ok},
        )

    async def _query_es_for_server(
        self, ip: str, hostname: str, cfg: DatasourceSettings, time_range: str
    ) -> dict:
        body = {
            "query": {"bool": {"must": [
                {"range": {"@timestamp": {"gte": time_range}}},
                {"terms": {"log_level": ["ERROR", "CRITICAL"]}},
                {"bool": {"should": [
                    {"term":  {"ip_target": ip}},
                    {"match": {"message": hostname}},
                    {"match": {"noi_dung": ip}},
                ], "minimum_should_match": 1}},
            ]}},
            "size": 0,
            "aggs": {
                "total":      {"value_count": {"field": "@timestamp"}},
                "top_errors": {"terms": {"field": "error_type", "size": 5}},
            },
        }
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if cfg.elasticsearch_api_key:
            headers["Authorization"] = f"ApiKey {cfg.elasticsearch_api_key}"
        from app.config import settings
        async with httpx.AsyncClient(timeout=settings.es_logs_timeout, verify=False) as client:
            resp = await client.post(
                f"{cfg.elasticsearch_url}/{cfg.app_log_index}/_search",
                json=body,
                headers=headers,
            )
            resp.raise_for_status()
        aggs = resp.json().get("aggregations", {})
        return {
            "total": aggs.get("total", {}).get("value", 0),
            "top_errors": [b["key"] for b in aggs.get("top_errors", {}).get("buckets", [])],
        }

    async def _query_prometheus_for_server(self, ip: str, cfg: DatasourceSettings) -> dict:
        if not cfg.prometheus_url:
            return {}
        from app.config import settings
        instance_filter = f'instance=~"{ip}:.*"'
        queries = {
            "cpu_pct": f'avg(rate(node_cpu_seconds_total{{mode!="idle",{instance_filter}}}[5m])) * 100',
            "ram_pct": f'(1 - node_memory_MemAvailable_bytes{{{instance_filter}}} / node_memory_MemTotal_bytes{{{instance_filter}}}) * 100',
            "disk_pct": f'(1 - node_filesystem_avail_bytes{{{instance_filter},mountpoint="/"}} / node_filesystem_size_bytes{{{instance_filter},mountpoint="/"}}) * 100',
            "http_error_rate": f'sum(rate(http_requests_total{{status=~"5..",{instance_filter}}}[5m]))',
        }
        result: dict[str, float | None] = {}
        async with httpx.AsyncClient(timeout=settings.prometheus_query_timeout) as client:
            for metric, query in queries.items():
                try:
                    r = await client.get(
                        f"{cfg.prometheus_url}/api/v1/query",
                        params={"query": query},
                    )
                    data = r.json().get("data", {}).get("result", [])
                    result[metric] = round(float(data[0]["value"][1]), 1) if data else None
                except Exception as e:
                    log.warning("prometheus_server_query_failed", ip=ip, metric=metric, error=str(e))
                    result[metric] = None
        return result


async def _safe(coro) -> tuple[Any, bool]:
    try:
        return await coro, True
    except Exception:
        return {}, False
