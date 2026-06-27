from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import CurrentUser, require_admin
from app.models.audit import AuditLog

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/admin", tags=["admin-audit"])


class AuditLogRead(BaseModel):
    id: str
    user_id: str | None
    action: str
    entity_type: str
    entity_id: str | None
    old_value: dict | None
    new_value: dict | None
    ip_address: str | None
    created_at: str

    model_config = {"from_attributes": True}


class AuditLogPage(BaseModel):
    total: int
    items: list[AuditLogRead]


@router.get("/audit-logs", response_model=AuditLogPage)
async def list_audit_logs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    entity_type: str | None = Query(None),
    user_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
):
    stmt = select(AuditLog)
    count_stmt = select(func.count()).select_from(AuditLog)

    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
        count_stmt = count_stmt.where(AuditLog.entity_type == entity_type)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
        count_stmt = count_stmt.where(AuditLog.user_id == user_id)

    total = (await db.execute(count_stmt)).scalar_one()
    rows = (
        await db.execute(stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit))
    ).scalars().all()

    items = [
        AuditLogRead(
            id=r.id,
            user_id=r.user_id,
            action=r.action,
            entity_type=r.entity_type,
            entity_id=r.entity_id,
            old_value=r.old_value,
            new_value=r.new_value,
            ip_address=r.ip_address,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]
    return AuditLogPage(total=total, items=items)
