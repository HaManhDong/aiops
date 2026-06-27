# Skill: TXT Log Collector (Module 1)

## Tổng quan
Service độc lập chạy trong container `worker`, dùng APScheduler chạy mỗi 5 phút.
Đọc file *.txt / *.log từ watch_dirs (lấy từ MariaDB), parse, index vào ES.

## Kiến trúc worker

```
APScheduler (cron: */5 * * * *)
        ↓
Đọc worker_configs từ MariaDB → list[WorkerConfig]
        ↓
Với mỗi WorkerConfig (mỗi app_id):
    Scan files trong watch_dirs
        ↓
    So sánh file_size với last_byte trong collector_state (MariaDB)
        ↓  (có thay đổi)
    Đọc phần mới từ offset last_byte
        ↓
    Parse từng block theo timestamp pattern
        ↓
    Classify error_type (regex patterns từ MariaDB)
        ↓
    Bulk index vào Elasticsearch
        ↓
    Update collector_state (last_byte, last_run_at, records_indexed)
```

## File: `services/worker/app/parser.py`

```python
import re
import hashlib
from dataclasses import dataclass
from datetime import datetime


TIMESTAMP_PATTERN = re.compile(r'\[(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})\]')
CHI_TIET_LOI_MARKER = "CHI TIẾT LỖI"


@dataclass
class ParsedLogRecord:
    doc_id: str              # MD5 dedup key
    timestamp: datetime
    source_file: str
    app_id: str
    log_type: str            # business_alert | technical_error
    log_level: str           # ERROR | WARNING | CRITICAL
    error_type: str          # connection_timeout | oracle_deadlock | ...
    severity: str            # critical | error | warning
    message: str             # cho technical_error
    tieu_de: str | None      # cho business_alert
    su_kien: str | None
    module: str | None
    noi_dung: str | None
    ip_target: str | None
    raw_body: str            # body gốc (truncate 2000 chars)


def parse_file_chunk(
    content: str,
    file_path: str,
    app_id: str,
    error_patterns: list[dict],
) -> list[ParsedLogRecord]:
    """
    Parse một đoạn nội dung file (từ last_byte đến EOF).
    Trả về danh sách record đã parse sẵn sàng để index.

    Args:
        content: nội dung file từ last_byte
        file_path: đường dẫn file gốc (để lưu source_file)
        app_id: "erp" | "mvs" | "website"
        error_patterns: list regex patterns từ MariaDB
    """
    records = []
    # Tách theo pattern [DD/MM/YYYY HH:MM:SS]
    parts = TIMESTAMP_PATTERN.split(content)

    i = 1
    while i < len(parts) - 1:
        ts_str = parts[i].strip()
        body   = parts[i + 1].strip()
        i += 2

        if not body:
            continue

        try:
            ts = datetime.strptime(ts_str, "%d/%m/%Y %H:%M:%S")
        except ValueError:
            ts = datetime.utcnow()

        record = _build_record(ts, body, file_path, app_id, error_patterns)
        records.append(record)

    return records


def _build_record(
    ts: datetime,
    body: str,
    file_path: str,
    app_id: str,
    error_patterns: list[dict],
) -> ParsedLogRecord:
    # Dedup ID
    doc_id = hashlib.md5(f"{ts.isoformat()}{body[:100]}".encode()).hexdigest()

    if CHI_TIET_LOI_MARKER in body:
        error_type, severity = _classify(body, error_patterns)
        return ParsedLogRecord(
            doc_id=doc_id, timestamp=ts, source_file=file_path, app_id=app_id,
            log_type="business_alert", log_level="ERROR",
            error_type=error_type, severity=severity,
            message="",
            tieu_de=_extract(body, r'Tiêu đề:\s*(.+)'),
            su_kien=_extract(body, r'Sự kiện:\s*(.+)'),
            module=_extract(body, r'Module:\s*(.+)'),
            noi_dung=_extract(body, r'Nội dung:\s*([\s\S]+)', max_len=1000),
            ip_target=_extract_ip(body),
            raw_body=body[:2000],
        )
    else:
        error_type, severity = _classify(body, error_patterns)
        return ParsedLogRecord(
            doc_id=doc_id, timestamp=ts, source_file=file_path, app_id=app_id,
            log_type="technical_error", log_level="ERROR",
            error_type=error_type, severity=severity,
            message=body.replace("ERROR", "").strip()[:1000],
            tieu_de=None, su_kien=None, module=None, noi_dung=None,
            ip_target=_extract_ip(body),
            raw_body=body[:2000],
        )


def _classify(body: str, patterns: list[dict]) -> tuple[str, str]:
    """Áp dụng patterns theo priority order (sorted từ DB)."""
    for p in patterns:
        if re.search(p["pattern"], body, re.IGNORECASE):
            return p["error_type"], p["severity"]
    return "unknown", "error"


def _extract(body: str, pattern: str, max_len: int = 300) -> str | None:
    m = re.search(pattern, body)
    if not m:
        return None
    return m.group(1).strip()[:max_len]


def _extract_ip(body: str) -> str | None:
    m = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+)', body)
    return m.group(1) if m else None
```

## File: `services/worker/app/collector.py`

```python
async def run_collection_for_app(app_id: str, db: AsyncSession) -> dict:
    """
    Chạy full collection cycle cho một app_id.
    Trả về summary {"files_scanned": N, "records_new": M, "errors": K}
    """
    config_svc = ConfigService(db)
    cfg = await config_svc.get_datasource(app_id)
    patterns = await config_svc.get_error_patterns(app_id)

    # Lấy worker config từ DB — source of truth cho file_patterns và is_enabled
    # watch_dirs đến từ datasource_configs (cfg.txt_watch_dirs)
    # file_patterns và schedule đến từ worker_configs
    worker_cfg = await get_worker_config(db, app_id)
    if not worker_cfg or not worker_cfg.is_enabled:
        return {"skipped": True}

    files_scanned = records_new = errors = 0

    for watch_dir in cfg.txt_watch_dirs:
        for file_path in _discover_files(watch_dir, worker_cfg.file_patterns):
            files_scanned += 1
            try:
                n = await _process_file(file_path, app_id, cfg, patterns, db)
                records_new += n
            except Exception as e:
                errors += 1
                log.error("file_processing_failed", file=str(file_path), error=str(e))

    return {"files_scanned": files_scanned, "records_new": records_new, "errors": errors}


async def _process_file(file_path, app_id, cfg, patterns, db) -> int:
    # Lấy last_byte từ MariaDB
    state = await get_collector_state(db, app_id, str(file_path))
    from_byte = state.last_byte if state else 0
    file_size = file_path.stat().st_size

    # File rotation: file bị truncate/xóa rồi tạo lại → size nhỏ hơn last_byte
    if file_size < from_byte:
        log.info("file_rotated_detected", file=str(file_path),
                 last_byte=from_byte, current_size=file_size)
        from_byte = 0  # Đọc lại từ đầu file mới

    if from_byte >= file_size:
        return 0  # Không có gì mới

    # Đọc phần mới
    with open(file_path, encoding="utf-8", errors="ignore") as f:
        f.seek(from_byte)
        content = f.read()
        current_byte = f.tell()

    # Parse
    records = parse_file_chunk(content, str(file_path), app_id, patterns)
    if not records:
        # Vẫn cập nhật last_byte để không đọc lại phần text không parse được
        await upsert_collector_state(db, app_id, str(file_path), current_byte, file_size, 0)
        return 0

    # Bulk index vào ES
    await _bulk_index(records, cfg, app_id)

    # Update state
    await upsert_collector_state(db, app_id, str(file_path), current_byte, file_size, len(records))
    return len(records)
```

## ES document mapping (Elasticsearch index template)

```json
{
  "index_patterns": ["vst-txt-logs*"],
  "template": {
    "mappings": {
      "properties": {
        "@timestamp":  {"type": "date"},
        "app_id":      {"type": "keyword"},
        "log_type":    {"type": "keyword"},
        "log_level":   {"type": "keyword"},
        "error_type":  {"type": "keyword"},
        "severity":    {"type": "keyword"},
        "source_file": {"type": "keyword"},
        "module":      {"type": "keyword"},
        "tieu_de":     {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
        "message":     {"type": "text"},
        "noi_dung":    {"type": "text"},
        "ip_target":   {"type": "keyword"},
        "raw_body":    {"type": "text", "index": false}
      }
    }
  }
}
```

## Phân chia trách nhiệm giữa hai bảng config

| Bảng | Field | Trách nhiệm |
|---|---|---|
| `datasource_configs` | `txt_watch_dirs` | **Nguồn truth** — thư mục nào cần watch cho app_id này |
| `worker_configs` | `file_patterns` | Pattern lọc file (*.txt, *.log) |
| `worker_configs` | `schedule_cron` | Cron schedule của APScheduler |
| `worker_configs` | `batch_size` | Số doc per bulk request |
| `worker_configs` | `is_enabled` | Bật/tắt collection cho từng app |

**Quy tắc**: `watch_dirs` **chỉ** đọc từ `datasource_configs.txt_watch_dirs`.
`worker_configs.watch_dirs` field **không dùng** (để tránh nhầm lẫn).
Xem thêm ADR-003 trong `docs/04_adr/`.

## Lưu ý quan trọng

1. **Idempotency**: `_id = MD5(timestamp + body[:100])` — chạy lại không tạo duplicate
2. **State persistence**: `last_byte` lưu trong MariaDB, không mất khi restart container
3. **File rotation**: nếu `file_size < last_byte` → file đã rotate → reset `last_byte = 0` và log `file_rotated_detected`
4. **Encoding**: luôn dùng `errors="ignore"` khi đọc file — log có thể chứa bytes không hợp lệ
5. **Error isolation**: lỗi một file không dừng toàn bộ collection cycle
6. **Batch size**: index 100 docs/batch, không index từng doc một (quá chậm)
7. **last_byte update khi không có record**: vẫn phải update để tránh đọc lại text không parse được
