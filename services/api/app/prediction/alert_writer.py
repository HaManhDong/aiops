from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.prediction.suppression import is_suppressed, suppress

log = structlog.get_logger()


async def write_alert(
    db: AsyncSession,
    *,
    app_id: str,
    server_ip: str | None,
    alert_type: str,
    signal_group: str,
    severity: str,
    title: str,
    explanation: str,
    metric_name: str | None = None,
    current_value: float | None = None,
    baseline_value: float | None = None,
    confidence: float = 0.5,
    evidence: dict | None = None,
) -> str | None:
    """
    Ghi alert mới. Kiểm tra suppression trước.
    Trả về alert_id nếu ghi thành công, None nếu bị suppress.
    """
    if await is_suppressed(app_id, alert_type, server_ip):
        log.debug("alert_suppressed", app_id=app_id, type=alert_type, ip=server_ip)
        return None

    alert_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")

    await db.execute(
        text("""
            INSERT INTO prediction_alerts
                (id, app_id, server_ip, alert_type, signal_group, severity, status,
                 title, explanation, metric_name, current_value, baseline_value,
                 confidence, evidence, predicted_at, created_at, updated_at)
            VALUES
                (:id, :app_id, :ip, :type, :group, :sev, 'open',
                 :title, :expl, :metric, :cur, :base,
                 :conf, :ev, :now, :now, :now)
        """),
        {
            "id": alert_id, "app_id": app_id, "ip": server_ip,
            "type": alert_type, "group": signal_group, "sev": severity,
            "title": title[:255], "expl": explanation[:2000],
            "metric": metric_name, "cur": current_value, "base": baseline_value,
            "conf": confidence, "ev": json.dumps(evidence or {}, ensure_ascii=False),
            "now": now,
        },
    )
    await db.commit()

    await suppress(app_id, alert_type, server_ip)
    log.info("prediction_alert_created", id=alert_id, app_id=app_id, type=alert_type, severity=severity)
    return alert_id


async def write_scan(
    db: AsyncSession,
    *,
    app_id: str,
    duration_ms: int,
    alerts_created: int,
    signals_found: int,
    data_quality: float,
    error_message: str | None = None,
) -> None:
    await db.execute(
        text("""
            INSERT INTO prediction_scans
                (id, app_id, scan_at, duration_ms, alerts_created, signals_found, data_quality, error_message)
            VALUES (UUID(), :app_id, NOW(6), :dur, :alerts, :signals, :quality, :err)
        """),
        {
            "app_id": app_id, "dur": duration_ms,
            "alerts": alerts_created, "signals": signals_found,
            "quality": data_quality, "err": error_message,
        },
    )
    await db.commit()
