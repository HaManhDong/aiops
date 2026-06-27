from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.config_service import ConfigService

log = structlog.get_logger()

_ES_CACHE_PREFIX = "qcache:es_logs:"


def _cache_key(body: dict) -> str:
    raw = json.dumps(body, sort_keys=True)
    return _ES_CACHE_PREFIX + hashlib.sha256(raw.encode()).hexdigest()[:20]


class QueryExecutor:
    def __init__(self, config_svc: ConfigService, db: AsyncSession):
        self._cfg = config_svc
        self._db = db

    async def execute(self, intent) -> dict:
        """
        Main entry point. Dispatch theo app_ids trong intent.
        """
        from app.agents.intent import QueryIntent

        if not intent.app_ids:
            return {"error": "Không xác định được hệ thống cần truy vấn", "error_type": "no_app_id"}

        if len(intent.app_ids) == 1:
            return await self._execute_single(intent.app_ids[0], intent)
        else:
            # Multi-service parallel
            tasks = [self._execute_single(app_id, intent) for app_id in intent.app_ids]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            services = {}
            for app_id, r in zip(intent.app_ids, results):
                services[app_id] = r if not isinstance(r, Exception) else {"error": str(r)}
            return {
                "multi_service": True,
                "services": services,
                "data_fetched_at": datetime.now(timezone.utc).isoformat(),
            }

    async def _execute_single(self, app_id: str, intent) -> dict:
        from app.agents.server_registry import ServerRegistryAgent, RegistryStatus
        from app.agents.intent import QueryIntent

        try:
            cfg = await self._cfg.get_datasource(app_id)
        except ValueError:
            return {"error": f"Datasource '{app_id}' chưa được cấu hình", "error_type": "service_not_configured"}

        # Server registry lookup
        registry_agent = ServerRegistryAgent(self._db)
        registry_result = await registry_agent.get_servers(app_id)

        context: dict = {
            "registry": {
                "status": registry_result.status.value,
                "servers": [
                    {"id": s.id, "hostname": s.hostname, "ip": s.ip, "os": s.os}
                    for s in registry_result.servers
                ],
            },
            "_queries_used": [],
            "data_fetched_at": datetime.now(timezone.utc).isoformat(),
        }

        # Build parallel tasks
        tasks: dict = {}

        # ES logs — always (except certain intents)
        if intent.intent not in (
            QueryIntent.SERVER_QUERY,
            QueryIntent.THREAT_MODEL,
            QueryIntent.CLARIFICATION,
        ):
            tasks["es_logs"] = self._query_es_logs(cfg, intent)
            tasks["es_log_stats"] = self._query_log_stats(cfg, intent)
            tasks["es_top_errors"] = self._query_top_errors(cfg, intent)

        # Metrics — for health/metric/root cause
        if intent.intent in (
            QueryIntent.HEALTH_CHECK,
            QueryIntent.METRIC_QUERY,
            QueryIntent.ROOT_CAUSE,
            QueryIntent.INCIDENT_ANALYSIS,
        ):
            if cfg.prometheus_url:
                tasks["server_metrics"] = self._query_prometheus(cfg, intent, registry_result.servers)

        # Execute all in parallel
        if tasks:
            task_names = list(tasks.keys())
            task_coros = list(tasks.values())
            results = await asyncio.gather(*task_coros, return_exceptions=True)
            for name, result in zip(task_names, results):
                if isinstance(result, Exception):
                    log.warning("query_task_failed", task=name, app_id=app_id, error=str(result))
                    context[name] = None
                else:
                    context[name] = result

        return context

    async def _query_es_logs(self, cfg, intent) -> dict:
        from app.config import settings

        body: dict = {
            "query": {"bool": {"must": [
                {"range": {"@timestamp": {"gte": intent.time_range, "lte": "now"}}},
            ]}},
            "sort": [{"@timestamp": {"order": "desc"}}],
            "size": settings.es_logs_size_normal,
        }

        # Add keyword filter
        if intent.keywords:
            body["query"]["bool"]["should"] = [
                {
                    "multi_match": {
                        "query": " ".join(intent.keywords[:5]),
                        "fields": ["message", "log.message", "tieu_de", "noi_dung"],
                    }
                }
            ]

        cache_key = _cache_key({
            **body,
            "_index": cfg.app_log_index,
            "_es_url": cfg.elasticsearch_url,
        })

        # Try cache
        try:
            from app.redis_client import get_redis
            redis = await get_redis()
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

        # Hit ES
        from app.providers.log_storage.elasticsearch import ElasticsearchProvider
        provider = ElasticsearchProvider(url=cfg.elasticsearch_url, api_key=cfg.elasticsearch_api_key)
        try:
            result = await provider.search(cfg.app_log_index, body, size=settings.es_logs_size_normal)
            result["_query"] = {
                "source": "es_logs",
                "index": cfg.app_log_index,
                "es_url": cfg.elasticsearch_url,
                "body": body,
            }
        except Exception as e:
            log.warning("es_logs_query_failed", error=str(e))
            return {"total": 0, "hits": [], "error": str(e)}

        # Write cache (best-effort)
        try:
            from app.redis_client import get_redis
            redis = await get_redis()
            result_no_query = {k: v for k, v in result.items() if k != "_query"}
            await redis.setex(
                cache_key, settings.es_result_cache_ttl, json.dumps(result_no_query)
            )
        except Exception:
            pass

        return result

    async def _query_log_stats(self, cfg, intent) -> dict:
        body = {
            "size": 0,
            "query": {"range": {"@timestamp": {"gte": intent.time_range}}},
            "aggs": {
                "by_level": {"terms": {"field": "log.level.keyword", "size": 10}},
            },
        }
        from app.providers.log_storage.elasticsearch import ElasticsearchProvider
        provider = ElasticsearchProvider(url=cfg.elasticsearch_url, api_key=cfg.elasticsearch_api_key)
        try:
            result = await provider.search(cfg.app_log_index, body, size=0)
            buckets = result.get("aggs", {}).get("by_level", {}).get("buckets", [])
            return {"by_level": [{"level": b["key"], "count": b["doc_count"]} for b in buckets]}
        except Exception as e:
            log.warning("log_stats_query_failed", error=str(e))
            return {"by_level": []}

    async def _query_top_errors(self, cfg, intent) -> dict:
        from app.config import settings

        body = {
            "size": 0,
            "query": {"bool": {"must": [
                {"range": {"@timestamp": {"gte": intent.time_range}}},
                {"terms": {"log.level.keyword": ["ERROR", "CRITICAL", "error", "critical"]}},
            ]}},
            "aggs": {
                "top_errors": {"terms": {"field": "message.keyword", "size": settings.es_agg_topk}},
            },
        }
        from app.providers.log_storage.elasticsearch import ElasticsearchProvider
        provider = ElasticsearchProvider(url=cfg.elasticsearch_url, api_key=cfg.elasticsearch_api_key)
        try:
            result = await provider.search(cfg.app_log_index, body, size=0)
            buckets = result.get("aggs", {}).get("top_errors", {}).get("buckets", [])
            return {"buckets": [{"payload": b["key"], "count": b["doc_count"]} for b in buckets]}
        except Exception as e:
            log.warning("top_errors_query_failed", error=str(e))
            return {"buckets": []}

    async def _query_prometheus(self, cfg, intent, servers) -> dict:
        import httpx
        results: dict = {}
        queries = {
            "cpu_pct": (
                'avg by(instance) (100 - (avg by(instance)'
                '(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100))'
            ),
            "ram_pct": (
                "100 * (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))"
            ),
            "disk_pct": (
                '100 * (1 - (node_filesystem_avail_bytes{mountpoint="/"}'
                ' / node_filesystem_size_bytes{mountpoint="/"}))'
            ),
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            for metric, q in queries.items():
                try:
                    resp = await client.get(
                        f"{cfg.prometheus_url}/api/v1/query",
                        params={"query": q},
                    )
                    resp.raise_for_status()
                    data = resp.json().get("data", {}).get("result", [])
                    results[metric] = {
                        r["metric"].get("instance", r["metric"].get("job", "unknown")): float(r["value"][1])
                        for r in data
                    }
                except Exception as e:
                    log.warning("prometheus_query_failed", metric=metric, error=str(e))
                    results[metric] = {}
        return results
