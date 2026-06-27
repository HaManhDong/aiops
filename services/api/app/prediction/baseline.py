from __future__ import annotations
import math
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.prediction.context import BaselineData

log = structlog.get_logger()


def ewma_update(old_mean: float, new_value: float, alpha: float) -> float:
    """Exponential Moving Average update."""
    return alpha * new_value + (1 - alpha) * old_mean


def compute_stats(values: list[float]) -> tuple[float, float, float | None]:
    """Trả về (mean, std, p95) từ list of values — pure Python."""
    if not values:
        return 0.0, 0.0, None
    n = len(values)
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / n
    std = math.sqrt(variance)
    sorted_vals = sorted(values)
    p95_idx = int(0.95 * n)
    p95 = sorted_vals[min(p95_idx, n - 1)]
    return mean, std, p95


def z_score(value: float, mean: float, std: float) -> float:
    """Z-score. Trả về 0 nếu std = 0."""
    if std < 1e-9:
        return 0.0
    return (value - mean) / std


async def get_baseline(
    db: AsyncSession, app_id: str, metric_name: str, server_ip: str | None = None
) -> BaselineData | None:
    result = await db.execute(
        text("""
            SELECT mean_val, std_val, p95_val, sample_count, ewma_alpha
            FROM prediction_baselines
            WHERE app_id = :app_id AND metric_name = :metric_name
              AND (server_ip = :ip OR (server_ip IS NULL AND :ip IS NULL))
            LIMIT 1
        """),
        {"app_id": app_id, "metric_name": metric_name, "ip": server_ip},
    )
    row = result.fetchone()
    if not row:
        return None
    return BaselineData(
        mean=float(row[0]), std=float(row[1]),
        p95=float(row[2]) if row[2] is not None else None,
        sample_count=int(row[3]), ewma_alpha=float(row[4]),
    )


async def upsert_baseline(
    db: AsyncSession,
    app_id: str,
    metric_name: str,
    new_value: float,
    server_ip: str | None = None,
) -> BaselineData:
    from app.config import settings
    existing = await get_baseline(db, app_id, metric_name, server_ip)

    if existing and existing.sample_count >= 10:
        alpha = existing.ewma_alpha
        new_mean = ewma_update(existing.mean, new_value, alpha)
        new_std = math.sqrt(alpha * (new_value - new_mean) ** 2 + (1 - alpha) * existing.std ** 2)
        sample_count = existing.sample_count + 1
        p95 = existing.p95
    else:
        # Bootstrap — need at least a few values
        samples = [new_value]
        if existing:
            samples = [existing.mean] * min(existing.sample_count, 5) + [new_value]
        new_mean, new_std, p95 = compute_stats(samples)
        sample_count = len(samples)
        alpha = settings.prediction_ewma_alpha

    from datetime import datetime, timezone
    await db.execute(
        text("""
            INSERT INTO prediction_baselines
                (id, app_id, metric_name, server_ip, mean_val, std_val, p95_val, sample_count, ewma_alpha, computed_at)
            VALUES (UUID(), :app_id, :metric, :ip, :mean, :std, :p95, :count, :alpha, :now)
            ON DUPLICATE KEY UPDATE
                mean_val = :mean, std_val = :std, p95_val = :p95,
                sample_count = :count, computed_at = :now
        """),
        {
            "app_id": app_id, "metric": metric_name, "ip": server_ip,
            "mean": round(new_mean, 4), "std": round(new_std, 4),
            "p95": round(p95, 4) if p95 is not None else None,
            "count": sample_count, "alpha": alpha,
            "now": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        },
    )
    await db.commit()
    return BaselineData(mean=new_mean, std=new_std, p95=p95, sample_count=sample_count)
