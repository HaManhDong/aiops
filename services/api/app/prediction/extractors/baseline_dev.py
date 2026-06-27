from __future__ import annotations
from dataclasses import dataclass
import structlog
from app.prediction.baseline import z_score

log = structlog.get_logger()


@dataclass
class BaselineDeviation:
    metric: str
    server_ip: str | None
    current_value: float
    baseline_mean: float
    baseline_std: float
    z_score_val: float
    severity: str


def detect_baseline_deviation(
    metric: str,
    current_value: float,
    baseline_mean: float,
    baseline_std: float,
    server_ip: str | None = None,
) -> BaselineDeviation | None:
    from app.config import settings
    z = z_score(current_value, baseline_mean, baseline_std)
    abs_z = abs(z)

    if abs_z >= settings.prediction_zscore_crit:
        severity = "critical"
    elif abs_z >= settings.prediction_zscore_warn:
        severity = "high"
    else:
        return None

    # Only alert on upward deviation for resource metrics
    if z <= 0 and metric in ("cpu_pct", "ram_pct", "disk_pct", "error_count"):
        return None

    return BaselineDeviation(
        metric=metric, server_ip=server_ip,
        current_value=round(current_value, 2),
        baseline_mean=round(baseline_mean, 2),
        baseline_std=round(baseline_std, 2),
        z_score_val=round(z, 3),
        severity=severity,
    )
