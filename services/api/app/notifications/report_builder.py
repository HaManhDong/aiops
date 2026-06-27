from __future__ import annotations

from datetime import datetime, timezone

import structlog

log = structlog.get_logger()


async def build_daily_report(app_id: str | None, window_hours: int = 24) -> str:
    """
    Tổng hợp ES log stats + prediction alerts → Markdown report.
    app_id=None → tổng hợp tất cả apps.
    """
    from app.database import get_db
    from app.services.config_service import ConfigService
    from sqlalchemy import text

    lines: list[str] = []
    now = datetime.now(timezone.utc)
    window_label = f"{window_hours}h qua"

    lines.append(f"# Báo cáo AIOps — {now.strftime('%d/%m/%Y %H:%M')} UTC")
    lines.append(f"Khoảng thời gian: {window_label}\n")

    async for db in get_db():
        # Lấy danh sách app_ids cần báo cáo
        if app_id:
            app_ids = [app_id]
        else:
            result = await db.execute(
                text("SELECT app_id, display_name FROM datasource_configs WHERE is_active=1")
            )
            rows = result.fetchall()
            app_ids = [r[0] for r in rows]
            app_names = {r[0]: r[1] for r in rows}

        # ── Incidents ──────────────────────────────────────────────
        inc_result = await db.execute(
            text("""
                SELECT app_id, severity, COUNT(*) as cnt
                FROM incidents
                WHERE created_at >= NOW() - INTERVAL :hours HOUR
                  AND (:app_id IS NULL OR app_id = :app_id)
                GROUP BY app_id, severity
                ORDER BY app_id, FIELD(severity,'critical','high','medium','low')
            """),
            {"hours": window_hours, "app_id": app_id},
        )
        inc_rows = inc_result.fetchall()

        lines.append("## Incidents mới")
        if inc_rows:
            by_app: dict[str, list] = {}
            for r in inc_rows:
                by_app.setdefault(r[0], []).append(r)
            for aid, rows_list in by_app.items():
                name = app_names.get(aid, aid) if not app_id else aid
                lines.append(f"\n### {name}")
                for r in rows_list:
                    lines.append(f"- **{r[1].upper()}**: {r[2]} incident(s)")
        else:
            lines.append("_Không có incident mới._")

        # ── Prediction Alerts ──────────────────────────────────────
        alert_result = await db.execute(
            text("""
                SELECT app_id, severity, COUNT(*) as cnt
                FROM prediction_alerts
                WHERE created_at >= NOW() - INTERVAL :hours HOUR
                  AND status = 'open'
                  AND (:app_id IS NULL OR app_id = :app_id)
                GROUP BY app_id, severity
                ORDER BY app_id, FIELD(severity,'critical','high','medium','low')
            """),
            {"hours": window_hours, "app_id": app_id},
        )
        alert_rows = alert_result.fetchall()

        lines.append("\n## Cảnh báo dự đoán (Prediction)")
        if alert_rows:
            by_app_a: dict[str, list] = {}
            for r in alert_rows:
                by_app_a.setdefault(r[0], []).append(r)
            for aid, rows_list in by_app_a.items():
                name = app_names.get(aid, aid) if not app_id else aid
                lines.append(f"\n### {name}")
                for r in rows_list:
                    lines.append(f"- **{r[1].upper()}**: {r[2]} alert(s)")
        else:
            lines.append("_Không có prediction alert đang mở._")

        # ── ES Log Stats per app ───────────────────────────────────
        lines.append("\n## Log errors (ES)")
        cfg_svc = ConfigService(db)

        for aid in app_ids:
            try:
                cfg = await cfg_svc.get_datasource(aid)
            except ValueError:
                continue
            if not cfg.elasticsearch_url:
                continue
            try:
                from app.providers.log_storage.elasticsearch import ElasticsearchProvider
                es = ElasticsearchProvider(
                    url=cfg.elasticsearch_url, api_key=cfg.elasticsearch_api_key
                )
                resp = await es.search(
                    cfg.app_log_index,
                    body={
                        "size": 0,
                        "query": {"bool": {"must": [
                            {"range": {"@timestamp": {"gte": f"now-{window_hours}h"}}},
                            {"terms": {"log.level.keyword": ["ERROR", "CRITICAL"]}},
                        ]}},
                        "aggs": {"top5": {"terms": {"field": "message.keyword", "size": 5}}},
                    },
                )
                error_count = resp.get("total", 0)
                top_errors = [
                    b["key"]
                    for b in resp.get("aggs", {}).get("top5", {}).get("buckets", [])
                    if isinstance(b, dict)
                ]
                name = app_names.get(aid, aid) if not app_id else aid
                lines.append(f"\n### {name}")
                lines.append(f"- Tổng lỗi {window_label}: **{error_count}**")
                if top_errors:
                    lines.append("- Top errors:")
                    for e in top_errors[:5]:
                        lines.append(f"  - `{e[:120]}`")
            except Exception as exc:
                lines.append(f"\n### {aid}")
                lines.append(f"_Không lấy được dữ liệu ES: {exc}_")

        break  # single DB iteration

    lines.append("\n---")
    lines.append("_Báo cáo tự động từ AI OpsAI Platform_")
    return "\n".join(lines)
