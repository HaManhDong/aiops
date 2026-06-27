from __future__ import annotations
import re
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone


TIMESTAMP_PATTERN = re.compile(r'\[(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})\]')
CHI_TIET_LOI_MARKER = "CHI TIẾT LỖI"


@dataclass
class ParsedLogRecord:
    doc_id: str
    timestamp: datetime
    source_file: str
    app_id: str
    log_type: str
    log_level: str
    error_type: str
    severity: str
    message: str
    tieu_de: str | None
    su_kien: str | None
    module: str | None
    noi_dung: str | None
    ip_target: str | None
    raw_body: str

    def to_es_doc(self) -> dict:
        return {
            "_id": self.doc_id,
            "@timestamp": self.timestamp.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "app_id": self.app_id,
            "log_type": self.log_type,
            "log_level": self.log_level,
            "error_type": self.error_type,
            "severity": self.severity,
            "source_file": self.source_file,
            "module": self.module,
            "message": self.message,
            "tieu_de": self.tieu_de,
            "su_kien": self.su_kien,
            "noi_dung": self.noi_dung,
            "ip_target": self.ip_target,
        }


def parse_file_chunk(
    content: str,
    file_path: str,
    app_id: str,
    error_patterns: list[dict],
) -> list[ParsedLogRecord]:
    records = []
    parts = TIMESTAMP_PATTERN.split(content)

    i = 1
    while i < len(parts) - 1:
        ts_str = parts[i].strip()
        body = parts[i + 1].strip()
        i += 2

        if not body:
            continue

        try:
            ts = datetime.strptime(ts_str, "%d/%m/%Y %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            ts = datetime.now(timezone.utc)

        record = _build_record(ts, body, file_path, app_id, error_patterns)
        records.append(record)

    return records


def _build_record(ts: datetime, body: str, file_path: str, app_id: str, error_patterns: list[dict]) -> ParsedLogRecord:
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
    for p in patterns:
        if re.search(p.get("pattern", ""), body, re.IGNORECASE):
            return p.get("error_type", "unknown"), p.get("severity", "error")
    return "unknown", "error"


def _extract(body: str, pattern: str, max_len: int = 300) -> str | None:
    m = re.search(pattern, body)
    if not m:
        return None
    return m.group(1).strip()[:max_len]


def _extract_ip(body: str) -> str | None:
    m = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d+)?)', body)
    return m.group(1) if m else None
