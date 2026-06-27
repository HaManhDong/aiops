# Reasoning-Native AI System — Phân Tích Kiến Trúc
**Ngày:** 2026-05-12  
**Reviewer:** Claude Sonnet 4.6  
**Câu hỏi trả lời:** Hệ thống hiện tại có phải là reasoning-native không? Cần gì để thực sự là?

---

## Kết luận thẳng: Không phải reasoning-native

Hệ thống hiện tại là **"Code-Orchestrated LLM"** — code quyết định mọi thứ, LLM là oracle được gọi khi cần. Đây là pattern khác về bản chất so với reasoning-native.

Nhưng điều thú vị là: các building blocks (`HypothesisGraph`, `EvidenceScorer`, `CapabilityRegistry`, `ReasoningTrace`) được thiết kế **đúng hướng** — chúng chỉ đang bị đặt sai vị trí trong luồng.

---

## Phần 1: Diagnosis — Vấn Đề Nằm Ở Đâu

### 1.1 Đọc luồng thực của ExpertAgent

```python
# expert_agent.py — đây là toàn bộ "reasoning" của hệ thống

for iteration in range(MAX_AGENTIC_ITERATIONS):   # ← capped cứng 2 lần
    
    # LLM gọi 1: "Hãy lên kế hoạch lấy dữ liệu gì"
    plan = await llm.generate_json(prompt, system=_PLAN_SYSTEM)
    # Code parse JSON ra danh sách queries
    queries = [CapabilityRegistry.normalize_query_spec(q) for q in plan["queries"]]
    
    # Code execute tất cả queries song song
    new_data = await executor.execute_selective(queries, ...)
    gathered.update(new_data)

# Sau khi vòng lặp kết thúc:
# LLM gọi 2: "Hãy tổng hợp phân tích từ toàn bộ data đã thu"
full_analysis = await llm.generate_stream(messages)

# Code parse text output để extract hypothesis:
hyp_graph = HypothesisGraph.from_analysis_text(full_analysis)  # ← REGEX PARSING

# Code score evidence và update confidence:
scored_evidence = score_log_errors(top_errors, ...)
for ev in scored_evidence:
    for h in hyp_graph.get_open():
        hyp_graph.add_evidence(h.id, ev.id, supports=True, weight=ev.total_score * 0.15)
```

**Nhận xét:** LLM được gọi 2 lần. Lần 1 là planning, lần 2 là synthesis. Ở giữa, CODE thực thi mọi thứ. LLM không tham gia vào quá trình điều tra — nó chỉ plan đầu rồi conclude cuối.

### 1.2 Vấn đề kiến trúc căn bản

**HypothesisGraph được điền bằng regex parse text của LLM:**

```python
# hypothesis_graph.py:121
@classmethod
def from_analysis_text(cls, text: str) -> "HypothesisGraph":
    candidates = _extract_hypothesis_candidates(text)  # ← regex tìm pattern
    for i, desc in enumerate(candidates):
        base_conf = max(0.35, 0.65 - i * 0.15 / max(n, 1))  # ← vị trí trong text = confidence
```

LLM **đã viết xong câu trả lời** trước khi hypothesis được extract. Confidence không phải là mức độ tin tưởng của LLM vào hypothesis — nó là thứ tự xuất hiện trong đoạn văn. Đây không phải reasoning, đây là **information extraction sau khi đã conclude**.

**EvidenceScorer không ảnh hưởng gì đến reasoning:**

Evidence scoring xảy ra **sau** khi LLM đã viết xong analysis. Score không được feed ngược lại cho LLM để nó điều chỉnh kết luận. Đây là decoration, không phải reasoning loop.

### 1.3 Sơ đồ luồng thực vs luồng cần có

**Hiện tại — "Code-Orchestrated LLM":**
```
Code: "Lên kế hoạch"
  LLM → {need_data: true, queries: [...]}
Code: Fetch data song song
Code: "Tổng hợp"
  LLM → [text output: "Nguyên nhân có thể là X, Y, Z"]
Code: Regex parse text → hypothesis objects
Code: Score evidence → update hypothesis confidence (không ai đọc)
```

**Cần có — "Reasoning-Native":**
```
LLM: "Tôi thấy error rate cao. Hypothesis: disk I/O → DB lock"
LLM calls tool: get_disk_metrics()
  → iowait 23%, saturation 89%
LLM: "Disk đang bão hòa. Confidence disk hypothesis: 0.8. Cần kiểm tra DB"
LLM calls tool: get_db_slow_queries()
  → 47 slow queries > 5s trong 15 phút qua
LLM: "Confirmed. Disk I/O → DB lock → application timeout"
LLM: [streams final answer with evidence chain]
```

Sự khác biệt: **LLM nắm quyền điều khiển loop**. Mỗi tool call result ảnh hưởng trực tiếp đến reasoning tiếp theo. Không có vòng lặp cứng 2 lần — LLM dừng khi đủ tự tin.

---

## Phần 2: Tại Sao Điều Này Quan Trọng Với AI SRE

### 2.1 SRE investigation là multi-hop reasoning

Một SRE thực sự điều tra sự cố theo kiểu này:

```
Quan sát: API timeout
Hypothesis 1: DB chậm?
  → Check: DB latency 3.2s (bình thường 0.1s) → XÁC NHẬN
Hypothesis 2: DB chậm do gì? Network? CPU? Lock?
  → Check: DB CPU 15% (bình thường) → loại trừ CPU
  → Check: Lock wait count tăng 450% → XÁC NHẬN lock
Hypothesis 3: Lock do gì? Batch job? Long transaction?
  → Check: Long running transactions → thấy batch export đang chạy
KẾT LUẬN: Batch export job giữ lock → DB timeout → API timeout
```

Mỗi bước **phụ thuộc vào kết quả bước trước**. Đây là **adaptive investigation** — điều tra thích nghi. Hệ thống hiện tại không làm được vì:
- Query plan được quyết định trước khi có data
- Các query chạy song song, không theo thứ tự logic
- LLM không thấy kết quả từng bước — chỉ thấy dump cuối cùng

### 2.2 Qwen 2.5 CÓ hỗ trợ native tool calling

Đây là điểm quan trọng nhất chưa được khai thác: **Qwen 2.5-Instruct hỗ trợ OpenAI function calling API**.

```python
# Hiện tại - generate_json chỉ trả text
plan_raw = await llm.generate_json(prompt, system=_PLAN_SYSTEM)

# Có thể làm - native tool calling
response = await openai_client.chat.completions.create(
    model="Qwen/Qwen2.5-14B-Instruct",
    messages=messages,
    tools=[                           # ← Qwen 2.5 hiểu cái này
        {
            "type": "function",
            "function": {
                "name": "fetch_logs",
                "description": "Lấy log lỗi từ Elasticsearch",
                "parameters": { ... }
            }
        }
    ],
    tool_choice="auto"               # LLM tự quyết định gọi tool nào
)
```

Khi dùng native tool calling, LLM **không output text plan mà code parse** — LLM output structured `tool_call` objects mà OpenAI client handle trực tiếp. Reliable hơn, không cần regex parse, không cần `_parse_plan()`.

### 2.3 "Thinking" trong reasoning-native

Reasoning-native models thường có nội dung reasoning ẩn trước khi output. Trong kiến trúc hiện tại, `thinking` field trong plan response có nhưng chỉ để log:

```python
# expert_agent.py:201
thinking = plan.get("thinking", "")
if thinking:
    yield {"type": "step", "text": f"🔍 {thinking}"}  # show to user nhưng không dùng
```

`thinking` đang được dùng như UX text, không phải như reasoning state. Trong reasoning-native design, thinking là **intermediate belief state** ảnh hưởng đến action tiếp theo.

---

## Phần 3: Thiết Kế Reasoning-Native Cho Hệ Thống Này

### 3.1 Kiến trúc đề xuất — "ReAct + Belief Propagation"

**ReAct** (Reasoning + Acting) là pattern chuẩn cho reasoning-native agents. Kết hợp với belief propagation từ hypothesis graph:

```
┌─────────────────────────────────────────────────────┐
│          REASONING LOOP (LLM-driven)                │
│                                                      │
│  ┌─ Belief State ──────────────────────────────┐   │
│  │  hypotheses: [H1: 0.6, H2: 0.4, H3: 0.3]  │   │
│  │  evidence_chain: [e1, e2, ...]              │   │
│  │  uncertainty: 0.4  (cần thêm data)         │   │
│  └────────────────────┬────────────────────────┘   │
│                       │ informs                      │
│  ┌─ LLM Reasoning ───▼────────────────────────┐   │
│  │  "H1 có confidence 0.6 nhưng chưa chắc.   │   │
│  │   Cần check DB lock count để confirm."      │   │
│  └────────────────────┬────────────────────────┘   │
│                       │ calls tool                   │
│  ┌─ Tool Execution ───▼────────────────────────┐   │
│  │  fetch_db_metrics() → lock_wait: 450%↑     │   │
│  └────────────────────┬────────────────────────┘   │
│                       │ observe result               │
│  ┌─ Belief Update ────▼────────────────────────┐   │
│  │  H1 confidence: 0.6 → 0.85  (confirmed)    │   │
│  │  uncertainty: 0.4 → 0.15                    │   │
│  │  → enough to conclude? YES → exit loop      │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### 3.2 Interface cần thêm vào LLMProvider

```python
# providers/llm/base.py — thêm abstract method

@abstractmethod
async def generate_with_tools(
    self,
    messages: list[dict],
    tools: list[dict],              # OpenAI function schemas
    tool_choice: str = "auto",
    temperature: float = 0.1,
    generation_name: str = "tool_call",
) -> AsyncGenerator[ToolCallEvent, None]:
    """Streaming call with tool use capability.

    Yields ToolCallEvent which can be:
    - {"type": "tool_call", "name": str, "arguments": dict, "call_id": str}
    - {"type": "token", "content": str}
    - {"type": "done"}
    """
```

```python
# providers/llm/openai_compatible.py — implement

async def generate_with_tools(self, messages, tools, tool_choice="auto", ...):
    response = await self._client.chat.completions.create(
        model=self._model,
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
        stream=True,
    )
    async for chunk in response:
        delta = chunk.choices[0].delta
        if delta.tool_calls:
            for tc in delta.tool_calls:
                yield {"type": "tool_call", "name": tc.function.name,
                       "arguments": json.loads(tc.function.arguments),
                       "call_id": tc.id}
        elif delta.content:
            yield {"type": "token", "content": delta.content}
```

### 3.3 ReAct Loop thay thế ExpertAgent hiện tại

```python
class ReActExpertAgent:
    """Reasoning-native expert agent using ReAct pattern.

    LLM holds the reasoning loop. Tools are native function calls.
    Belief state (HypothesisGraph) is maintained across iterations.
    Loop terminates when LLM is confident enough, not after N iterations.
    """

    MAX_ITERATIONS = 8           # không phải 2 — LLM tự dừng khi đủ tin
    CONFIDENCE_THRESHOLD = 0.75  # LLM kết luận khi top hypothesis confirmed

    async def run(
        self,
        user_message: str,
        session_context: dict,
        app_id: str,
        executor_factory,
        ...
    ) -> AsyncGenerator[dict, None]:

        belief = HypothesisGraph()    # belief state — maintained across loop
        evidence_chain: list[ScoredEvidence] = []
        messages = self._build_initial_messages(user_message, session_context, app_id)
        tools = self._build_tool_schemas(app_id)    # từ CapabilityRegistry

        for iteration in range(self.MAX_ITERATIONS):

            # LLM drives: decides what to do next based on current belief
            belief_context = self._format_belief(belief, evidence_chain)
            messages[-1]["content"] += f"\n\n[Belief state hiện tại]\n{belief_context}"

            async for event in (await get_llm_provider()).generate_with_tools(
                messages, tools, temperature=0.1
            ):
                if event["type"] == "tool_call":
                    # LLM called a tool — execute it
                    tool_name = event["name"]
                    tool_args = event["arguments"]
                    yield {"type": "step", "text": f"Đang kiểm tra {tool_name}..."}

                    result = await self._execute_tool(tool_name, tool_args, executor_factory, app_id)

                    # Update belief based on new evidence — BEFORE next LLM call
                    new_evidence = self._extract_evidence(result, tool_name)
                    for ev in new_evidence:
                        evidence_chain.append(ev)
                        self._update_belief(belief, ev)    # belief propagation HERE

                    # Feed result back to LLM for next reasoning step
                    messages.append({
                        "role": "tool",
                        "tool_call_id": event["call_id"],
                        "content": json.dumps(result, ensure_ascii=False)[:3000]
                    })

                    if belief.get_confirmed():
                        # Top hypothesis confirmed — no need for more data
                        break

                elif event["type"] == "token":
                    yield {"type": "token", "token": event["content"]}

                elif event["type"] == "done":
                    yield {"type": "hypothesis_graph", "data": belief.to_dict()}
                    return

            # Check termination: LLM didn't request any tools → has enough info
            if not any(m.get("role") == "tool" for m in messages[-3:]):
                break

        # LLM streams final analysis with full belief state as context
        yield {"type": "hypothesis_graph", "data": belief.to_dict()}
```

### 3.4 Tool Schemas từ CapabilityRegistry

`CapabilityRegistry` đã đúng hướng — chỉ cần thêm method `to_openai_tool_schemas()`:

```python
# orchestrator/capability_registry.py

@staticmethod
def to_openai_tool_schemas(app_id: str) -> list[dict]:
    """Return capability catalogue as OpenAI function schemas for tool calling."""
    return [
        {
            "type": "function",
            "function": {
                "name": cap.name,
                "description": cap.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "time_range": {
                            "type": "string",
                            "description": "Elasticsearch date math, vd 'now-1h', 'now-30m'",
                        },
                        "keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Từ khoá lọc log",
                        },
                    },
                    "required": ["time_range"],
                },
            },
        }
        for cap in CapabilityRegistry.list_all()
        if cap.backend not in ("db",)  # không expose internal DB tools
    ]
```

### 3.5 Belief Propagation — HypothesisGraph dùng đúng cách

Thay vì `from_analysis_text()` (parse sau), dùng **hypothesis seeding trước**:

```python
# Bước 1: LLM generates initial hypotheses từ câu hỏi (TRƯỚC khi fetch data)
initial_hypotheses = await llm.generate_json(
    prompt=f"Với triệu chứng: '{user_message}', liệt kê 3-5 hypothesis root cause",
    system="Trả về JSON: {hypotheses: [{id, description, initial_confidence}]}"
)
for h_data in initial_hypotheses["hypotheses"]:
    belief.add(Hypothesis(
        id=h_data["id"],
        description=h_data["description"],
        confidence=h_data.get("initial_confidence", 0.4)
    ))

# Bước 2: Với mỗi tool result, LLM cập nhật belief
# LLM không chỉ nói "data cho thấy X" mà phải nói
# "hypothesis H1 tăng confidence vì... H2 giảm vì..."
```

---

## Phần 4: Phân Tích Trung Thực — Qwen 2.5 14B Có Đủ Không

Đây là câu hỏi thực tế nhất. Câu trả lời trung thực:

### Qwen 2.5 14B strengths (relevant)
- **Hỗ trợ native function calling** qua OpenAI API format — đây là điều kiện cần
- **Vietnamese competent** — có thể reason về log tiếng Việt
- **Context 8192 tokens** — đủ cho ReAct loop với 4-5 tool calls
- **Tool-use training** — Qwen 2.5-Instruct được fine-tune với tool use tasks

### Qwen 2.5 14B limitations (honest)
- **Không có extended thinking** như Claude 3.7 hay OpenAI o1 — không có internal reasoning chain ẩn
- **14B parameter** — nhỏ hơn đáng kể so với frontier models, multi-hop reasoning kém hơn
- **ReAct reliability** — với model nhỏ, LLM có thể gọi sai tool, quên context giữa các turns
- **Calibration** — confidence 0.8 của Qwen 14B không đáng tin bằng của GPT-4o

### Khuyến nghị thực tế

**Dùng 2-tier architecture:**

```
Tier 1: Fast Path — Qwen 2.5 14B (on-premise, 3-5 giây)
  → Dùng cho queries thông thường (HEALTH_CHECK, METRIC_QUERY)
  → Simple tool calling: 1-2 tools, không cần deep reasoning
  → Hiện tại: hệ thống đang dùng đúng cho tier này

Tier 2: Deep Reasoning — Cloud LLM với thinking (khi ROOT_CAUSE, INCIDENT_ANALYSIS)
  → Claude claude-sonnet-4-6 extended thinking / GPT-4o / Qwen 2.5 72B
  → Full ReAct loop với 5-8 tool calls
  → Gọi khi: user hỏi root cause, khi anomaly detected, khi incident critical
```

**Short-term (có thể làm với Qwen 14B):**
- Tăng `MAX_AGENTIC_ITERATIONS` từ 2 → 5
- Implement `generate_with_tools()` dùng native function calling
- Feed belief state (hypothesis confidence) vào prompt của mỗi iteration
- LLM sẽ reasoning tốt hơn vì thấy belief state evolving

**Medium-term (thêm cloud LLM):**
- Thêm `providers/llm/thinking_provider.py` cho Claude/o3
- Dùng provider này chỉ cho `ROOT_CAUSE` và `INCIDENT_ANALYSIS` intents
- Qwen 14B vẫn xử lý 90% queries thông thường

---

## Phần 5: Migration Path — Không Cần Rewrite

### Step 1 (1-2 ngày): Thêm `generate_with_tools()` vào LLMProvider

Chỉ implement trong `openai_compatible.py` và `openai.py`. Ollama provider giữ nguyên (không hỗ trợ tool calling tốt).

### Step 2 (2-3 ngày): ExpertAgent — Hypothesis-First Design

Tách ExpertAgent thành 2 mode:
- `mode="classic"` — giữ nguyên current behavior (fallback khi model không support tools)
- `mode="react"` — ReAct loop với native tool calling

```python
class ExpertAgent:
    async def run(self, ..., mode: str = "react"):
        if mode == "react":
            async for event in self._run_react(...):
                yield event
        else:
            async for event in self._run_classic(...):
                yield event
```

### Step 3 (1 ngày): Belief-Propagation trong ReAct

Move `EvidenceScorer` và `HypothesisGraph` vào ReAct loop (từ post-processing sang in-loop). Không cần viết lại — chỉ cần gọi chúng sớm hơn.

### Step 4 (3-5 ngày): A/B testing

Chạy song song `mode="classic"` và `mode="react"` với logging để compare:
- Accuracy (operator satisfaction)
- Latency
- Token consumption

---

## Tổng Kết

| Khía cạnh | Hiện tại | Cần có |
|---|---|---|
| Loop control | Code (cứng 2 lần) | LLM (dynamic) |
| Hypothesis generation | Post-hoc (regex parse text) | Pre-hoc (seed trước khi fetch) |
| Belief update | Sau synthesis (vô nghĩa) | Sau mỗi tool result |
| Tool selection | Code parse JSON plan | LLM native tool calling |
| Termination condition | N iterations | LLM confidence threshold |
| Evidence → next action | Không có | Belief state informs next tool |

**Các module đã build đúng hướng nhưng dùng sai thứ tự:**
- `HypothesisGraph` — đúng structure, sai timing (post → pre)
- `EvidenceScorer` — đúng logic, sai position (after → during)
- `CapabilityRegistry` — đúng abstraction, cần thêm `to_openai_tool_schemas()`
- `ReasoningTrace` — đúng concept, cần connect vào loop thật

**Đây là thay đổi kiến trúc quan trọng nhất dự án cần làm** — không phải vì code hiện tại sai, mà vì nó đang dùng LLM như một text generator thay vì một reasoner. Khi reasoning-native được implement, toàn bộ capability của ExpertAgent, HypothesisGraph, EvidenceScorer mới thực sự phát huy.
