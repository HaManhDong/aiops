from __future__ import annotations

import json


def make_event(event_type: str, data: dict | str) -> str:
    """Format SSE event: 'event: type\\ndata: {...}\\n\\n'"""
    if isinstance(data, str):
        payload = data
    else:
        payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


def step_event(text: str) -> str:
    return make_event("step", {"text": text})


def token_event(token: str) -> str:
    return make_event("token", {"token": token})


def es_query_event(source: str, index: str, es_url: str, body: dict) -> str:
    return make_event("es_query", {"source": source, "index": index, "es_url": es_url, "body": body})


def server_table_event(servers: list[dict]) -> str:
    return make_event("server_table", {"servers": servers})


def log_stats_event(by_level: list, top_errors: list) -> str:
    return make_event("log_stats", {"by_level": by_level, "top_errors": top_errors})


def done_event(
    session_id: str,
    intent: str,
    latency_ms: int,
    sources_used: list | None = None,
) -> str:
    return make_event("done", {
        "session_id": session_id,
        "intent": intent,
        "latency_ms": latency_ms,
        "sources_used": sources_used or [],
    })


def error_event(code: str, message: str) -> str:
    return make_event("error", {"code": code, "message": message})


def requires_input_event(app_id: str, message: str) -> str:
    return make_event("requires_input", {
        "type": "server_input_form",
        "app_id": app_id,
        "message": message,
        "form": {
            "fields": [
                {"name": "ip", "label": "IP Address", "required": True},
                {"name": "hostname", "label": "Hostname", "required": True},
                {"name": "os", "label": "OS", "required": False},
            ],
            "allow_multiple": True,
        },
    })


def incident_draft_event(title: str, app_id: str, severity: str, description: str) -> str:
    from datetime import datetime, timezone
    return make_event("incident_draft", {
        "title": title,
        "app_id": app_id,
        "severity": severity,
        "description": description[:500],
        "incident_time": datetime.now(timezone.utc).isoformat(),
    })
