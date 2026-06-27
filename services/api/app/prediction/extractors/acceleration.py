from __future__ import annotations
from dataclasses import dataclass
import structlog

log = structlog.get_logger()


@dataclass
class AccelerationSignal:
    metric: str
    server_ip: str
    slope_per_hour: float
    current_value: float
    severity: str


def detect_acceleration(
    metric: str,
    timestamps: list[float],
    values: list[float],
    server_ip: str,
) -> AccelerationSignal | None:
    from app.config import settings
    from app.prediction.extractors.capacity import _ols
    if len(timestamps) < 4:
        return None

    t0 = timestamps[0]
    x = [(t - t0) / 3600.0 for t in timestamps]
    slope, _, r2 = _ols(x, values)

    if r2 < 0.5 or slope <= 0:
        return None

    threshold = settings.prediction_acceleration_slope_warn
    if slope < threshold:
        return None

    severity = "high" if slope >= threshold * 2 else "medium"
    return AccelerationSignal(
        metric=metric, server_ip=server_ip,
        slope_per_hour=round(slope, 4),
        current_value=round(values[-1], 2),
        severity=severity,
    )
