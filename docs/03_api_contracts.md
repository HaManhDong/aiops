# API Contracts — AIOps

Base URL: `https://vst-ai.internal/api/v1`
Auth: `Authorization: Bearer <jwt_token>` (except public endpoints)
Content-Type: `application/json`

---

## Public endpoints

### POST /auth/token
Lấy JWT token.
```
Request:
  { "username": "thien.nguyen", "password": "..." }

Response 200:
  {
    "access_token": "eyJ...",
    "token_type": "bearer",
    "expires_in": 28800,
    "user": {
      "id": "usr-001",
      "username": "thien.nguyen",
      "full_name": "Nguyễn Văn Thiên",
      "role": "engineer",
      "allowed_apps": ["erp"]
    }
  }
```

### GET /health
Liveness probe.
```
Response 200: { "status": "ok", "service": "vst-ai-api", "timestamp": "..." }
```

### GET /ready
Readiness probe — kiểm tra tất cả dependencies.
```
Response 200:
  {
    "status": "ready",
    "checks": {
      "mariadb":       { "status": "ok", "latency_ms": 2 },
      "redis":         { "status": "ok", "latency_ms": 1 },
      "ollama":        { "status": "ok", "latency_ms": 180, "model": "qwen2.5:14b" },
      "elasticsearch": { "status": "ok", "latency_ms": 12 }
    }
  }

Response 503 (nếu có dependency down):
  {
    "status": "degraded",
    "checks": {
      "mariadb": { "status": "ok" },
      "ollama":  { "status": "down", "error": "Connection refused" }
    }
  }
```

---

## Chat

### POST /api/v1/chat
Gửi câu hỏi — streaming SSE response.

**session_id**: nếu không truyền, server tự tạo theo format `sess_{uuid4_hex[:12]}`.
Client nên lưu lại `session_id` từ response `done` để dùng cho request tiếp theo.
Server kiểm tra session thuộc về `user_id` trong JWT — không cho phép truy cập session của user khác.

```
Request:
  {
    "message": "ERP hôm nay có vấn đề gì không?",
    "session_id": "sess_abc123",       ← optional, tạo mới nếu thiếu
    "app_id": "erp"                    ← optional; nếu thiếu, lấy từ JWT allowed_apps
  }

Response: text/event-stream (SSE)
  event: token
  data: {"token": "Hệ", "trace_id": "trc_xyz"}

  event: token
  data: {"token": " thống", "trace_id": "trc_xyz"}

  event: done
  data: {
    "trace_id": "trc_xyz",
    "session_id": "sess_abc123",
    "intent": "HEALTH_CHECK",
    "sources_used": ["es_logs", "prometheus", "kibana_alerts"],
    "latency_ms": 3200
  }

  event: error (nếu có lỗi)
  data: { "code": "LLM_TIMEOUT", "message": "Ollama không phản hồi" }

Khi cần nhập server (server chưa có trong registry):
  event: requires_input
  data: {
    "type": "server_input_form",
    "app_id": "erp",
    "message": "Chưa có danh sách server vật lý cho ERP...",
    "form": {
      "fields": [
        {"name": "ip",       "label": "Địa chỉ IP",   "required": true},
        {"name": "hostname", "label": "Hostname",      "required": true},
        {"name": "os",       "label": "Hệ điều hành", "required": false}
      ],
      "allow_multiple": true
    }
  }
```

### GET /api/v1/chat/history?session_id=&limit=20
Server kiểm tra `session_id` thuộc về `user_id` trong JWT.
Nếu session không tồn tại hoặc thuộc user khác → 403.
```
Response 200:
  {
    "session_id": "sess_abc123",
    "messages": [
      {
        "role": "user",
        "content": "ERP hôm nay ổn không?",
        "timestamp": "2026-04-22T09:00:00Z"
      },
      {
        "role": "assistant",
        "content": "Hệ thống ERP hôm nay cơ bản ổn...",
        "timestamp": "2026-04-22T09:00:03Z",
        "trace_id": "trc_xyz"
      }
    ]
  }

Response 403 (session không thuộc user này):
  {
    "type": "https://vst-ai.internal/errors/forbidden-session",
    "title": "Không có quyền truy cập session này",
    "status": 403,
    "request_id": "req_abc123"
  }
```

---

## Server Registry

### GET /api/v1/servers?app_id=erp
```
Response 200:
  {
    "app_id": "erp",
    "status": "found",       ← found | not_found
    "servers": [
      {
        "id": 1,
        "app_id": "erp",
        "ip": "172.16.10.1",
        "hostname": "erp-app-01",
        "os": "Ubuntu 22.04",
        "description": "ERP Application Server",
        "is_active": true,
        "added_by": "thien.nguyen",
        "created_at": "2026-04-22T09:00:00Z"
      }
    ]
  }
```

### POST /api/v1/servers
Thêm server mới. Hỗ trợ thêm nhiều cùng lúc.
```
Request:
  {
    "app_id": "erp",
    "servers": [
      { "ip": "172.16.10.1", "hostname": "erp-app-01", "os": "Ubuntu 22.04" },
      { "ip": "172.16.10.2", "hostname": "erp-app-02" }
    ]
  }

Response 201:
  {
    "created": 2,
    "servers": [ ... ]
  }
```

### DELETE /api/v1/servers/{id}
Soft delete (set `is_active = false`).
```
Response 204: (no body)
```

---

## Config Management (Admin only)

### GET /api/v1/admin/datasources
```
Response 200:
  {
    "datasources": [
      {
        "app_id": "erp",
        "display_name": "Hệ thống ERP",
        "elasticsearch_url": "http://es-erp:9200",
        "log_index_pattern": "erp-*",
        "prometheus_url": "http://prom:9090",
        "kibana_url": "http://kibana:5601",
        "alert_thresholds": { "cpu_pct": 85, "error_count_1h": 10 },
        "is_active": true
      }
    ]
  }
```

### PUT /api/v1/admin/datasources/{app_id}
Cập nhật config. Tự động invalidate Redis cache.
```
Request: (bất kỳ field nào của datasource_configs)
  {
    "prometheus_url": "http://prom-new:9090",
    "alert_thresholds": { "cpu_pct": 90 }
  }

Response 200: datasource object đã cập nhật
```

### GET /api/v1/admin/datasources/{app_id}/test
Kiểm tra kết nối tới tất cả endpoint của datasource.
```
Response 200:
  {
    "app_id": "erp",
    "results": {
      "elasticsearch": { "ok": true,  "latency_ms": 15 },
      "prometheus":    { "ok": true,  "latency_ms": 8  },
      "kibana":        { "ok": false, "error": "Connection refused" }
    }
  }
```

---

## Error response format (RFC 7807)
```json
{
  "type": "https://vst-ai.internal/errors/{error-code}",
  "title": "Mô tả lỗi ngắn gọn",
  "status": 503,
  "detail": "Chi tiết kỹ thuật của lỗi",
  "request_id": "req_abc123",
  "timestamp": "2026-04-22T09:00:00Z"
}
```

Error codes:
| Code | HTTP | Mô tả |
|---|---|---|
| `es-unavailable` | 503 | Elasticsearch không phản hồi |
| `llm-timeout` | 503 | Ollama timeout |
| `invalid-token` | 401 | JWT không hợp lệ hoặc hết hạn |
| `forbidden-app` | 403 | User không có quyền xem app_id này |
| `forbidden-session` | 403 | Session không thuộc về user đang request |
| `server-not-found` | 404 | Server registry không tồn tại |
| `validation-error` | 422 | Request body không hợp lệ |
| `rate-limited` | 429 | Quá nhiều request |
