# Skill: Server Metrics Aggregator (M16)

## Mục đích
M16 chạy song song với M6 (QueryExecutor). Với mỗi server IP trong registry,
query Elasticsearch và Prometheus để lấy metrics riêng theo từng server.
Output được M7 dùng để tổng hợp câu trả lời theo từng server vật lý.

## Vị trí trong pipeline

```
M6: QueryExecutor ──┐
                    ├──► asyncio.gather ──► M7: AnswerSynthesizer
M16: ServerMetricsAgg ─┘
```

M16 chỉ chạy khi intent là `HEALTH_CHECK`, `METRIC_QUERY`, hoặc `ROOT_CAUSE`
**và** ServerRegistry trả về danh sách server (status = FOUND).

## File: `agents/server_metrics.py`

```python
"""
M16: Server Metrics Aggregator.
Query ES log và Prometheus metrics theo từng server IP trong registry.
Chạy song song với M6 bằng asyncio.gather.
"""
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
    es_log_count: int              # số lỗi trong time_range
    es_top_errors: list[str]       # top 5 error_type
    cpu_pct: float | None          # từ Prometheus
    ram_pct: float | None
    disk_pct: float | None
    http_error_rate: float | None  # request/s lỗi 5xx
    source_available: dict[str, bool]  # {"es": True, "prometheus": False}


class ServerMetricsAggregator:
    def __init__(self, config_svc: ConfigService):
        self._config_svc = config_svc

    async def aggregate(
        self,
        app_id: str,
        servers: list[ServerInfo],
        time_range: str,           # "now-1h" | "now-6h" | "now-24h" | "now-7d"
    ) -> dict[str, ServerMetricsResult]:
        """
        Query metrics song song cho tất cả server.
        Trả về dict {ip: ServerMetricsResult}.
        Nếu một server fail → trả partial result, không dừng toàn bộ.
        """
        cfg = await self._config_svc.get_datasource(app_id)

        tasks = [
            self._get_server_metrics(server, cfg, time_range)
            for server in servers
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = {}
        for server, result in zip(servers, results):
            if isinstance(result, Exception):
                log.warning("server_metrics_failed",
                            ip=server.ip, hostname=server.hostname, error=str(result))
                # Trả về empty result để M7 biết không có dữ liệu
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
        self,
        server: ServerInfo,
        cfg: DatasourceSettings,
        time_range: str,
    ) -> ServerMetricsResult:
        """Query ES và Prometheus song song cho một server."""
        es_task   = self._query_es_for_server(server.ip, server.hostname, cfg, time_range)
        prom_task = self._query_prometheus_for_server(server.ip, cfg)

        (es_data, es_ok), (prom_data, prom_ok) = await asyncio.gather(
            _safe(es_task),
            _safe(prom_task),
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
        """
        Query ES lấy log errors liên quan đến server IP hoặc hostname.
        Filter theo ip_target field hoặc hostname trong message.
        """
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
            }
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{cfg.elasticsearch_url}/{cfg.log_index_pattern}/_search",
                json=body,
                headers={"Authorization": f"ApiKey {cfg.elasticsearch_api_key}"},
            )
            resp.raise_for_status()

        data = resp.json()
        aggs = data.get("aggregations", {})
        return {
            "total": aggs.get("total", {}).get("value", 0),
            "top_errors": [
                b["key"] for b in aggs.get("top_errors", {}).get("buckets", [])
            ],
        }

    async def _query_prometheus_for_server(
        self, ip: str, cfg: DatasourceSettings
    ) -> dict:
        """
        Query Prometheus lấy CPU, RAM, disk, HTTP error rate cho server IP.
        ip được dùng làm label filter trong PromQL.
        """
        if not cfg.prometheus_url:
            return {}

        # instance label thường là "ip:port" — dùng regex match
        instance_filter = f'instance=~"{ip}:.*"'

        queries = {
            "cpu_pct": (
                f'avg(rate(node_cpu_seconds_total{{mode!="idle",{instance_filter}}}[5m])) * 100'
            ),
            "ram_pct": (
                f'(1 - node_memory_MemAvailable_bytes{{{instance_filter}}}'
                f' / node_memory_MemTotal_bytes{{{instance_filter}}}) * 100'
            ),
            "disk_pct": (
                f'(1 - node_filesystem_avail_bytes{{{instance_filter},mountpoint="/"}}'
                f' / node_filesystem_size_bytes{{{instance_filter},mountpoint="/"}}) * 100'
            ),
            "http_error_rate": (
                f'sum(rate(http_requests_total{{status=~"5..",{instance_filter}}}[5m]))'
            ),
        }

        result = {}
        async with httpx.AsyncClient(timeout=5) as client:
            for metric, query in queries.items():
                try:
                    r = await client.get(
                        f"{cfg.prometheus_url}/api/v1/query",
                        params={"query": query},
                    )
                    data = r.json().get("data", {}).get("result", [])
                    if data:
                        result[metric] = round(float(data[0]["value"][1]), 1)
                except Exception as e:
                    log.warning("prometheus_server_query_failed",
                                ip=ip, metric=metric, error=str(e))
                    result[metric] = None

        return result


async def _safe(coro) -> tuple[Any, bool]:
    """Bọc coroutine để không raise — trả (result, ok)."""
    try:
        return await coro, True
    except Exception:
        return {}, False
```

## Cách gọi từ routers/chat.py

```python
# Chạy M6 và M16 song song
query_task   = query_executor.execute(intent)
metrics_task = server_metrics_agg.aggregate(
    app_id=intent.app_id,
    servers=registry_result.servers,
    time_range=intent.time_range,
) if registry_result.status == RegistryStatus.FOUND else asyncio.coroutine(lambda: {})()

context, server_metrics = await asyncio.gather(query_task, metrics_task)
context["server_metrics"] = server_metrics  # pass vào M7
```

## Lưu ý

1. **Timeout riêng**: ES timeout 10s, Prometheus timeout 5s — không để một source block cả pipeline
2. **Partial failure**: nếu một server fail → `source_available = {"es": False}`, M7 sẽ note "không có dữ liệu cho server X"
3. **instance label format**: Prometheus thường dùng `ip:port` — regex match `ip:.*` để bắt tất cả port
4. **Empty result khi không có server**: nếu registry KHÔNG tìm thấy server → skip M16 hoàn toàn, không query
