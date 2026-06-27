from __future__ import annotations

from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.middleware.auth import CurrentUser, require_admin
from app.models.config import DatasourceConfig
from app.services.audit import audit_log
from app.services.config_service import ConfigService, get_config_service

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/admin", tags=["admin-config"])


class DatasourceCreate(BaseModel):
    app_id: str
    display_name: str
    elasticsearch_url: str
    elasticsearch_api_key: str | None = None
    app_log_index: str
    syslog_index: str = "aiops-txt-logs"
    prometheus_url: str | None = None
    prometheus_extra_labels: dict | None = None
    kibana_url: str | None = None
    kibana_api_key: str | None = None
    alert_thresholds: dict[str, Any] | None = None
    txt_watch_dirs: list[str] | None = None
    log_provider: str = "elasticsearch"
    metrics_provider: str = "prometheus"


class DatasourceUpdate(BaseModel):
    display_name: str | None = None
    elasticsearch_url: str | None = None
    elasticsearch_api_key: str | None = None
    app_log_index: str | None = None
    syslog_index: str | None = None
    prometheus_url: str | None = None
    prometheus_extra_labels: dict | None = None
    kibana_url: str | None = None
    kibana_api_key: str | None = None
    alert_thresholds: dict[str, Any] | None = None
    txt_watch_dirs: list[str] | None = None
    log_provider: str | None = None
    metrics_provider: str | None = None
    is_active: bool | None = None


class DatasourceRead(BaseModel):
    id: str
    app_id: str
    display_name: str
    elasticsearch_url: str
    has_elasticsearch_api_key: bool
    app_log_index: str
    syslog_index: str
    prometheus_url: str | None
    prometheus_extra_labels: dict | None
    kibana_url: str | None
    has_kibana_api_key: bool
    alert_thresholds: dict[str, Any]
    txt_watch_dirs: list | None
    log_provider: str
    metrics_provider: str
    is_active: bool

    model_config = {"from_attributes": True}


def _row_to_read(row: DatasourceConfig) -> DatasourceRead:
    return DatasourceRead(
        id=row.id,
        app_id=row.app_id,
        display_name=row.display_name,
        elasticsearch_url=row.elasticsearch_url,
        has_elasticsearch_api_key=bool(row.elasticsearch_api_key),
        app_log_index=row.app_log_index,
        syslog_index=row.syslog_index,
        prometheus_url=row.prometheus_url,
        prometheus_extra_labels=row.prometheus_extra_labels,
        kibana_url=row.kibana_url,
        has_kibana_api_key=bool(row.kibana_api_key),
        alert_thresholds=row.alert_thresholds or {},
        txt_watch_dirs=row.txt_watch_dirs,
        log_provider=row.log_provider,
        metrics_provider=row.metrics_provider,
        is_active=row.is_active,
    )


def _encrypt_if_present(value: str | None) -> str | None:
    if not value:
        return None
    from app.services.encryption import encrypt
    return encrypt(value)


@router.get("/services", response_model=list[DatasourceRead])
async def list_datasources(
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
):
    rows = (
        await db.execute(select(DatasourceConfig).order_by(DatasourceConfig.created_at))
    ).scalars().all()
    return [_row_to_read(r) for r in rows]


@router.post("/services", response_model=DatasourceRead, status_code=201)
async def create_datasource(
    body: DatasourceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
):
    existing = (
        await db.execute(
            select(DatasourceConfig).where(DatasourceConfig.app_id == body.app_id)
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail={"title": f"app_id '{body.app_id}' đã tồn tại"})

    row = DatasourceConfig(
        app_id=body.app_id,
        display_name=body.display_name,
        elasticsearch_url=body.elasticsearch_url,
        elasticsearch_api_key=_encrypt_if_present(body.elasticsearch_api_key),
        app_log_index=body.app_log_index,
        syslog_index=body.syslog_index,
        prometheus_url=body.prometheus_url,
        prometheus_extra_labels=body.prometheus_extra_labels,
        kibana_url=body.kibana_url,
        kibana_api_key=_encrypt_if_present(body.kibana_api_key),
        alert_thresholds=body.alert_thresholds or {
            "cpu_pct": 85, "ram_pct": 90, "disk_pct": 85,
            "error_count_1h": 10, "error_count_critical_1h": 3,
            "connection_timeout_1h": 10, "oracle_deadlock_1h": 3, "smtp_error_30m": 5,
        },
        txt_watch_dirs=body.txt_watch_dirs,
        log_provider=body.log_provider,
        metrics_provider=body.metrics_provider,
    )
    db.add(row)
    await db.flush()

    ip = request.client.host if request.client else None
    await audit_log(
        db, current_user.user_id, "CREATE_DATASOURCE", "datasource_configs", row.app_id,
        new_value={"app_id": row.app_id, "display_name": row.display_name}, ip=ip,
    )
    await db.commit()
    await db.refresh(row)

    log.info("datasource_created", app_id=row.app_id, by=current_user.username)
    return _row_to_read(row)


@router.get("/services/{app_id}", response_model=DatasourceRead)
async def get_datasource(
    app_id: str,
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
):
    row = (
        await db.execute(
            select(DatasourceConfig).where(DatasourceConfig.app_id == app_id)
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail={"title": f"Datasource '{app_id}' không tồn tại"})
    return _row_to_read(row)


@router.put("/services/{app_id}", response_model=DatasourceRead)
async def update_datasource(
    app_id: str,
    body: DatasourceUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
):
    row = (
        await db.execute(
            select(DatasourceConfig).where(DatasourceConfig.app_id == app_id)
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail={"title": f"Datasource '{app_id}' không tồn tại"})

    old = {"display_name": row.display_name, "elasticsearch_url": row.elasticsearch_url}

    update_data = body.model_dump(exclude_none=True)
    for field, value in update_data.items():
        if field == "elasticsearch_api_key":
            row.elasticsearch_api_key = _encrypt_if_present(value)
        elif field == "kibana_api_key":
            row.kibana_api_key = _encrypt_if_present(value)
        else:
            setattr(row, field, value)

    ip = request.client.host if request.client else None
    await audit_log(
        db, current_user.user_id, "UPDATE_DATASOURCE", "datasource_configs", app_id,
        old_value=old, new_value=update_data, ip=ip,
    )
    await db.commit()
    await db.refresh(row)

    # Invalidate Redis cache
    cfg_svc = ConfigService(db)
    await cfg_svc.invalidate_cache(app_id)

    log.info("datasource_updated", app_id=app_id, by=current_user.username)
    return _row_to_read(row)


@router.delete("/services/{app_id}", status_code=204)
async def delete_datasource(
    app_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
):
    row = (
        await db.execute(
            select(DatasourceConfig).where(DatasourceConfig.app_id == app_id)
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail={"title": f"Datasource '{app_id}' không tồn tại"})

    row.is_active = False

    ip = request.client.host if request.client else None
    await audit_log(
        db, current_user.user_id, "DEACTIVATE_DATASOURCE", "datasource_configs", app_id,
        old_value={"is_active": True}, new_value={"is_active": False}, ip=ip,
    )
    await db.commit()

    cfg_svc = ConfigService(db)
    await cfg_svc.invalidate_cache(app_id)
    log.info("datasource_deactivated", app_id=app_id, by=current_user.username)


@router.get("/services/{app_id}/test")
async def test_datasource_connection(
    app_id: str,
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
):
    row = (
        await db.execute(
            select(DatasourceConfig).where(DatasourceConfig.app_id == app_id)
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail={"title": f"Datasource '{app_id}' không tồn tại"})

    results: dict[str, Any] = {}

    # Test Elasticsearch
    try:
        headers = {}
        if row.elasticsearch_api_key:
            from app.services.encryption import decrypt
            api_key = decrypt(row.elasticsearch_api_key)
            headers["Authorization"] = f"ApiKey {api_key}"

        es_url = row.elasticsearch_url.rstrip("/")
        async with httpx.AsyncClient(timeout=settings.es_logs_timeout, verify=False) as client:
            resp = await client.get(f"{es_url}/_cluster/health", headers=headers)
            index_name = row.app_log_index.strip().strip("/")
            index_resp = await client.head(f"{es_url}/{index_name}", headers=headers)
            resolved_index = index_name
            if index_resp.status_code >= 400 and "*" not in index_name and "," not in index_name:
                wildcard_index = f"{index_name}-*"
                wildcard_resp = await client.get(
                    f"{es_url}/_cat/indices/{wildcard_index}",
                    headers=headers,
                    params={"format": "json", "h": "index"},
                )
                if wildcard_resp.status_code < 400 and wildcard_resp.json():
                    resolved_index = wildcard_index
                    index_resp = wildcard_resp
            results["elasticsearch"] = {
                "status": "ok" if resp.status_code < 400 and index_resp.status_code < 400 else "error",
                "http_status": resp.status_code,
                "index": resolved_index,
                "index_status": index_resp.status_code,
            }
    except Exception as e:
        results["elasticsearch"] = {"status": "error", "error": str(e)}

    # Test Prometheus (nếu có)
    if row.prometheus_url:
        try:
            prom_url = row.prometheus_url.rstrip("/")
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(f"{prom_url}/-/healthy")
                results["prometheus"] = {
                    "status": "ok" if resp.status_code == 200 else "error",
                    "http_status": resp.status_code,
                }
        except Exception as e:
            results["prometheus"] = {"status": "error", "error": str(e)}

    all_ok = all(v.get("status") == "ok" for v in results.values())
    return {"app_id": app_id, "overall": "ok" if all_ok else "partial", "checks": results}


@router.get("/services/{app_id}/log-fields/detect")
async def detect_log_fields(
    app_id: str,
    db: AsyncSession = Depends(get_db),
    config_svc: ConfigService = Depends(get_config_service),
    _: CurrentUser = Depends(require_admin),
):
    """
    Auto-detect ES log field mapping:
    1. Fetch sample 3 log documents from ES
    2. Send sample to LLM to detect field mapping
    3. Return recommended field mapping
    """
    import json as _json
    from app.providers.log_storage.elasticsearch import ElasticsearchProvider
    from app.providers import get_llm_provider

    try:
        cfg = await config_svc.get_datasource(app_id)
    except ValueError:
        raise HTTPException(status_code=404, detail={"title": f"Datasource '{app_id}' không tồn tại"})

    # Get sample documents
    try:
        es_provider = ElasticsearchProvider(
            url=cfg.elasticsearch_url,
            api_key=cfg.elasticsearch_api_key,
        )
        sample = await es_provider.search(
            cfg.app_log_index,
            body={"query": {"match_all": {}}, "sort": [{"@timestamp": {"order": "desc"}}], "size": 3},
            size=3,
        )
        hits = sample.get("hits", [])
    except Exception as e:
        raise HTTPException(status_code=502, detail={"title": f"Không thể lấy sample từ ES: {str(e)}"})

    if not hits:
        return {"message": "Không có document trong index", "mapping": {}}

    # Ask LLM to detect field mapping
    sample_text = _json.dumps(hits[:3], ensure_ascii=False, indent=2)[:3000]
    prompt = f"""Phân tích các log document sau và xác định field mapping:
{sample_text}

Trả về JSON với các field names thực tế:
{{
  "timestamp_field": "tên field timestamp",
  "message_field": "tên field message chính",
  "level_field": "tên field log level",
  "app_id_field": "tên field app_id nếu có",
  "ip_field": "tên field IP nếu có"
}}
Chỉ trả về JSON."""

    mapping: dict = {}
    try:
        llm = await get_llm_provider()
        raw = await llm.generate_json(prompt, temperature=0.0)
        mapping = _json.loads(raw)
    except Exception as e:
        log.warning("field_detect_llm_failed", app_id=app_id, error=str(e))

    return {
        "app_id": app_id,
        "index": cfg.app_log_index,
        "sample_count": len(hits),
        "mapping": mapping,
        "sample": hits[0] if hits else None,
    }
