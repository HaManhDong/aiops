from __future__ import annotations
from dataclasses import dataclass
import re
import structlog

log = structlog.get_logger()


@dataclass
class RecurrenceSignal:
    matched_incident_id: str
    matched_title: str
    similarity: float
    solution: str | None
    severity: str = "medium"


def _tokenize(text: str) -> set[str]:
    stopwords = {"và", "hoặc", "là", "có", "the", "a", "an"}
    return set(re.findall(r'[A-Za-z0-9_À-ɏ]+', text.lower())) - stopwords


def _jaccard(a: set, b: set) -> float:
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def detect_recurrence(
    current_errors: list[str],
    past_incidents: list[dict],  # [{id, title, error_patterns, solution}]
) -> list[RecurrenceSignal]:
    from app.config import settings
    threshold = settings.prediction_recurrence_jaccard_threshold
    query_text = " ".join(current_errors[:10])
    query_tokens = _tokenize(query_text)
    signals = []
    for inc in past_incidents:
        pattern_text = " ".join(str(p) for p in (inc.get("error_patterns") or []))
        pattern_text += " " + (inc.get("title") or "")
        inc_tokens = _tokenize(pattern_text)
        sim = _jaccard(query_tokens, inc_tokens)
        if sim >= threshold:
            signals.append(RecurrenceSignal(
                matched_incident_id=inc["id"],
                matched_title=inc.get("title", "")[:100],
                similarity=round(sim, 3),
                solution=inc.get("solution"),
                severity="high" if sim >= 0.85 else "medium",
            ))
    return sorted(signals, key=lambda s: s.similarity, reverse=True)[:3]
