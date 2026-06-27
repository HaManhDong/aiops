from __future__ import annotations
import json
import structlog
from app.services.kibana_client import KibanaClient
from app.services.config_service import ConfigService

log = structlog.get_logger()

_CACHE_PREFIX = "kibana:alerts:"


class KibanaAlertClient:
    def __init__(self, config_svc: ConfigService):
        self._config_svc = config_svc

    async def get_alerts_for_app(self, app_id: str) -> list[dict]:
        from app.config import settings
        cache_key = f"{_CACHE_PREFIX}{app_id}"
        try:
            from app.redis_client import get_redis
            redis = await get_redis()
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

        try:
            cfg = await self._config_svc.get_datasource(app_id)
            if not cfg.kibana_url:
                return []
            client = KibanaClient(url=cfg.kibana_url, api_key=cfg.kibana_api_key)
            alerts = await client.get_active_alerts()
        except Exception as e:
            log.warning("kibana_alert_fetch_failed", app_id=app_id, error=str(e))
            return []

        try:
            from app.redis_client import get_redis
            redis = await get_redis()
            await redis.setex(cache_key, settings.kibana_alert_cache_ttl, json.dumps(alerts))
        except Exception:
            pass

        return alerts
