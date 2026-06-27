from __future__ import annotations
import math
from dataclasses import dataclass
import structlog

log = structlog.get_logger()


@dataclass
class DriftSignal:
    metric: str
    server_ip: str | None
    variance_ratio: float
    severity: str = "medium"


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((x - mean) ** 2 for x in values) / len(values)


def detect_drift(
    metric: str,
    recent_values: list[float],    # last N values
    baseline_values: list[float],  # historical N values
    server_ip: str | None = None,
) -> DriftSignal | None:
    if len(recent_values) < 4 or len(baseline_values) < 4:
        return None
    recent_var = _variance(recent_values)
    baseline_var = _variance(baseline_values)
    if baseline_var < 1e-6:
        return None
    ratio = recent_var / baseline_var
    if ratio >= 3.0:
        severity = "high" if ratio >= 5.0 else "medium"
        return DriftSignal(metric=metric, server_ip=server_ip,
                           variance_ratio=round(ratio, 2), severity=severity)
    return None
