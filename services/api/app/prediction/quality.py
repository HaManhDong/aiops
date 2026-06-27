from __future__ import annotations
from dataclasses import dataclass
import structlog

log = structlog.get_logger()


@dataclass
class DataQualityMetrics:
    es_available: bool = False
    prometheus_available: bool = False
    server_count: int = 0
    metrics_coverage: float = 0.0  # fraction of servers with metrics

    def compute_score(self) -> float:
        """0.0 → 1.0. Minimum 0.40 để chạy scan."""
        score = 0.0
        if self.es_available:
            score += 0.40
        if self.prometheus_available:
            score += 0.30
        if self.server_count > 0:
            score += 0.20
        score += self.metrics_coverage * 0.10
        return round(min(score, 1.0), 4)

    def is_sufficient(self) -> bool:
        from app.config import settings
        return self.compute_score() >= settings.prediction_min_data_quality
