from __future__ import annotations
import os
import asyncio
import json
from contextlib import asynccontextmanager
import structlog
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

log = structlog.get_logger()

# DB connection URL from environment variables
_DB_URL = (
    f"mysql+asyncmy://{os.getenv('MARIADB_USER', 'vst')}:{os.getenv('MARIADB_PASSWORD', 'vst')}"
    f"@{os.getenv('MARIADB_HOST', 'mariadb')}:{os.getenv('MARIADB_PORT', '3306')}"
    f"/{os.getenv('MARIADB_DB', 'aiops')}"
)

_engine = create_async_engine(_DB_URL, pool_pre_ping=True)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)

_scheduler: AsyncIOScheduler | None = None


async def _run_collection_cycle() -> None:
    """Main collection job — runs all enabled app_ids."""
    from app.collector import run_collection_for_app

    async with _session_factory() as db:
        try:
            # Get all datasource configs that have txt_watch_dirs
            result = await db.execute(
                text(
                    "SELECT app_id, elasticsearch_url, elasticsearch_api_key, app_log_index, txt_watch_dirs "
                    "FROM datasource_configs "
                    "WHERE txt_watch_dirs IS NOT NULL AND txt_watch_dirs != 'null' AND is_active = 1"
                )
            )
            rows = result.fetchall()

            # Get error patterns
            patterns_result = await db.execute(
                text(
                    "SELECT pattern, error_type, severity FROM error_classifier_patterns "
                    "WHERE is_active = 1 ORDER BY priority ASC"
                )
            )
            patterns = [
                {"pattern": r[0], "error_type": r[1], "severity": r[2]}
                for r in patterns_result.fetchall()
            ]

            for row in rows:
                app_id, es_url, es_key, log_index, watch_dirs_raw = row
                try:
                    watch_dirs = json.loads(watch_dirs_raw) if isinstance(watch_dirs_raw, str) else watch_dirs_raw
                except Exception:
                    watch_dirs = []

                if not watch_dirs:
                    continue

                cfg = {
                    "elasticsearch_url": es_url,
                    "elasticsearch_api_key": es_key,
                    "app_log_index": log_index or f"aiops-txt-logs-{app_id}",
                    "txt_watch_dirs": watch_dirs,
                }
                try:
                    summary = await run_collection_for_app(app_id, db, cfg, patterns)
                    log.info("app_collection_done", app_id=app_id, **summary)
                except Exception as e:
                    log.error("app_collection_error", app_id=app_id, error=str(e))

        except Exception as e:
            log.error("collection_cycle_error", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    structlog.configure(processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.JSONRenderer(),
    ])

    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _run_collection_cycle,
        "cron",
        minute="*/5",
        id="txt_collection",
        replace_existing=True,
    )
    _scheduler.start()
    log.info("worker_started", schedule="*/5 * * * *")
    yield
    _scheduler.shutdown(wait=False)
    log.info("worker_stopped")


app = FastAPI(title="TXT Log Collector Worker", lifespan=lifespan)


@app.get("/")
async def health():
    return {
        "status": "ok",
        "scheduler_running": _scheduler.running if _scheduler else False,
    }


@app.post("/run-now")
async def run_now():
    """Trigger manual collection run (for testing/admin)."""
    asyncio.create_task(_run_collection_cycle())
    return {"triggered": True}
