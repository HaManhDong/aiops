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
    predicted_at: str | None = None
    confidence: float | None
    evidence: dict | None = None
    blast_radius: dict | None = None
    is_true_positive: bool | None
    resolved_at: str | None = None
    suppressed_until: str | None = None
    created_at: str
    updated_at: str | None = None


class AlertPage(BaseModel):
    total: int
    items: list[AlertRead]


class ScanRead(BaseModel):
    id: str
    app_id: str
    scan_at: str
    started_at: str
    finished_at: str | None
    status: str
    duration_ms: int | None
    alerts_created: int
    signals_found: int
    data_quality: float | None
    error_message: str | None


def _access_filter(current_user: CurrentUser, app_id: str | None, params: dict) -> list[str]:
    if app_id:
        if not current_user.can_access(app_id):
            raise HTTPException(status_code=403, detail={"title": "Không có quyền"})
        params["app_id"] = app_id
        return ["app_id = :app_id"]
    if "all" in current_user.allowed_apps:
        return []
    if not current_user.allowed_apps:
        return ["1=0"]
    placeholders = []
    for idx, allowed_app in enumerate(current_user.allowed_apps):
        key = f"allowed_{idx}"
        params[key] = allowed_app
        placeholders.append(f":{key}")
    return [f"app_id IN ({', '.join(placeholders)})"]


def _json_or_none(raw: str | bytes | dict | None) -> dict | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        import json

        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _alert_from_row(r) -> AlertRead:
    return AlertRead(
        id=r[0], app_id=r[1], server_ip=r[2], alert_type=r[3], signal_group=r[4],
        severity=r[5], status=r[6], title=r[7], explanation=r[8],
        metric_name=r[9],
        current_value=float(r[10]) if r[10] is not None else None,
        baseline_value=float(r[11]) if r[11] is not None else None,
        predicted_at=r[12].isoformat() if r[12] else None,
        confidence=float(r[13]) if r[13] is not None else None,
        evidence=_json_or_none(r[14]),
        blast_radius=_json_or_none(r[15]),
        is_true_positive=bool(r[16]) if r[16] is not None else None,
        resolved_at=r[17].isoformat() if r[17] else None,
        suppressed_until=r[18].isoformat() if r[18] else None,
        created_at=r[19].isoformat() if r[19] else "",
        updated_at=r[20].isoformat() if r[20] else None,
    )


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
    params: dict = {}
    filters = ["1=1", *_access_filter(current_user, app_id, params)]

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
                   predicted_at, confidence, evidence, blast_radius, is_true_positive,
                   resolved_at, suppressed_until, created_at, updated_at
            FROM prediction_alerts WHERE {where}
            ORDER BY created_at DESC LIMIT :limit OFFSET :offset
        """),
        {**params, "limit": limit, "offset": offset},
    )

    items = [_alert_from_row(r) for r in rows.fetchall()]
    return AlertPage(total=total, items=items)


@router.get("/overview")
async def get_overview(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    params: dict = {}
    filters = ["1=1", *_access_filter(current_user, None, params)]
    where = " AND ".join(filters)

    open_count = (await db.execute(
        text(f"SELECT COUNT(*) FROM prediction_alerts WHERE {where} AND status = 'open'"),
        params,
    )).scalar() or 0
    today_count = (await db.execute(
        text(f"SELECT COUNT(*) FROM prediction_alerts WHERE {where} AND DATE(created_at) = CURRENT_DATE"),
        params,
    )).scalar() or 0
    severity_rows = (await db.execute(
        text(f"SELECT severity, COUNT(*) FROM prediction_alerts WHERE {where} GROUP BY severity"),
        params,
    )).fetchall()
    phase_rows = (await db.execute(
        text(f"SELECT signal_group, COUNT(*) FROM prediction_alerts WHERE {where} GROUP BY signal_group"),
        params,
    )).fetchall()
    top_rows = await db.execute(
        text(f"""
            SELECT id, app_id, server_ip, alert_type, signal_group, severity, status,
                   title, explanation, metric_name, current_value, baseline_value,
                   predicted_at, confidence, evidence, blast_radius, is_true_positive,
                   resolved_at, suppressed_until, created_at, updated_at
            FROM prediction_alerts WHERE {where}
            ORDER BY FIELD(severity, 'critical', 'high', 'medium', 'low'), created_at DESC
            LIMIT 5
        """),
        params,
    )
    return {
        "total_alerts_open": int(open_count),
        "total_alerts_today": int(today_count),
        "by_severity": {r[0]: int(r[1]) for r in severity_rows},
        "by_phase": {r[0]: int(r[1]) for r in phase_rows if r[0]},
        "top_alerts": [_alert_from_row(r) for r in top_rows.fetchall()],
    }


@router.get("/alerts/{alert_id}", response_model=AlertRead)
async def get_alert(
    alert_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("""
            SELECT id, app_id, server_ip, alert_type, signal_group, severity, status,
                   title, explanation, metric_name, current_value, baseline_value,
                   predicted_at, confidence, evidence, blast_radius, is_true_positive,
                   resolved_at, suppressed_until, created_at, updated_at
            FROM prediction_alerts WHERE id = :id
        """),
        {"id": alert_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail={"title": "Alert không tồn tại"})
    if not current_user.can_access(row[1]):
        raise HTTPException(status_code=403, detail={"title": "Không có quyền"})
    return _alert_from_row(row)


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await update_alert(alert_id, {"status": "acknowledged"}, current_user, db)


@router.get("/alerts/{alert_id}/blast-radius")
async def get_alert_blast_radius(
    alert_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("SELECT app_id, blast_radius, title FROM prediction_alerts WHERE id = :id"),
        {"id": alert_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail={"title": "Alert không tồn tại"})
    if not current_user.can_access(row[0]):
        raise HTTPException(status_code=403, detail={"title": "Không có quyền"})
    blast = _json_or_none(row[1]) or {}
    return {
        "origin": blast.get("origin") or row[2],
        "nodes": blast.get("nodes", []),
        "edges": blast.get("edges", []),
    }


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


@router.get("/baselines")
async def list_baselines(
    app_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    params: dict = {}
    filters = ["1=1", *_access_filter(current_user, app_id, params)]
    where = " AND ".join(filters)
    total = (await db.execute(
        text(f"SELECT COUNT(*) FROM prediction_baselines WHERE {where}"),
        params,
    )).scalar() or 0
    rows = await db.execute(
        text(f"""
            SELECT id, app_id, COALESCE(server_ip, '') AS host, metric_name,
                   mean_val, std_val, NULL AS ewma, computed_at
            FROM prediction_baselines WHERE {where}
            ORDER BY computed_at DESC LIMIT :limit OFFSET :offset
        """),
        {**params, "limit": limit, "offset": offset},
    )
    return {
        "total": int(total),
        "items": [
            {
                "id": r[0],
                "app_id": r[1],
                "host": r[2],
                "metric_name": r[3],
                "mean": float(r[4]),
                "std": float(r[5]),
                "ewma": float(r[6]) if r[6] is not None else None,
                "updated_at": r[7].isoformat() if r[7] else "",
            }
            for r in rows.fetchall()
        ],
    }


@router.get("/scans")
async def list_scans(
    app_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    params: dict = {}
    filters = ["1=1", *_access_filter(current_user, app_id, params)]
    where = " AND ".join(filters)
    total = (await db.execute(
        text(f"SELECT COUNT(*) FROM prediction_scans WHERE {where}"),
        params,
    )).scalar() or 0

    rows = await db.execute(
        text(f"""
            SELECT id, app_id, scan_at, duration_ms, alerts_created, signals_found, data_quality, error_message
            FROM prediction_scans WHERE {where}
            ORDER BY scan_at DESC LIMIT :limit OFFSET :offset
        """),
        {**params, "limit": limit, "offset": offset},
    )
    return {
        "total": int(total),
        "items": [
            ScanRead(
            id=r[0], app_id=r[1],
            scan_at=r[2].isoformat() if r[2] else "",
            started_at=r[2].isoformat() if r[2] else "",
            finished_at=r[2].isoformat() if r[2] and r[3] is not None else None,
            status="error" if r[7] else "done",
            duration_ms=r[3], alerts_created=r[4], signals_found=r[5],
            data_quality=float(r[6]) if r[6] is not None else None,
            error_message=r[7],
        )
            for r in rows.fetchall()
        ],
    }


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


@router.get("/accuracy-report")
async def get_accuracy_report(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    params: dict = {}
    filters = ["1=1", *_access_filter(current_user, None, params)]
    where = " AND ".join(filters)
    rows = await db.execute(
        text(f"""
            SELECT alert_type, app_id,
                   COUNT(*) AS total,
                   SUM(CASE WHEN is_true_positive = 1 THEN 1 ELSE 0 END) AS tp,
                   SUM(CASE WHEN is_true_positive = 0 THEN 1 ELSE 0 END) AS fp
            FROM prediction_alerts WHERE {where}
            GROUP BY alert_type, app_id
            ORDER BY total DESC
        """),
        params,
    )
    result = []
    for r in rows.fetchall():
        total = int(r[2] or 0)
        tp = int(r[3] or 0)
        fp = int(r[4] or 0)
        precision = tp / (tp + fp) if (tp + fp) else None
        result.append({
            "detector_type": r[0],
            "app_id": r[1],
            "total": total,
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": 0,
            "precision": round(precision, 4) if precision is not None else None,
            "recall": None,
            "f1": None,
        })
    return {"rows": result}
