from __future__ import annotations
import asyncio
from dataclasses import dataclass
import structlog

log = structlog.get_logger()


@dataclass
class CapabilitySnapshot:
    app_id: str
    es_available: bool = False
    prometheus_available: bool = False
    kibana_available: bool = False
    has_servers: bool = False
    es_latency_ms: int = 0
    prometheus_latency_ms: int = 0


async def check_capabilities(app_id: str) -> CapabilitySnapshot:
    """C3: Runtime capability probe. Run before building context."""
    from app.services.service_probe import probe_http
    from app.services.config_service import ConfigService
    from app.database import get_db

    snap = CapabilitySnapshot(app_id=app_id)

    async for db in get_db():
        try:
            from app.agents.server_registry import ServerRegistryAgent, RegistryStatus
            cfg_svc = ConfigService(db)

            cfg = await cfg_svc.get_datasource(app_id)

            # Probe ES
            if cfg.elasticsearch_url:
                es_result = await probe_http(cfg.elasticsearch_url, "/_cluster/health")
                snap.es_available = es_result.reachable
                snap.es_latency_ms = es_result.latency_ms

            # Probe Prometheus
            if cfg.prometheus_url:
                prom_result = await probe_http(cfg.prometheus_url, "/-/healthy")
                snap.prometheus_available = prom_result.reachable
                snap.prometheus_latency_ms = prom_result.latency_ms

            # Check Kibana
            if cfg.kibana_url:
                kb_result = await probe_http(cfg.kibana_url, "/api/status")
                snap.kibana_available = kb_result.reachable

            # Check servers
            registry = ServerRegistryAgent(db)
            result = await registry.get_servers(app_id)
            snap.has_servers = result.status == RegistryStatus.FOUND

        except Exception as e:
            log.warning("capability_check_failed", app_id=app_id, error=str(e))
        break

    return snap
