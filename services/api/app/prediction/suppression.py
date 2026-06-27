from __future__ import annotations
import hashlib
import structlog
from datetime import datetime, timezone

log = structlog.get_logger()

_SUPP_PREFIX = "pred:supp:"


def _supp_key(app_id: str, alert_type: str, server_ip: str | None) -> str:
    raw = f"{app_id}:{alert_type}:{server_ip or ''}"
    return _SUPP_PREFIX + hashlib.md5(raw.encode()).hexdigest()[:16]


async def is_suppressed(app_id: str, alert_type: str, server_ip: str | None = None) -> bool:
    try:
        from app.redis_client import get_redis
        redis = await get_redis()
        key = _supp_key(app_id, alert_type, server_ip)
        return await redis.exists(key) > 0
    except Exception as e:
        log.warning("suppression_check_failed", error=str(e))
        return False


async def suppress(app_id: str, alert_type: str, server_ip: str | None = None) -> None:
    from app.config import settings
    try:
        from app.redis_client import get_redis
        redis = await get_redis()
        key = _supp_key(app_id, alert_type, server_ip)
        await redis.setex(key, settings.prediction_suppression_window_s, "1")
    except Exception as e:
        log.warning("suppression_set_failed", error=str(e))
