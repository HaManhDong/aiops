from __future__ import annotations

from typing import Literal
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import CurrentUser, get_current_user
from app.models.notification import NotificationConfig, NotificationLog
from app.services.audit import audit_log

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


# ── Schemas ──────────────────────────────────────────────────────────

class NotificationConfigCreate(BaseModel):
    name: str
    app_id: str | None = None
    channel: Literal["email", "telegram"]
    schedule_cron: str = "0 8 * * *"
    is_enabled: bool = True
    recipients: list[str]
    report_window_hours: int = 24


class NotificationConfigUpdate(BaseModel):
    name: str | None = None
    app_id: str | None = None
    channel: Literal["email", "telegram"] | None = None
    schedule_cron: str | None = None
    is_enabled: bool | None = None
    recipients: list[str] | None = None
    report_window_hours: int | None = None


class NotificationConfigRead(BaseModel):
    id: str
    name: str
    app_id: str | None
    channel: str
    schedule_cron: str
    is_enabled: bool
    recipients: list[str]
    report_window_hours: int
    created_by: str | None
    created_at: str
    updated_at: str


class NotificationLogRead(BaseModel):
    id: str
    config_id: str
    channel: str
    status: str
    recipients_count: int
    error_message: str | None
    sent_at: str


def _to_read(row: NotificationConfig) -> NotificationConfigRead:
    return NotificationConfigRead(
        id=row.id,
        name=row.name,
        app_id=row.app_id,
        channel=row.channel,
        schedule_cron=row.schedule_cron,
        is_enabled=row.is_enabled,
        recipients=row.recipients or [],
        report_window_hours=row.report_window_hours,
        created_by=row.created_by,
        created_at=row.created_at.isoformat() if row.created_at else "",
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
    )


def _get_scheduler():
    """Lazy accessor — lấy scheduler từ app state."""
    from app.main import app
    return getattr(app.state, "scheduler", None)


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("", response_model=list[NotificationConfigRead])
async def list_configs(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail={"title": "Chỉ admin mới xem được"})

    rows = (
        await db.execute(
            select(NotificationConfig).order_by(NotificationConfig.created_at.desc())
        )
    ).scalars().all()
    return [_to_read(r) for r in rows]


@router.post("", response_model=NotificationConfigRead, status_code=201)
async def create_config(
    body: NotificationConfigCreate,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail={"title": "Chỉ admin mới tạo được"})

    if not body.recipients:
        raise HTTPException(
            status_code=422, detail={"title": "Cần ít nhất 1 recipient"}
        )

    row = NotificationConfig(
        name=body.name,
        app_id=body.app_id,
        channel=body.channel,
        schedule_cron=body.schedule_cron,
        is_enabled=body.is_enabled,
        recipients=body.recipients,
        report_window_hours=body.report_window_hours,
        created_by=current_user.user_id,
    )
    db.add(row)
    await db.flush()

    ip = request.client.host if request.client else None
    await audit_log(
        db=db,
        user_id=current_user.user_id,
        action="CREATE_NOTIFICATION_CONFIG",
        entity_type="notification_configs",
        entity_id=row.id,
        new_value={"name": row.name, "channel": row.channel, "cron": row.schedule_cron},
        ip=ip,
    )
    await db.commit()
    await db.refresh(row)

    # Đăng ký job vào scheduler ngay sau khi tạo
    scheduler = _get_scheduler()
    if scheduler and row.is_enabled:
        from app.notifications.scheduler import _register_job
        _register_job(scheduler, row.id, row.schedule_cron, row.channel)

    log.info("notification_config_created", id=row.id, channel=row.channel)
    return _to_read(row)


@router.get("/{config_id}", response_model=NotificationConfigRead)
async def get_config(
    config_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail={"title": "Chỉ admin mới xem được"})

    row = await db.get(NotificationConfig, config_id)
    if not row:
        raise HTTPException(status_code=404, detail={"title": "Config không tồn tại"})
    return _to_read(row)


@router.patch("/{config_id}", response_model=NotificationConfigRead)
async def update_config(
    config_id: str,
    body: NotificationConfigUpdate,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail={"title": "Chỉ admin mới sửa được"})

    row = await db.get(NotificationConfig, config_id)
    if not row:
        raise HTTPException(status_code=404, detail={"title": "Config không tồn tại"})

    old = {"name": row.name, "is_enabled": row.is_enabled}
    if body.name is not None:
        row.name = body.name
    if body.app_id is not None:
        row.app_id = body.app_id
    if body.channel is not None:
        row.channel = body.channel
    if body.schedule_cron is not None:
        row.schedule_cron = body.schedule_cron
    if body.is_enabled is not None:
        row.is_enabled = body.is_enabled
    if body.recipients is not None:
        if not body.recipients:
            raise HTTPException(status_code=422, detail={"title": "Cần ít nhất 1 recipient"})
        row.recipients = body.recipients
    if body.report_window_hours is not None:
        row.report_window_hours = body.report_window_hours

    ip = request.client.host if request.client else None
    await audit_log(
        db=db,
        user_id=current_user.user_id,
        action="UPDATE_NOTIFICATION_CONFIG",
        entity_type="notification_configs",
        entity_id=config_id,
        old_value=old,
        new_value={"name": row.name, "is_enabled": row.is_enabled},
        ip=ip,
    )
    await db.commit()
    await db.refresh(row)

    scheduler = _get_scheduler()
    if scheduler:
        from app.notifications.scheduler import reload_job
        reload_job(scheduler, row.id, row.schedule_cron, row.channel, row.is_enabled)

    return _to_read(row)


@router.delete("/{config_id}", status_code=204)
async def delete_config(
    config_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail={"title": "Chỉ admin mới xóa được"})

    row = await db.get(NotificationConfig, config_id)
    if not row:
        raise HTTPException(status_code=404, detail={"title": "Config không tồn tại"})

    ip = request.client.host if request.client else None
    await audit_log(
        db=db,
        user_id=current_user.user_id,
        action="DELETE_NOTIFICATION_CONFIG",
        entity_type="notification_configs",
        entity_id=config_id,
        old_value={"name": row.name, "channel": row.channel},
        ip=ip,
    )

    # Hủy job scheduler trước khi xóa DB record
    scheduler = _get_scheduler()
    if scheduler:
        try:
            scheduler.remove_job(f"notif_{config_id}")
        except Exception:
            pass

    await db.delete(row)
    await db.commit()


@router.post("/{config_id}/trigger", status_code=202)
async def trigger_now(
    config_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Gửi báo cáo ngay lập tức (không chờ cron)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail={"title": "Chỉ admin mới trigger được"})

    row = await db.get(NotificationConfig, config_id)
    if not row:
        raise HTTPException(status_code=404, detail={"title": "Config không tồn tại"})

    import asyncio
    from app.notifications.scheduler import run_notification_job
    asyncio.create_task(run_notification_job(config_id))
    log.info("notification_triggered", config_id=config_id, by=current_user.username)
    return {"message": "Đang gửi báo cáo", "config_id": config_id}


@router.get("/{config_id}/logs", response_model=list[NotificationLogRead])
async def get_logs(
    config_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail={"title": "Chỉ admin mới xem được"})

    row = await db.get(NotificationConfig, config_id)
    if not row:
        raise HTTPException(status_code=404, detail={"title": "Config không tồn tại"})

    logs = (
        await db.execute(
            select(NotificationLog)
            .where(NotificationLog.config_id == config_id)
            .order_by(NotificationLog.sent_at.desc())
            .limit(50)
        )
    ).scalars().all()

    return [
        NotificationLogRead(
            id=lg.id,
            config_id=lg.config_id,
            channel=lg.channel,
            status=lg.status,
            recipients_count=lg.recipients_count,
            error_message=lg.error_message,
            sent_at=lg.sent_at.isoformat() if lg.sent_at else "",
        )
        for lg in logs
    ]
