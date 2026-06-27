from __future__ import annotations

import structlog
import redis.asyncio as aioredis
from redis.asyncio.sentinel import Sentinel

log = structlog.get_logger()

_client = None


def init_redis() -> None:
    global _client
    from app.config import settings

    if settings.redis_standalone_url:
        _client = aioredis.from_url(settings.redis_standalone_url, decode_responses=True)
        log.info("redis_standalone_mode", url=settings.redis_standalone_url.split("@")[-1])
    else:
        hosts = [
            (h.split(":")[0], int(h.split(":")[1]))
            for h in settings.redis_sentinel_hosts.split(",")
            if ":" in h
        ]
        sentinel = Sentinel(
            hosts,
            password=settings.redis_password or None,
            decode_responses=True,
        )
        _client = sentinel.master_for(settings.redis_sentinel_master)
        log.info("redis_sentinel_mode", master=settings.redis_sentinel_master, sentinels=len(hosts))


async def get_redis():
    assert _client is not None, "Redis not initialized — call init_redis() first"
    return _client
