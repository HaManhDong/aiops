from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class PredictionContext:
    app_id: str
    scan_id: str
    scan_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    servers: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)       # {ip: {cpu_pct, ram_pct, disk_pct}}
    log_stats: dict = field(default_factory=dict)     # {ip: {error_count, ...}}
    baselines: dict = field(default_factory=dict)     # {metric_key: BaselineData}
    data_quality: float = 0.0
    signals: list[dict] = field(default_factory=list)  # collected signals this scan


@dataclass
class BaselineData:
    mean: float
    std: float
    p95: float | None
    sample_count: int
    ewma_alpha: float = 0.3
