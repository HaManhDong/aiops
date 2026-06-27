from __future__ import annotations
import re
from dataclasses import dataclass
import structlog

log = structlog.get_logger()


@dataclass
class NoveltySignal:
    new_pattern: str
    similarity: float
    severity: str = "medium"


def _tokenize_error(text: str) -> set[str]:
    tokens = set(re.findall(r'[A-Za-z0-9_\-]+', text.lower()))
    stopwords = {"the", "a", "an", "in", "at", "of", "to", "error", "exception", "failed"}
    return tokens - stopwords


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def detect_novelty(
    current_errors: list[str],
    known_patterns: list[str],
) -> list[NoveltySignal]:
    from app.config import settings
    threshold = settings.prediction_novelty_jaccard_threshold
    signals = []
    for error in current_errors[:20]:
        tokens_cur = _tokenize_error(error)
        max_sim = max(
            (_jaccard(tokens_cur, _tokenize_error(p)) for p in known_patterns),
            default=0.0,
        )
        if max_sim < threshold:
            signals.append(NoveltySignal(
                new_pattern=error[:200],
                similarity=round(max_sim, 3),
            ))
    return signals
