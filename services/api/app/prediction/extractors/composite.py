from __future__ import annotations
from dataclasses import dataclass
import structlog

log = structlog.get_logger()


@dataclass
class CompositeSignal:
    signal_types: list[str]
    severity: str
    server_ip: str | None


def detect_composite(signals: list[dict], server_ip: str | None = None) -> CompositeSignal | None:
    from app.config import settings
    # Count distinct signal groups
    groups = set(s.get("signal_group", "?") for s in signals)
    if len(groups) >= settings.prediction_composite_min_signals:
        severity = "critical" if len(groups) >= 3 else "high"
        return CompositeSignal(
            signal_types=list(groups),
            severity=severity,
            server_ip=server_ip,
        )
    return None
