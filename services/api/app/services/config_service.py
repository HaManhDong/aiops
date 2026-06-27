"""
ConfigService: lấy datasource config từ MariaDB, cache trong Redis (TTL 60s).
Cache key: config:datasource:{app_id}
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import structlog
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

log = structlog.get_logger()

_CACHE_TTL = 60
_CACHE_PREFIX = "config:datasource:"


@dataclass
class DatasourceSettings:
    app_id: str
    display_name: str
    elasticsearch_url: str
    elasticsearch_api_key: str | None
    app_log_index: str
    syslog_index: str
    prometheus_url: str | None
    prometheus_extra_labels: dict | None
    kibana_url: str | None
    kibana_api_key: str | None
    alert_thresholds: dict[str, Any]
    txt_watch_dirs: list[str]
    log_provider: str
    metrics_provider: str


@dataclass
class AppThresholds:
    cpu_pct: int = 85
    ram_pct: int = 90
    disk_pct: int = 85
    error_count_1h: int = 10
    error_count_critical_1h: int = 3
    connection_timeout_1h: int = 10
    oracle_deadlock_1h: int = 3
    smtp_error_30m: int = 5

    @classmethod
    def from_service(cls, cfg: DatasourceSettings) -> AppThresholds:
        t = cfg.alert_thresholds or {}
        return cls(
            cpu_pct=t.get("cpu_pct", 85),
            ram_pct=t.get("ram_pct", 90),
            disk_pct=t.get("disk_pct", 85),
            error_count_1h=t.get("error_count_1h", 10),
            error_count_critical_1h=t.get("error_count_critical_1h", 3),
            connection_timeout_1h=t.get("connection_timeout_1h", 10),
            oracle_deadlock_1h=t.get("oracle_deadlock_1h", 3),
            smtp_error_30m=t.get("smtp_error_30m", 5),
        )


def _decrypt_safe(value: str | None) -> str | None:
    if not value:
        return None
    try:
        from app.services.encryption import decrypt
        return decrypt(value)
    except Exception:
        return None


class ConfigService:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def get_datasource(self, app_id: str) -> DatasourceSettings:
        """
        Lấy config datasource. Redis cache → fallback MariaDB.

        QUAN TRỌNG: dùng select().where(app_id==...) không dùng db.get()
        vì PK là UUID id, không phải app_id.

        Raises:
            ValueError: app_id không tồn tại hoặc inactive
        """
        from app.models.config import DatasourceConfig

        cache_key = f"{_CACHE_PREFIX}{app_id}"

        # 1. Redis cache
        try:
            from app.redis_client import get_redis
            redis = await get_redis()
            cached = await redis.get(cache_key)
            if cached:
                log.debug("config_cache_hit", app_id=app_id)
                return DatasourceSettings(**json.loads(cached))
        except Exception as e:
            log.warning("config_cache_unavailable", app_id=app_id, error=str(e))

        # 2. MariaDB — phải dùng WHERE app_id
        row = (
            await self._db.execute(
                select(DatasourceConfig).where(
                    DatasourceConfig.app_id == app_id,
                    DatasourceConfig.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()

        if not row:
            raise ValueError(f"Datasource '{app_id}' không tồn tại hoặc đã bị vô hiệu hóa")

        ds = DatasourceSettings(
            app_id=row.app_id,
            display_name=row.display_name,
            elasticsearch_url=row.elasticsearch_url,
            elasticsearch_api_key=_decrypt_safe(row.elasticsearch_api_key),
            app_log_index=row.app_log_index,
            syslog_index=row.syslog_index,
            prometheus_url=row.prometheus_url,
            prometheus_extra_labels=row.prometheus_extra_labels,
            kibana_url=row.kibana_url,
            kibana_api_key=_decrypt_safe(row.kibana_api_key),
            alert_thresholds=row.alert_thresholds or {},
            txt_watch_dirs=row.txt_watch_dirs or [],
            log_provider=row.log_provider,
            metrics_provider=row.metrics_provider,
        )

        # 3. Write cache — best-effort
        try:
            from app.redis_client import get_redis
            redis = await get_redis()
            await redis.setex(cache_key, _CACHE_TTL, json.dumps(ds.__dict__))
        except Exception as e:
            log.warning("config_cache_write_failed", app_id=app_id, error=str(e))

        return ds

    async def list_datasources(self) -> list[DatasourceSettings]:
        from app.models.config import DatasourceConfig

        rows = (
            await self._db.execute(
                select(DatasourceConfig).where(DatasourceConfig.is_active.is_(True))
            )
        ).scalars().all()

        return [
            DatasourceSettings(
                app_id=r.app_id,
                display_name=r.display_name,
                elasticsearch_url=r.elasticsearch_url,
                elasticsearch_api_key=None,  # không expose key khi list
                app_log_index=r.app_log_index,
                syslog_index=r.syslog_index,
                prometheus_url=r.prometheus_url,
                prometheus_extra_labels=r.prometheus_extra_labels,
                kibana_url=r.kibana_url,
                kibana_api_key=None,
                alert_thresholds=r.alert_thresholds or {},
                txt_watch_dirs=r.txt_watch_dirs or [],
                log_provider=r.log_provider,
                metrics_provider=r.metrics_provider,
            )
            for r in rows
        ]

    async def invalidate_cache(self, app_id: str) -> None:
        try:
            from app.redis_client import get_redis
            redis = await get_redis()
            await redis.delete(f"{_CACHE_PREFIX}{app_id}")
            log.info("config_cache_invalidated", app_id=app_id)
        except Exception as e:
            log.warning("config_cache_invalidate_failed", app_id=app_id, error=str(e))


# FastAPI dependency — PHẢI có Depends(get_db)
async def get_config_service(db: AsyncSession = Depends(get_db)) -> ConfigService:
    return ConfigService(db)
