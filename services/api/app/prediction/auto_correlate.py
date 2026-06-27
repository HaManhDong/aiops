from __future__ import annotations
import structlog
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()


async def auto_correlate_alerts(db: AsyncSession, app_id: str) -> int:
    """
    HIGH_RISK prediction alerts → check nếu incident được tạo sau đó trong 2h.
    Nếu có → đánh dấu is_true_positive = 1.
    Trả về số alerts được correlate.
    """
    window_start = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    result = await db.execute(
        text("""
            SELECT id, created_at FROM prediction_alerts
            WHERE app_id = :app_id
              AND severity IN ('critical', 'high')
              AND is_true_positive IS NULL
              AND created_at >= :start
        """),
        {"app_id": app_id, "start": window_start},
    )
    alerts = result.fetchall()
    if not alerts:
        return 0

    correlated = 0
    for alert_id, alert_time in alerts:
        inc_result = await db.execute(
            text("""
                SELECT id FROM incidents
                WHERE app_id = :app_id AND created_at >= :alert_time
                LIMIT 1
            """),
            {"app_id": app_id, "alert_time": alert_time},
        )
        if inc_result.fetchone():
            await db.execute(
                text("UPDATE prediction_alerts SET is_true_positive = 1 WHERE id = :id"),
                {"id": alert_id},
            )
            correlated += 1

    if correlated:
        await db.commit()
        log.info("auto_correlate_done", app_id=app_id, correlated=correlated)
    return correlated
