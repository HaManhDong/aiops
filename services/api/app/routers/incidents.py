from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import CurrentUser, get_current_user
from app.models.incident import Incident, IncidentTimeline
from app.services.incident_matcher import IncidentMatcher
from app.services.audit import audit_log

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


# ── Pydantic Schemas ─────────────────────────────────────────────────

class IncidentCreate(BaseModel):
    app_id: str
    title: str
    severity: Literal["critical", "high", "medium", "low"] = "high"
    description: str | None = None
    root_cause: str | None = None
    affected_servers: list[str] | None = None
    related_logs: list[dict] | None = None
    error_patterns: list[str] | None = None
    source: Literal["manual", "chat_draft", "prediction"] = "manual"
    chat_session_id: str | None = None
    incident_time: str | None = None


class IncidentUpdate(BaseModel):
    title: str | None = None
    severity: Literal["critical", "high", "medium", "low"] | None = None
    status: Literal["open", "investigating", "resolved", "closed"] | None = None
    description: str | None = None
    root_cause: str | None = None
    solution: str | None = None
    assigned_to: str | None = None
    affected_servers: list[str] | None = None


class TimelineEntryCreate(BaseModel):
    action: str
    detail: str | None = None
    metadata: dict | None = None


class TimelineRead(BaseModel):
    id: str
    incident_id: str
    user_id: str | None
    action: str
    detail: str | None
    metadata: dict | None
    created_at: str


class IncidentRead(BaseModel):
    id: str
    app_id: str
    title: str
    severity: str
    status: str
    description: str | None
    root_cause: str | None
    solution: str | None
    related_logs: list | None
    error_patterns: list | None
    affected_servers: list | None
    source: str
    chat_session_id: str | None
    created_by: str | None
    assigned_to: str | None
    resolved_by: str | None
    solution_at: str | None
    incident_time: str | None
    resolved_at: str | None
    created_at: str
    updated_at: str


class IncidentPage(BaseModel):
    total: int
    items: list[IncidentRead]


class SimilarIncidentRead(BaseModel):
    id: str
    title: str
    severity: str
    status: str
    similarity: float
    solution: str | None
    resolved_at: str | None


# ── Helpers ──────────────────────────────────────────────────────────

def _to_read(row: Incident) -> IncidentRead:
    return IncidentRead(
        id=row.id,
        app_id=row.app_id,
        title=row.title,
        severity=row.severity,
        status=row.status,
        description=row.description,
        root_cause=row.root_cause,
        solution=row.solution,
        related_logs=row.related_logs,
        error_patterns=row.error_patterns,
        affected_servers=row.affected_servers,
        source=row.source,
        chat_session_id=row.chat_session_id,
        created_by=row.created_by,
        assigned_to=row.assigned_to,
        resolved_by=row.resolved_by,
        solution_at=row.solution_at.isoformat() if row.solution_at else None,
        incident_time=row.incident_time.isoformat() if row.incident_time else None,
        resolved_at=row.resolved_at.isoformat() if row.resolved_at else None,
        created_at=row.created_at.isoformat() if row.created_at else "",
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
    )


async def _add_timeline(
    db: AsyncSession,
    incident_id: str,
    user_id: str | None,
    action: str,
    detail: str | None = None,
    metadata: dict | None = None,
) -> None:
    entry = IncidentTimeline(
        incident_id=incident_id,
        user_id=user_id,
        action=action,
        detail=detail,
        metadata_=metadata,
    )
    db.add(entry)


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("", response_model=IncidentPage)
async def list_incidents(
    app_id: str | None = Query(None),
    status: str | None = Query(None),
    severity: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Incident)
    count_stmt = select(func.count()).select_from(Incident)

    # app_id access check
    if app_id:
        if not current_user.can_access(app_id):
            raise HTTPException(status_code=403, detail={"title": "Không có quyền truy cập app_id này"})
        stmt = stmt.where(Incident.app_id == app_id)
        count_stmt = count_stmt.where(Incident.app_id == app_id)
    else:
        # Filter theo allowed_apps
        if "all" not in current_user.allowed_apps:
            stmt = stmt.where(Incident.app_id.in_(current_user.allowed_apps))
            count_stmt = count_stmt.where(Incident.app_id.in_(current_user.allowed_apps))

    if status:
        stmt = stmt.where(Incident.status == status)
        count_stmt = count_stmt.where(Incident.status == status)
    if severity:
        stmt = stmt.where(Incident.severity == severity)
        count_stmt = count_stmt.where(Incident.severity == severity)

    total = (await db.execute(count_stmt)).scalar_one()
    rows = (
        await db.execute(
            stmt.order_by(Incident.created_at.desc()).offset(offset).limit(limit)
        )
    ).scalars().all()

    return IncidentPage(total=total, items=[_to_read(r) for r in rows])


@router.post("", response_model=IncidentRead, status_code=201)
async def create_incident(
    body: IncidentCreate,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.can_access(body.app_id):
        raise HTTPException(status_code=403, detail={"title": "Không có quyền truy cập app_id này"})

    incident_time = None
    if body.incident_time:
        try:
            incident_time = datetime.fromisoformat(body.incident_time.replace("Z", "+00:00"))
        except ValueError:
            incident_time = datetime.now(timezone.utc)

    row = Incident(
        app_id=body.app_id,
        title=body.title,
        severity=body.severity,
        description=body.description,
        root_cause=body.root_cause,
        affected_servers=body.affected_servers,
        related_logs=body.related_logs,
        error_patterns=body.error_patterns,
        source=body.source,
        chat_session_id=body.chat_session_id,
        created_by=current_user.user_id,
        incident_time=incident_time or datetime.now(timezone.utc),
    )
    db.add(row)
    await db.flush()

    await _add_timeline(db, row.id, current_user.user_id, "CREATED", f"Incident tạo bởi {current_user.username}")

    ip = request.client.host if request.client else None
    await audit_log(
        db=db,
        user_id=current_user.user_id,
        action="CREATE_INCIDENT",
        entity_type="incidents",
        entity_id=row.id,
        new_value={"title": row.title, "app_id": row.app_id, "severity": row.severity},
        ip=ip,
    )
    await db.commit()
    await db.refresh(row)
    log.info("incident_created", id=row.id, app_id=row.app_id, by=current_user.username)
    return _to_read(row)


@router.get("/{incident_id}", response_model=IncidentRead)
async def get_incident(
    incident_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(Incident, incident_id)
    if not row:
        raise HTTPException(status_code=404, detail={"title": "Incident không tồn tại"})
    if not current_user.can_access(row.app_id):
        raise HTTPException(status_code=403, detail={"title": "Không có quyền"})
    return _to_read(row)


@router.patch("/{incident_id}", response_model=IncidentRead)
async def update_incident(
    incident_id: str,
    body: IncidentUpdate,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(Incident, incident_id)
    if not row:
        raise HTTPException(status_code=404, detail={"title": "Incident không tồn tại"})
    if not current_user.can_access(row.app_id):
        raise HTTPException(status_code=403, detail={"title": "Không có quyền"})

    old = {"status": row.status, "severity": row.severity}
    changes = []

    if body.title is not None:
        row.title = body.title
        changes.append("title")
    if body.severity is not None:
        row.severity = body.severity
        changes.append(f"severity→{body.severity}")
    if body.description is not None:
        row.description = body.description
    if body.root_cause is not None:
        row.root_cause = body.root_cause
        changes.append("root_cause")
    if body.assigned_to is not None:
        row.assigned_to = body.assigned_to
        changes.append(f"assigned→{body.assigned_to}")
    if body.affected_servers is not None:
        row.affected_servers = body.affected_servers

    # Status transition
    if body.status is not None and body.status != row.status:
        prev_status = row.status
        row.status = body.status
        changes.append(f"status {prev_status}→{body.status}")

        if body.status == "resolved":
            # Guard: phải có solution trước khi resolve
            if body.solution:
                row.solution = body.solution
                row.solution_at = datetime.now(timezone.utc)
                row.solution_by = current_user.user_id
            elif not row.solution:
                raise HTTPException(
                    status_code=422,
                    detail={"title": "Phải điền solution trước khi resolve incident"},
                )
            row.resolved_at = datetime.now(timezone.utc)
            row.resolved_by = current_user.user_id
        elif body.status == "closed" and not row.resolved_at:
            row.resolved_at = datetime.now(timezone.utc)
            row.resolved_by = current_user.user_id

    if body.solution is not None and body.status != "resolved":
        row.solution = body.solution
        changes.append("solution")

    if changes:
        await _add_timeline(
            db, incident_id, current_user.user_id,
            "UPDATED", f"Thay đổi: {', '.join(changes)}"
        )
        ip = request.client.host if request.client else None
        await audit_log(
            db=db,
            user_id=current_user.user_id,
            action="UPDATE_INCIDENT",
            entity_type="incidents",
            entity_id=incident_id,
            old_value=old,
            new_value={"status": row.status, "severity": row.severity},
            ip=ip,
        )

    await db.commit()
    await db.refresh(row)
    return _to_read(row)


@router.delete("/{incident_id}", status_code=204)
async def delete_incident(
    incident_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Chỉ admin mới xóa được
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail={"title": "Chỉ admin mới có thể xóa incident"})

    row = await db.get(Incident, incident_id)
    if not row:
        raise HTTPException(status_code=404, detail={"title": "Incident không tồn tại"})

    ip = request.client.host if request.client else None
    await audit_log(
        db=db,
        user_id=current_user.user_id,
        action="DELETE_INCIDENT",
        entity_type="incidents",
        entity_id=incident_id,
        old_value={"title": row.title, "app_id": row.app_id},
        ip=ip,
    )
    await db.delete(row)
    await db.commit()


# ── Timeline ─────────────────────────────────────────────────────────

@router.get("/{incident_id}/timeline", response_model=list[TimelineRead])
async def get_timeline(
    incident_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(Incident, incident_id)
    if not row:
        raise HTTPException(status_code=404, detail={"title": "Incident không tồn tại"})
    if not current_user.can_access(row.app_id):
        raise HTTPException(status_code=403, detail={"title": "Không có quyền"})

    entries = (
        await db.execute(
            select(IncidentTimeline)
            .where(IncidentTimeline.incident_id == incident_id)
            .order_by(IncidentTimeline.created_at)
        )
    ).scalars().all()

    return [
        TimelineRead(
            id=e.id,
            incident_id=e.incident_id,
            user_id=e.user_id,
            action=e.action,
            detail=e.detail,
            metadata=e.metadata_,
            created_at=e.created_at.isoformat() if e.created_at else "",
        )
        for e in entries
    ]


@router.post("/{incident_id}/timeline", response_model=TimelineRead, status_code=201)
async def add_timeline_entry(
    incident_id: str,
    body: TimelineEntryCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(Incident, incident_id)
    if not row:
        raise HTTPException(status_code=404, detail={"title": "Incident không tồn tại"})
    if not current_user.can_access(row.app_id):
        raise HTTPException(status_code=403, detail={"title": "Không có quyền"})

    entry = IncidentTimeline(
        incident_id=incident_id,
        user_id=current_user.user_id,
        action=body.action,
        detail=body.detail,
        metadata_=body.metadata,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    return TimelineRead(
        id=entry.id,
        incident_id=entry.incident_id,
        user_id=entry.user_id,
        action=entry.action,
        detail=entry.detail,
        metadata=entry.metadata_,
        created_at=entry.created_at.isoformat() if entry.created_at else "",
    )


# ── Similar Incidents ─────────────────────────────────────────────────

@router.get("/{incident_id}/similar", response_model=list[SimilarIncidentRead])
async def find_similar_incidents(
    incident_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(Incident, incident_id)
    if not row:
        raise HTTPException(status_code=404, detail={"title": "Incident không tồn tại"})
    if not current_user.can_access(row.app_id):
        raise HTTPException(status_code=403, detail={"title": "Không có quyền"})

    matcher = IncidentMatcher(db)
    similar = await matcher.find_similar(
        title=f"{row.title} {row.description or ''}",
        app_id=row.app_id,
        limit=5,
    )
    # Exclude self
    similar = [s for s in similar if s.id != incident_id]

    return [
        SimilarIncidentRead(
            id=s.id,
            title=s.title,
            severity=s.severity,
            status=s.status,
            similarity=s.similarity,
            solution=s.solution,
            resolved_at=s.resolved_at,
        )
        for s in similar
    ]


@router.post("/search/similar", response_model=list[SimilarIncidentRead])
async def search_similar_by_text(
    body: dict,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Tìm similar incidents theo title text (dùng khi chat tạo incident_draft).
    Body: {"title": "...", "app_id": "...", "error_messages": [...]}
    """
    title = body.get("title", "")
    app_id = body.get("app_id", "")
    error_messages = body.get("error_messages", [])

    if not title or not app_id:
        raise HTTPException(status_code=422, detail={"title": "Cần title và app_id"})
    if not current_user.can_access(app_id):
        raise HTTPException(status_code=403, detail={"title": "Không có quyền"})

    matcher = IncidentMatcher(db)
    by_title = await matcher.find_similar(title=title, app_id=app_id, limit=3)
    by_patterns = await matcher.find_by_error_patterns(error_messages, app_id, limit=2)

    # Merge + deduplicate
    seen: set[str] = set()
    results = []
    for s in by_title + by_patterns:
        if s.id not in seen:
            seen.add(s.id)
            results.append(s)

    results.sort(key=lambda x: x.similarity, reverse=True)
    return [
        SimilarIncidentRead(
            id=s.id, title=s.title, severity=s.severity, status=s.status,
            similarity=s.similarity, solution=s.solution, resolved_at=s.resolved_at,
        )
        for s in results[:5]
    ]
