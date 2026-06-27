from __future__ import annotations
from dataclasses import dataclass
import structlog

log = structlog.get_logger()


@dataclass
class CapacityForecast:
    metric: str
    server_ip: str
    current_value: float
    slope_per_hour: float
    r_squared: float
    hours_until_full: float | None
    severity: str  # critical | high | medium | none


def _ols(x: list[float], y: list[float]) -> tuple[float, float, float]:
    """OLS linear regression: y = slope*x + intercept. Trả về (slope, intercept, r2)."""
    n = len(x)
    if n < 3:
        return 0.0, 0.0, 0.0
    sum_x = sum(x)
    sum_y = sum(y)
    sum_xy = sum(xi * yi for xi, yi in zip(x, y))
    sum_x2 = sum(xi ** 2 for xi in x)
    denom = n * sum_x2 - sum_x ** 2
    if abs(denom) < 1e-10:
        return 0.0, sum_y / n, 0.0
    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    # R²
    y_mean = sum_y / n
    ss_tot = sum((yi - y_mean) ** 2 for yi in y)
    ss_res = sum((yi - (slope * xi + intercept)) ** 2 for xi, yi in zip(x, y))
    r2 = 1 - ss_res / ss_tot if ss_tot > 1e-10 else 0.0
    return slope, intercept, r2


def forecast_capacity(
    timestamps: list[float],  # Unix timestamps
    values: list[float],      # metric values (0-100%)
    metric: str,
    server_ip: str,
) -> CapacityForecast | None:
    """
    Dự báo khi metric đạt 95% (ngưỡng đầy).
    Trả về None nếu không đủ dữ liệu hoặc slope <= 0.
    """
    from app.config import settings
    if len(timestamps) < 6:
        return None

    # Normalize time to hours from first point
    t0 = timestamps[0]
    x = [(t - t0) / 3600.0 for t in timestamps]

    slope, intercept, r2 = _ols(x, values)

    if r2 < settings.prediction_capacity_r2_min or slope <= 0:
        return None  # Trend không đủ rõ hoặc không tăng

    current = values[-1]
    current_x = x[-1]
    # Tính thời gian để đạt 95%
    if current >= 95.0:
        hours_until_full = 0.0
    else:
        hours_until_full = (95.0 - (slope * current_x + intercept)) / slope
        if hours_until_full < 0:
            hours_until_full = 0.0

    days = hours_until_full / 24.0
    if days <= settings.prediction_capacity_days_crit:
        severity = "critical"
    elif days <= settings.prediction_capacity_days_high:
        severity = "high"
    elif days <= settings.prediction_capacity_days_med:
        severity = "medium"
    else:
        return None  # Còn xa, không cần cảnh báo

    return CapacityForecast(
        metric=metric, server_ip=server_ip,
        current_value=round(current, 2),
        slope_per_hour=round(slope, 4),
        r_squared=round(r2, 4),
        hours_until_full=round(hours_until_full, 1),
        severity=severity,
    )
