from __future__ import annotations
import asyncio
import time
import uuid
import structlog

log = structlog.get_logger()

_RUNNING = False


async def run_prediction_scan_all() -> None:
    """Entry point — scan tất cả app_ids."""
    global _RUNNING
    if _RUNNING:
        log.debug("prediction_scan_already_running")
        return
    _RUNNING = True
    try:
        from app.database import get_db
        from sqlalchemy import text
        async for db in get_db():
            result = await db.execute(
                text("SELECT DISTINCT app_id FROM datasource_configs WHERE is_active = 1")
            )
            app_ids = [r[0] for r in result.fetchall()]
            for app_id in app_ids:
                try:
                    await scan_app(app_id)
                except Exception as e:
                    log.error("prediction_scan_error", app_id=app_id, error=str(e))
            break
    finally:
        _RUNNING = False


async def scan_app(app_id: str) -> None:
    from app.database import get_db
    from app.prediction.context import PredictionContext

    scan_id = str(uuid.uuid4())
    start = time.monotonic()

    async for db in get_db():
        ctx = PredictionContext(app_id=app_id, scan_id=scan_id)
        alerts_created = 0
        signals_found = 0
        error_msg = None

        try:
            # 1. Collect data
            await _collect_data(ctx, db)

            # 2. Quality gate
            quality = _assess_quality(ctx)
            ctx.data_quality = quality.compute_score()
            if not quality.is_sufficient():
                log.debug("scan_quality_insufficient", app_id=app_id, score=ctx.data_quality)
                return

            # 3. Run extractors
            signals = await _run_extractors(ctx, db)
            ctx.signals = signals
            signals_found = len(signals)

            # 4. Write alerts
            alerts_created = await _write_signals_as_alerts(ctx, signals, db)

            # 5. Auto-correlate
            from app.prediction.auto_correlate import auto_correlate_alerts
            await auto_correlate_alerts(db, app_id)

        except Exception as e:
            error_msg = str(e)[:500]
            log.error("scan_app_error", app_id=app_id, error=str(e))
        finally:
            duration_ms = int((time.monotonic() - start) * 1000)
            from app.prediction.alert_writer import write_scan
            try:
                await write_scan(
                    db, app_id=app_id, duration_ms=duration_ms,
                    alerts_created=alerts_created, signals_found=signals_found,
                    data_quality=ctx.data_quality, error_message=error_msg,
                )
            except Exception:
                pass
        break

    log.info("prediction_scan_done", app_id=app_id, scan_id=scan_id,
             alerts=alerts_created, signals=signals_found)


async def _collect_data(ctx: PredictionContext, db) -> None:
    """Collect servers + metrics + ES log stats."""
    from app.agents.server_registry import ServerRegistryAgent, RegistryStatus
    from app.services.config_service import ConfigService

    cfg_svc = ConfigService(db)
    try:
        cfg = await cfg_svc.get_datasource(ctx.app_id)
    except ValueError:
        return

    # Servers
    registry = ServerRegistryAgent(db)
    result = await registry.get_servers(ctx.app_id)
    if result.status == RegistryStatus.FOUND:
        ctx.servers = [{"ip": s.ip, "hostname": s.hostname} for s in result.servers]

    # Prometheus metrics
    if cfg.prometheus_url and ctx.servers:
        from app.providers.metrics.prometheus import PrometheusProvider
        prom = PrometheusProvider(url=cfg.prometheus_url)
        for server in ctx.servers[:30]:
            ip = server["ip"]
            metrics: dict = {}
            for metric, query in [
                (
                    "cpu_pct",
                    f'avg(rate(node_cpu_seconds_total{{mode!="idle",instance=~"{ip}:.*"}}[5m])) * 100',
                ),
                (
                    "ram_pct",
                    f'(1 - node_memory_MemAvailable_bytes{{instance=~"{ip}:.*"}} / node_memory_MemTotal_bytes{{instance=~"{ip}:.*"}}) * 100',
                ),
                (
                    "disk_pct",
                    f'(1 - node_filesystem_avail_bytes{{instance=~"{ip}:.*",mountpoint="/"}} / node_filesystem_size_bytes{{instance=~"{ip}:.*",mountpoint="/"}}) * 100',
                ),
            ]:
                try:
                    result_data = await prom.query_instant(query)
                    if result_data:
                        metrics[metric] = float(result_data[0]["value"][1])
                    else:
                        metrics[metric] = None
                except Exception:
                    metrics[metric] = None
            ctx.metrics[ip] = metrics

    # ES log stats (error count per app)
    if cfg.elasticsearch_url:
        from app.providers.log_storage.elasticsearch import ElasticsearchProvider
        es = ElasticsearchProvider(
            url=cfg.elasticsearch_url, api_key=cfg.elasticsearch_api_key
        )
        try:
            result_es = await es.search(
                cfg.app_log_index,
                body={
                    "size": 0,
                    "query": {"bool": {"must": [
                        {"range": {"@timestamp": {"gte": "now-1h"}}},
                        {"terms": {"log.level.keyword": ["ERROR", "CRITICAL"]}},
                    ]}},
                    "aggs": {"top_errors": {"terms": {"field": "message.keyword", "size": 10}}},
                },
            )
            ctx.log_stats["error_count"] = result_es.get("total", 0)
            # aggs["top_errors"] is raw ES aggregation response with "buckets" list
            buckets = result_es.get("aggs", {}).get("top_errors", {}).get("buckets", [])
            ctx.log_stats["top_errors"] = [
                b["key"] for b in buckets if isinstance(b, dict) and "key" in b
            ]
        except Exception as e:
            log.warning("scan_es_failed", app_id=ctx.app_id, error=str(e))


def _assess_quality(ctx: PredictionContext) -> "DataQualityMetrics":
    from app.prediction.quality import DataQualityMetrics
    has_metrics = any(
        any(v is not None for v in m.values())
        for m in ctx.metrics.values()
    )
    servers_with_metrics = sum(
        1 for ip, m in ctx.metrics.items() if any(v is not None for v in m.values())
    )
    coverage = servers_with_metrics / len(ctx.servers) if ctx.servers else 0.0
    return DataQualityMetrics(
        es_available="error_count" in ctx.log_stats,
        prometheus_available=has_metrics,
        server_count=len(ctx.servers),
        metrics_coverage=coverage,
    )


async def _run_extractors(ctx: PredictionContext, db) -> list[dict]:
    from sqlalchemy import text
    signals: list[dict] = []

    for server in ctx.servers:
        ip = server["ip"]
        metrics = ctx.metrics.get(ip, {})

        for metric in ("cpu_pct", "ram_pct", "disk_pct"):
            value = metrics.get(metric)
            if value is None:
                continue

            # Update baseline
            from app.prediction.baseline import upsert_baseline
            baseline = await upsert_baseline(db, ctx.app_id, metric, value, server_ip=ip)

            # Group B: Baseline deviation
            from app.prediction.extractors.baseline_dev import detect_baseline_deviation
            dev = detect_baseline_deviation(metric, value, baseline.mean, baseline.std, ip)
            if dev:
                signals.append({
                    "signal_group": "B",
                    "type": "baseline_deviation",
                    "server_ip": ip,
                    "metric": metric,
                    "value": value,
                    "baseline_mean": baseline.mean,
                    "baseline_std": baseline.std,
                    "z_score": dev.z_score_val,
                    "severity": dev.severity,
                })

    # Group D1: Novelty detection on error patterns
    top_errors = ctx.log_stats.get("top_errors", [])
    if top_errors:
        result = await db.execute(
            text("SELECT pattern FROM error_classifier_patterns WHERE is_active = 1 LIMIT 50")
        )
        known = [r[0] for r in result.fetchall()]
        from app.prediction.extractors.novelty import detect_novelty
        novelty_signals = detect_novelty(top_errors, known)
        for ns in novelty_signals:
            signals.append({
                "signal_group": "D1",
                "type": "novel_error",
                "server_ip": None,
                "pattern": ns.new_pattern,
                "similarity": ns.similarity,
                "severity": ns.severity,
            })

    # Group F1: Recurrence detection
    if top_errors:
        result = await db.execute(
            text("""
                SELECT id, title, error_patterns, solution
                FROM incidents
                WHERE app_id = :app_id AND status = 'resolved'
                ORDER BY resolved_at DESC LIMIT 20
            """),
            {"app_id": ctx.app_id},
        )
        past_incidents = [
            {"id": r[0], "title": r[1], "error_patterns": r[2], "solution": r[3]}
            for r in result.fetchall()
        ]
        from app.prediction.extractors.recurrence import detect_recurrence
        rec_signals = detect_recurrence(top_errors, past_incidents)
        for rs in rec_signals:
            signals.append({
                "signal_group": "F1",
                "type": "recurrence",
                "server_ip": None,
                "incident_id": rs.matched_incident_id,
                "incident_title": rs.matched_title,
                "similarity": rs.similarity,
                "solution": rs.solution,
                "severity": rs.severity,
            })

    # Group E: Composite (2+ distinct groups for same server)
    from app.prediction.extractors.composite import detect_composite
    server_signals: dict[str, list] = {}
    for sig in signals:
        key = sig.get("server_ip") or "_global"
        server_signals.setdefault(key, []).append(sig)
    for ip_key, sigs in server_signals.items():
        comp = detect_composite(sigs, server_ip=ip_key if ip_key != "_global" else None)
        if comp:
            signals.append({
                "signal_group": "E",
                "type": "composite",
                "server_ip": comp.server_ip,
                "signal_types": comp.signal_types,
                "severity": comp.severity,
            })

    return signals


async def _write_signals_as_alerts(ctx: PredictionContext, signals: list[dict], db) -> int:
    from app.prediction.alert_writer import write_alert
    from app.prediction.explanation import (
        explain_baseline_deviation, explain_novelty,
        explain_recurrence, explain_composite,
    )
    count = 0
    for sig in signals:
        sig_type = sig["type"]
        expl = ""
        title = ""

        if sig_type == "baseline_deviation":
            expl = explain_baseline_deviation(
                sig["metric"], sig.get("server_ip"),
                sig["value"], sig["baseline_mean"], sig["z_score"],
            )
            title = f"Bất thường {sig['metric']} trên {sig.get('server_ip', 'hệ thống')}"
        elif sig_type == "novel_error":
            expl = explain_novelty(sig["pattern"], sig["similarity"])
            title = "Pattern lỗi mới chưa từng gặp"
        elif sig_type == "recurrence":
            expl = explain_recurrence(sig["incident_title"], sig["similarity"], sig.get("solution"))
            title = f"Tái phát: {sig['incident_title'][:80]}"
        elif sig_type == "composite":
            expl = explain_composite(sig.get("signal_types", []))
            title = "Nhiều tín hiệu bất thường đồng thời"
        else:
            continue

        alert_id = await write_alert(
            db,
            app_id=ctx.app_id,
            server_ip=sig.get("server_ip"),
            alert_type=sig_type,
            signal_group=sig.get("signal_group", "?"),
            severity=sig.get("severity", "medium"),
            title=title,
            explanation=expl,
            metric_name=sig.get("metric"),
            current_value=sig.get("value"),
            baseline_value=sig.get("baseline_mean"),
            confidence=0.6,
            evidence=sig,
        )
        if alert_id:
            count += 1
    return count
