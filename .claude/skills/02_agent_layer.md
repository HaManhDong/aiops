# Skill: AI Agent Layer (M5 → M6 → M7)

## ⚠️ Quy tắc bắt buộc: KHÔNG hardcode magic number trong agents

**Mọi threshold, limit, window size phải đến từ một trong hai nguồn:**

### A. System-wide defaults → `app/config.py` (Settings, đọc từ env)

```python
# Thêm vào class Settings trong config.py:
dedup_jaccard_threshold: float = 0.72
metric_cpu_warn: float = 75.0
metric_cpu_crit: float = 90.0
es_agg_topk: int = 10
default_lookback_fallback: str = "now-2h"
# ... xem config.py để biết đầy đủ
```

Dùng trong code:
```python
from app.config import settings
# Thay vì: if cpu >= 90.0:
if cpu >= settings.metric_cpu_crit:
```

### B. Per-app overrides → `datasource_configs.analysis_thresholds` (JSON trong MariaDB)

Truy cập qua `AppThresholds.from_service(cfg)` (trong `config_service.py`):

```python
from app.services.config_service import AppThresholds

cfg = await config_svc.get_service(app_id)
thr = AppThresholds.from_service(cfg)

# Các keys có thể override trong analysis_thresholds JSON:
# cpu_warn, cpu_crit, ram_warn, ram_crit, disk_warn, disk_crit
# severity_critical_errors, severity_high_errors, severity_medium_errors
# es_agg_topk, anomaly_lookback, capacity_planning_days

if cpu >= thr.cpu_crit:        # ✅ per-app override → env default
    mark_critical()
```

**Thứ tự ưu tiên:** per-app DB > env var > Python default trong Settings

### Quy tắc bắt buộc

| Loại giá trị | Làm gì |
|---|---|
| Ngưỡng metric (CPU/RAM/Disk) | `AppThresholds.from_service(cfg)` |
| Limit hiển thị (max_logs, max_signals) | `settings.display_max_*` |
| Time window mặc định | `settings.default_lookback_*` |
| Query safety (max_docs, rate_limit) | `settings.*` qua lazy function |
| Evidence weights | `settings.evidence_weight_*` |
| Dedup threshold | `settings.dedup_jaccard_threshold` |

**KHÔNG làm:**
```python
# ❌ WRONG — magic number baked in
if cpu >= 90.0: ...
_ES_AGG_TOPK = 10
now-7d_lookback = "now-7d"
threshold = 0.72

# ❌ WRONG — module-level constant không qua settings
_WARN_CPU = 75.0
_RATE_LIMIT = 30
```



## Tổng quan luồng
```
ChatRequest
    ↓ M5: IntentClassifier  → ClassifiedIntent
    ↓ M14: ServerRegistry   → list[ServerInfo] hoặc NOT_FOUND
    ↓ M6: QueryExecutor     → Dict[str, Any] (raw context)
    ↓ M16: ServerMetricsAgg → Dict[hostname, ServerData]  (chạy song song M6)
    ↓ M7: AnswerSynthesizer → AsyncGenerator[str]  (streaming tokens)
```

## M5 — Intent Classifier

### File: `agents/intent.py`

Intent types:
```python
class QueryIntent(str, Enum):
    HEALTH_CHECK    = "HEALTH_CHECK"     # "hệ thống ổn không?"
    ERROR_LOOKUP    = "ERROR_LOOKUP"     # "ERP có lỗi gì?"
    METRIC_QUERY    = "METRIC_QUERY"     # "CPU server nào cao?"
    ALERT_STATUS    = "ALERT_STATUS"     # "có alert nào active không?"
    ROOT_CAUSE      = "ROOT_CAUSE"       # "tại sao website chậm lúc 2h?"
    TREND_ANALYSIS  = "TREND_ANALYSIS"   # "tuần này lỗi nhiều hơn tuần trước?"
    SERVER_QUERY    = "SERVER_QUERY"     # "ERP đang chạy trên server nào?"
```

Prompt template (lưu trong DB hoặc file — KHÔNG hardcode trong code):
```
INTENT_CLASSIFY_PROMPT = """
Phân tích câu hỏi tiếng Việt về hệ thống IT và trả về JSON:
{
  "intent": <HEALTH_CHECK|ERROR_LOOKUP|METRIC_QUERY|ALERT_STATUS|ROOT_CAUSE|TREND_ANALYSIS|SERVER_QUERY>,
  "app_id": <"erp"|"mvs"|"website"|null>,
  "time_range": <"now-1h"|"now-6h"|"now-24h"|"now-7d">,
  "keywords": [<từ khóa kỹ thuật>]
}

Quy tắc time_range:
- "vừa rồi", "mới xảy ra"   → now-1h
- "6 giờ", "sáng nay"       → now-6h
- "hôm nay", không đề cập  → now-24h
- "tuần này"                → now-7d

Chỉ trả về JSON, không giải thích.

Câu hỏi: {question}
"""
```

Implementation checklist:
- [ ] Gọi Ollama với `format="json"` và `temperature=0`
- [ ] Parse JSON response, fallback nếu parse lỗi (default HEALTH_CHECK, now-24h)
- [ ] Override `app_id` từ JWT nếu user không có quyền `all`
- [ ] Langfuse span: log tokens_in, tokens_out, latency_ms, parsed_intent

## M6 — Query Executor

### File: `agents/query_executor.py`

Chạy **song song** tất cả query cần thiết cho intent:

```python
async def execute(self, intent: ClassifiedIntent) -> dict:
    tasks = {}

    # ES log query — luôn chạy
    tasks["es_logs"] = self._query_es_logs(intent)
    tasks["es_business_alerts"] = self._query_business_alerts(intent)

    # Chỉ chạy khi cần metrics
    if intent.intent in (HEALTH_CHECK, METRIC_QUERY, ROOT_CAUSE):
        tasks["prometheus"] = self._query_prometheus(intent)

    # Chỉ chạy khi cần alert status
    if intent.intent in (HEALTH_CHECK, ALERT_STATUS, ROOT_CAUSE):
        tasks["kibana_alerts"] = self._query_kibana_alerts(intent)

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    return {
        name: (None if isinstance(r, Exception) else r)
        for name, r in zip(tasks.keys(), results)
    }
```

Query ES (NL → DSL):
```python
async def _query_es_logs(self, intent: ClassifiedIntent) -> dict:
    cfg = await self._config_svc.get_datasource(intent.app_id)
    # cfg.elasticsearch_url, cfg.log_index_pattern đến từ DB
    body = {
        "query": {"bool": {"must": [
            {"range": {"@timestamp": {"gte": intent.time_range}}},
            {"terms": {"log_level": ["ERROR", "CRITICAL", "WARNING"]}},
            *([{"term": {"app_id": intent.app_id}}] if intent.app_id else []),
            *([{"multi_match": {"query": " ".join(intent.keywords),
                                "fields": ["message", "tieu_de", "noi_dung"]}}]
              if intent.keywords else []),
        ]}},
        "size": 10,
        "sort": [{"@timestamp": "desc"}],
        "aggs": {
            "by_error_type": {"terms": {"field": "error_type", "size": 10}},
            "over_time":     {"date_histogram": {"field": "@timestamp",
                                                  "calendar_interval": "1h"}},
        }
    }
    # Timeout riêng cho mỗi source — không để một source block cả pipeline
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{cfg.elasticsearch_url}/{cfg.log_index_pattern}/_search",
            json=body,
            headers={"Authorization": f"ApiKey {cfg.elasticsearch_api_key}"},
        )
        resp.raise_for_status()
    return _parse_es_response(resp.json())
```

Query Prometheus (gọi thẳng, không qua ES):
```python
async def _query_prometheus(self, intent: ClassifiedIntent) -> dict:
    cfg = await self._config_svc.get_datasource(intent.app_id)
    queries = {
        "cpu":      'topk(5, avg by(instance)(rate(node_cpu_seconds_total{mode!="idle"}[5m])) * 100)',
        "memory":   'topk(5, (1 - node_memory_MemAvailable_bytes/node_memory_MemTotal_bytes) * 100)',
        "http_err": 'sum by(instance)(rate(http_requests_total{status=~"5.."}[5m]))',
    }
    results = {}
    async with httpx.AsyncClient(timeout=5) as client:
        for name, q in queries.items():
            try:
                r = await client.get(f"{cfg.prometheus_url}/api/v1/query", params={"query": q})
                results[name] = r.json()["data"]["result"]
            except Exception as e:
                log.warning("prometheus_query_failed", query=name, error=str(e))
                results[name] = None
    return results
```

## M7 — Answer Synthesizer

### File: `agents/synthesizer.py`

```python
from app.config import settings   # Pydantic Settings đọc từ env var OLLAMA_URL

class AnswerSynthesizer:
    """
    OLLAMA_URL và model name KHÔNG được hardcode.
    Đọc từ settings (env var) — tránh vi phạm Rule 1.

    settings.ollama_url  → env var OLLAMA_URL (e.g. http://ollama.vst.internal:11434)
    settings.ollama_model → env var OLLAMA_MODEL (default: qwen2.5:14b)
    """

    async def synthesize_stream(
        self,
        question: str,
        context: dict,
        intent: ClassifiedIntent,
        user_role: str,
    ) -> AsyncGenerator[str, None]:
        """
        Stream tokens từ LLM về client.
        user_role ảnh hưởng đến mức độ chi tiết (manager: ẩn stack trace).
        """
        context_text = self._format_context(context, user_role)
        prompt = f"Câu hỏi: {question}\n\nDữ liệu:\n{context_text}"

        system_prompt = _load_system_prompt()   # đọc từ file prompts/system_vi.txt

        # Ollama streaming — URL và model đến từ settings, không hardcode
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST",
                f"{settings.ollama_url}/api/chat",
                json={
                    "model": settings.ollama_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": prompt},
                    ],
                    "stream": True,
                    "options": {"temperature": 0.1},
                }
            ) as response:
                async for line in response.aiter_lines():
                    if line:
                        chunk = json.loads(line)
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            yield token


def _load_system_prompt() -> str:
    """Đọc system prompt từ file — không hardcode string trong code."""
    prompt_path = Path(__file__).parent.parent / "prompts" / "system_vi.txt"
    return prompt_path.read_text(encoding="utf-8")
```

### Thêm vào `services/api/app/config.py` (Pydantic Settings)

```python
class Settings(BaseSettings):
    # ... các field khác ...

    # Ollama
    ollama_url: str = "http://ollama.vst.internal:11434"
    ollama_model: str = "qwen2.5:14b"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
```

SYSTEM_PROMPT_VI (lưu trong file `prompts/system_vi.txt`, không hardcode):
```
Bạn là AI Assistant phân tích hệ thống IT cho VST.
Trả lời bằng tiếng Việt, ngắn gọn, có cấu trúc rõ ràng.

Nguyên tắc bắt buộc:
- Chỉ dựa vào dữ liệu được cung cấp, không suy đoán
- Nếu không có dữ liệu → nói rõ "Không tìm thấy thông tin liên quan"
- Ưu tiên nêu vấn đề nghiêm trọng (CRITICAL/ERROR) trước
- Luôn kèm timestamp và tên module/service cụ thể
- Cuối câu trả lời: đề xuất hành động tiếp theo nếu phát hiện vấn đề
```

## Conversation state (M15)

Ba trạng thái cần xử lý trong `routers/chat.py`:

```python
class ConvState(str, Enum):
    NORMAL               = "NORMAL"
    WAITING_SERVER_INPUT = "WAITING_SERVER_INPUT"
    CONFIRMING_SERVER    = "CONFIRMING_SERVER"

# Redis key: conv:{session_id}
# TTL: 1800 giây (30 phút)
# Value: JSON serialized ConversationContext dataclass
```

Lưu vào Redis: `await redis.setex(f"conv:{session_id}", 1800, ctx.json())`
Đọc từ Redis: `raw = await redis.get(f"conv:{session_id}")`

## Langfuse tracing

Mỗi bước phải có span riêng:
```python
from langfuse import Langfuse
langfuse = Langfuse()  # đọc LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY từ env

trace = langfuse.trace(name="chat_request", user_id=user_id, session_id=session_id)

# Trong mỗi agent:
span = trace.span(name="intent_classification")
intent = await classifier.classify(question)
span.end(output={"intent": intent.intent, "app_id": intent.app_id},
         usage={"input": tokens_in, "output": tokens_out})
```
