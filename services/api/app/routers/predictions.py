from __future__ import annotations
import asyncio
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import CurrentUser, get_current_user, require_admin

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/predictions", tags=["predictions"])


class AlertRead(BaseModel):
    id: str
    app_id: str
    server_ip: str | None
    alert_type: str
    signal_group: str
    severity: str
    status: str
    title: str
    explanation: str | None
    metric_name: str | None
    current_value: float | None
    baseline_value: float | None
    confidence: float | None
    is_true_positive: bool | None
    created_at: str


class AlertPage(BaseModel):
    total: int
    items: list[AlertRead]


class ScanRead(BaseModel):
    id: str
    app_id: str
    scan_at: str
    duration_ms: int | None
    alerts_created: int
    signals_found: int
    data_quality: float | None
    error_message: str | None


@router.get("/alerts", response_model=AlertPage)
async def list_alerts(
    app_id: str | None = Query(None),
    status: str | None = Query(None),
    severity: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    filters = ["1=1"]
    params: dict = {}

    if app_id:
        if not current_user.can_access(app_id):
            raise HTTPException(status_code=403, detail={"title": "Không có quyền"})
        filters.append("app_id = :app_id")
        params["app_id"] = app_id
    elif "all" not in current_user.allowed_apps:
        filters.append("app_id IN :allowed")
        params["allowed"] = tuple(current_user.allowed_apps) or ("__none__",)

    if status:
        filters.append("status = :status")
        params["status"] = status
    if severity:
        filters.append("severity = :severity")
        params["severity"] = severity

    where = " AND ".join(filters)
    total_result = await db.execute(
        text(f"SELECT COUNT(*) FROM prediction_alerts WHERE {where}"), params
    )
    total = total_result.scalar() or 0

    rows = await db.execute(
        text(f"""
            SELECT id, app_id, server_ip, alert_type, signal_group, severity, status,
                   title, explanation, metric_name, current_value, baseline_value,
                   confidence, is_true_positive, created_at
            FROM prediction_alerts WHERE {where}
            ORDER BY created_at DESC LIMIT :limit OFFSET :offset
        """),
        {**params, "limit": limit, "offset": offset},
    )

    items = [
        AlertRead(
            id=r[0], app_id=r[1], server_ip=r[2], alert_type=r[3], signal_group=r[4],
            severity=r[5], status=r[6], title=r[7], explanation=r[8],
            metric_name=r[9],
            current_value=float(r[10]) if r[10] is not None else None,
            baseline_value=float(r[11]) if r[11] is not None else None,
            confidence=float(r[12]) if r[12] is not None else None,
            is_true_positive=bool(r[13]) if r[13] is not None else None,
            created_at=r[14].isoformat() if r[14] else "",
        )
        for r in rows.fetchall()
    ]
    return AlertPage(total=total, items=items)


@router.patch("/alerts/{alert_id}")
async def update_alert(
    alert_id: str,
    body: dict,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text("SELECT id, app_id FROM prediction_alerts WHERE id = :id"),
        {"id": alert_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail={"title": "Alert không tồn tại"})
    if not current_user.can_access(row[1]):
        raise HTTPException(status_code=403, detail={"title": "Không có quyền"})

    updates = []
    params: dict = {"id": alert_id}
    if "status" in body:
        updates.append("status = :status")
        params["status"] = body["status"]
    if "is_true_positive" in body:
        updates.append("is_true_positive = :tp")
        params["tp"] = int(body["is_true_positive"])

    if updates:
        await db.execute(
            text(f"UPDATE prediction_alerts SET {', '.join(updates)} WHERE id = :id"),
            params,
        )
        await db.commit()
    return {"id": alert_id, "updated": True}


@router.get("/scans", response_model=list[ScanRead])
async def list_scans(
    app_id: str = Query(...),
    limit: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.can_access(app_id):
        raise HTTPException(status_code=403, detail={"title": "Không có quyền"})

    rows = await db.execute(
        text("""
            SELECT id, app_id, scan_at, duration_ms, alerts_created, signals_found, data_quality, error_message
            FROM prediction_scans WHERE app_id = :app_id
            ORDER BY scan_at DESC LIMIT :limit
        """),
        {"app_id": app_id, "limit": limit},
    )
    return [
        ScanRead(
            id=r[0], app_id=r[1],
            scan_at=r[2].isoformat() if r[2] else "",
            duration_ms=r[3], alerts_created=r[4], signals_found=r[5],
            data_quality=float(r[6]) if r[6] is not None else None,
            error_message=r[7],
        )
        for r in rows.fetchall()
    ]


@router.post("/scan-now")
async def trigger_scan(
    app_id: str | None = Query(None),
    _: CurrentUser = Depends(require_admin),
):
    """Admin trigger manual scan."""
    from app.prediction.runner import run_prediction_scan_all, scan_app
    if app_id:
        asyncio.create_task(scan_app(app_id))
    else:
        asyncio.create_task(run_prediction_scan_all())
    return {"triggered": True, "app_id": app_id}


@router.get("/accuracy")
async def get_accuracy(
    app_id: str = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Tỷ lệ true positive của prediction alerts."""
    if not current_user.can_access(app_id):
        raise HTTPException(status_code=403, detail={"title": "Không có quyền"})

    result = await db.execute(
        text("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN is_true_positive = 1 THEN 1 ELSE 0 END) as tp,
                SUM(CASE WHEN is_true_positive = 0 THEN 1 ELSE 0 END) as fp,
                SUM(CASE WHEN is_true_positive IS NULL THEN 1 ELSE 0 END) as unknown_count
            FROM prediction_alerts WHERE app_id = :app_id
        """),
        {"app_id": app_id},
    )
    row = result.fetchone()
    total, tp, fp, unknown = (int(x or 0) for x in row)
    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    return {
        "app_id": app_id,
        "total_alerts": total,
        "true_positives": tp,
        "false_positives": fp,
        "unknown": unknown,
        "precision": round(precision, 4) if precision is not None else None,
    }
