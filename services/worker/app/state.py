from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()


@dataclass
class CollectorState:
    app_id: str
    file_path: str
    last_byte: int
    file_size: int
    records_indexed: int


async def get_collector_state(
    db: AsyncSession, app_id: str, file_path: str
) -> CollectorState | None:
    result = await db.execute(
        text("""
            SELECT app_id, file_path, last_byte, file_size, records_indexed
            FROM collector_state
            WHERE app_id = :app_id AND file_path = :file_path
            LIMIT 1
        """),
        {"app_id": app_id, "file_path": file_path},
    )
    row = result.fetchone()
    if not row:
        return None
    return CollectorState(
        app_id=row[0], file_path=row[1],
        last_byte=row[2], file_size=row[3], records_indexed=row[4],
    )


async def upsert_collector_state(
    db: AsyncSession,
    app_id: str,
    file_path: str,
    last_byte: int,
    file_size: int,
    records_indexed: int,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    await db.execute(
        text("""
            INSERT INTO collector_state (id, app_id, file_path, last_byte, file_size, records_indexed, last_run_at)
            VALUES (UUID(), :app_id, :file_path, :last_byte, :file_size, :records_indexed, :now)
            ON DUPLICATE KEY UPDATE
                last_byte = :last_byte,
                file_size = :file_size,
                records_indexed = :records_indexed,
                last_run_at = :now
        """),
        {
            "app_id": app_id,
            "file_path": file_path[:255],
            "last_byte": last_byte,
            "file_size": file_size,
            "records_indexed": records_indexed,
            "now": now,
        },
    )
    await db.commit()


async def get_worker_config(db: AsyncSession, app_id: str) -> dict | None:
    result = await db.execute(
        text(
            "SELECT app_id, is_enabled, file_patterns, schedule_cron, batch_size "
            "FROM worker_configs WHERE app_id = :app_id"
        ),
        {"app_id": app_id},
    )
    row = result.fetchone()
    if not row:
        return None
    import json
    return {
        "app_id": row[0],
        "is_enabled": bool(row[1]),
        "file_patterns": json.loads(row[2]) if isinstance(row[2], str) else row[2],
        "schedule_cron": row[3],
        "batch_size": row[4],
    }
