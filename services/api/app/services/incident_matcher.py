from __future__ import annotations
import re
from dataclasses import dataclass
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident

log = structlog.get_logger()


@dataclass
class SimilarIncident:
    id: str
    title: str
    severity: str
    status: str
    similarity: float
    solution: str | None
    resolved_at: str | None


def _tokenize(text: str) -> set[str]:
    """Tokenize text thành set of words (lowercase, remove stopwords)."""
    _STOPWORDS = {
        "và", "hoặc", "của", "trong", "với", "là", "có", "không", "được",
        "the", "a", "an", "is", "in",
    }
    tokens = set(re.findall(r'\w+', text.lower()))
    return tokens - _STOPWORDS


def jaccard_similarity(text_a: str, text_b: str) -> float:
    """Tính Jaccard similarity giữa 2 strings."""
    if not text_a or not text_b:
        return 0.0
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)
    if not tokens_a and not tokens_b:
        return 0.0
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return intersection / union if union > 0 else 0.0


class IncidentMatcher:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def find_similar(
        self,
        title: str,
        app_id: str,
        limit: int = 3,
        min_similarity: float = 0.25,
        include_resolved: bool = True,
    ) -> list[SimilarIncident]:
        """
        Tìm similar incidents dựa trên:
        1. app_id match (bắt buộc)
        2. Jaccard similarity trên title + description
        """
        stmt = select(Incident).where(Incident.app_id == app_id)
        if not include_resolved:
            stmt = stmt.where(Incident.status.in_(["open", "investigating"]))
        stmt = stmt.order_by(Incident.created_at.desc()).limit(50)

        rows = (await self._db.execute(stmt)).scalars().all()

        scored: list[tuple[float, Incident]] = []
        for row in rows:
            combined = f"{row.title} {row.description or ''}"
            sim = jaccard_similarity(title, combined)
            if sim >= min_similarity:
                scored.append((sim, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:limit]

        return [
            SimilarIncident(
                id=row.id,
                title=row.title,
                severity=row.severity,
                status=row.status,
                similarity=round(sim, 3),
                solution=row.solution,
                resolved_at=row.resolved_at.isoformat() if row.resolved_at else None,
            )
            for sim, row in top
        ]

    async def find_by_error_patterns(
        self, error_messages: list[str], app_id: str, limit: int = 3
    ) -> list[SimilarIncident]:
        """Tìm incidents có error_patterns match với error messages hiện tại."""
        if not error_messages:
            return []

        stmt = (
            select(Incident)
            .where(
                Incident.app_id == app_id,
                Incident.error_patterns.is_not(None),
                Incident.status == "resolved",
            )
            .order_by(Incident.resolved_at.desc())
            .limit(30)
        )
        rows = (await self._db.execute(stmt)).scalars().all()

        query_text = " ".join(error_messages[:5])
        scored = []
        for row in rows:
            patterns = row.error_patterns or []
            pattern_text = " ".join(str(p) for p in patterns)
            sim = jaccard_similarity(query_text, pattern_text)
            if sim >= 0.2:
                scored.append((sim, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            SimilarIncident(
                id=row.id,
                title=row.title,
                severity=row.severity,
                status=row.status,
                similarity=round(sim, 3),
                solution=row.solution,
                resolved_at=row.resolved_at.isoformat() if row.resolved_at else None,
            )
            for sim, row in scored[:limit]
        ]
