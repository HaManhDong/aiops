from __future__ import annotations
import json
import pathlib
import httpx
import structlog
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.parser import parse_file_chunk
from app.state import get_collector_state, upsert_collector_state, get_worker_config

log = structlog.get_logger()


async def run_collection_for_app(app_id: str, db: AsyncSession, cfg: dict, patterns: list[dict]) -> dict:
    worker_cfg = await get_worker_config(db, app_id)
    if not worker_cfg or not worker_cfg["is_enabled"]:
        return {"skipped": True, "reason": "disabled"}

    watch_dirs = cfg.get("txt_watch_dirs") or []
    if isinstance(watch_dirs, str):
        watch_dirs = json.loads(watch_dirs)

    file_patterns = worker_cfg.get("file_patterns") or ["*.txt", "*.log"]
    batch_size = worker_cfg.get("batch_size") or 100

    files_scanned = records_new = errors = 0

    for watch_dir in watch_dirs:
        dir_path = pathlib.Path(watch_dir)
        if not dir_path.exists():
            log.warning("watch_dir_not_found", dir=watch_dir, app_id=app_id)
            continue

        for file_path in _discover_files(dir_path, file_patterns):
            files_scanned += 1
            try:
                n = await _process_file(
                    file_path=file_path,
                    app_id=app_id,
                    es_url=cfg["elasticsearch_url"],
                    es_api_key=cfg.get("elasticsearch_api_key"),
                    log_index=cfg.get("app_log_index", f"vst-txt-logs-{app_id}"),
                    error_patterns=patterns,
                    batch_size=batch_size,
                    db=db,
                )
                records_new += n
            except Exception as e:
                errors += 1
                log.error("file_processing_failed", file=str(file_path), error=str(e))

    log.info("collection_done", app_id=app_id, files=files_scanned, records=records_new, errors=errors)
    return {"files_scanned": files_scanned, "records_new": records_new, "errors": errors}


def _discover_files(dir_path: pathlib.Path, file_patterns: list[str]) -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for pattern in file_patterns:
        files.extend(dir_path.rglob(pattern))
    return sorted(set(files))


async def _process_file(
    file_path: pathlib.Path,
    app_id: str,
    es_url: str,
    es_api_key: str | None,
    log_index: str,
    error_patterns: list[dict],
    batch_size: int,
    db: AsyncSession,
) -> int:
    state = await get_collector_state(db, app_id, str(file_path))
    from_byte = state.last_byte if state else 0
    file_size = file_path.stat().st_size

    # File rotation detection
    if file_size < from_byte:
        log.info("file_rotated_detected", file=str(file_path), last_byte=from_byte, size=file_size)
        from_byte = 0

    if from_byte >= file_size:
        return 0

    # Read new content
    with open(file_path, encoding="utf-8", errors="ignore") as f:
        f.seek(from_byte)
        content = f.read()
        current_byte = f.tell()

    # Parse
    records = parse_file_chunk(content, str(file_path), app_id, error_patterns)

    if not records:
        await upsert_collector_state(db, app_id, str(file_path), current_byte, file_size, 0)
        return 0

    # Bulk index in batches
    total_indexed = 0
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        try:
            await _bulk_index_es(batch, es_url, es_api_key, log_index)
            total_indexed += len(batch)
        except Exception as e:
            log.error("bulk_index_failed", batch_start=i, error=str(e))

    await upsert_collector_state(db, app_id, str(file_path), current_byte, file_size, total_indexed)
    log.info("file_processed", file=str(file_path), records=total_indexed)
    return total_indexed


async def _bulk_index_es(records, es_url: str, api_key: str | None, index: str) -> None:
    lines = []
    for rec in records:
        doc = rec.to_es_doc()
        doc_id = doc.pop("_id", None)
        meta: dict = {"index": {"_index": index}}
        if doc_id:
            meta["index"]["_id"] = doc_id
        lines.append(json.dumps(meta))
        lines.append(json.dumps(doc, ensure_ascii=False, default=str))
    body = "\n".join(lines) + "\n"

    headers: dict[str, str] = {"Content-Type": "application/x-ndjson"}
    if api_key:
        headers["Authorization"] = f"ApiKey {api_key}"

    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        resp = await client.post(f"{es_url}/_bulk", headers=headers, content=body.encode())
        resp.raise_for_status()
        result = resp.json()
        if result.get("errors"):
            error_items = [i for i in result.get("items", []) if i.get("index", {}).get("error")]
            log.warning("bulk_index_partial_errors", errors=len(error_items))
