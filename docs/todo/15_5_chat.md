# Todo — Chat Intent Routing (2026-05-15)

Phân tích từ session `sess_616016492ba5` + testing 11-message routing.

---

## Root cause tổng quát

Ba lỗ hổng kiến trúc được xác định:

1. **Intent space coarse** — HEALTH_CHECK và ERROR_LOOKUP quá gần nhau về ngôn ngữ, LLM phân biệt không đáng tin cậy khi chỉ dựa vào semantic
2. **CLARIFICATION overloaded** — một intent dùng cho cả câu thực sự mơ hồ lẫn câu có thể trả lời được từ context; handler `_gen_clarification()` trả hardcoded menu, bỏ qua câu hỏi thực tế
3. **Override chain brittle** — post-LLM override là patch ad-hoc, không scale, order-dependent, không có confidence signal

## Giải pháp: Structured NLU Extraction

Thay LLM output một `intent string` → LLM output **structured JSON** gồm cả intent + slots + completeness.

Pipeline mới:
```
LLM (full history in prompt) → {intent, slots, slot_source, completeness, missing_slots}
    ├── completeness=full       → handler(intent, slots)
    ├── completeness=resolvable → điền slots từ history → handler(intent, resolved_slots)
    └── completeness=missing    → generate câu hỏi cụ thể từ missing_slots
```

---

## Các việc phải làm

### 1. `app/agents/intent.py`

**Bỏ filter hardcode trong `classify()`:**

Xoá đoạn hiện tại (dòng 239–243):
```python
recent = [h["content"] for h in history[-4:] if h.get("role") == "user"][-2:]
```

Thay bằng: format toàn bộ `history` (cả user lẫn assistant, không cắt thêm):
```python
for h in history:
    role_label = "Người dùng" if h.get("role") == "user" else "Trợ lý"
    lines.append(f"[{role_label}]: {h.get('content','').strip()}")
history_prefix = "[Lịch sử hội thoại]\n" + "\n".join(lines) + "\n\n"
```

Việc giới hạn số turn là trách nhiệm của `settings.llm_max_history_turns` (đặt ở caller `workflow.py`), không phải `classify()`.

Thêm fields vào `ClassifiedIntent`:
```python
slots: dict[str, str | None]           # target_system, action, metric, time_ref
slot_source: dict[str, str | None]     # "current" | "history:turnN" | null
completeness: str                      # "full" | "resolvable" | "missing"
missing_slots: list[str]               # tên các slot còn thiếu
```

---

### 2. `app/prompts/intent_classify.txt`

**Tách `{history}` thành placeholder riêng** (không nhét vào `{question}`):

```
Hôm nay: {current_date}
Lượt trước — intent: {last_intent}, câu hỏi: {last_question}

{history}
Câu hỏi hiện tại: {question}
```

**Thêm vào JSON schema:**
```json
"slots": {
  "target_system": "<tên service/system hoặc null>",
  "action": "<thao tác cụ thể hoặc null>",
  "metric": "<tên metric hoặc null>",
  "time_ref": "<mốc thời gian hoặc null>"
},
"slot_source": {
  "target_system": "<'current'|'history:turnN'|null>",
  "action": "<'current'|'history:turnN'|null>"
},
"completeness": "<full|resolvable|missing>",
"missing_slots": ["<tên slot còn thiếu>"]
```

**Thêm quy tắc:**

```
Quy tắc completeness:
- "full"       : tất cả slot cần thiết có trong câu hỏi hiện tại
- "resolvable" : slot thiếu trong câu hỏi nhưng tìm được trong [Lịch sử hội thoại]
                 → ghi slot_source = "history:turnN"
- "missing"    : slot cần thiết không có ở đâu — cần hỏi lại

Quy tắc slots — tra cứu theo thứ tự:
1. Câu hỏi hiện tại → slot_source = "current"
2. [Trợ lý] trong lịch sử (assistant đã confirm entity gì)
3. [Người dùng] trong lịch sử (user đã đề cập entity trước đó)
Không tìm được → slot = null, đưa vào missing_slots
```

---

### 3. `app/orchestrator/workflow.py`

**Bỏ CLARIFICATION handler hiện tại**, thay bằng logic dựa trên `completeness`:

```python
# Hiện tại — route thẳng vào hardcoded menu
if intent.intent == QueryIntent.CLARIFICATION:
    async for chunk in _gen_clarification(...): yield chunk
    return

# Thay bằng — xử lý theo completeness
if intent.completeness == "resolvable":
    # Entity resolver: điền slots thiếu từ history vào intent
    intent = _resolve_slots_from_history(intent, recent_messages)
    # Tiếp tục routing bình thường với intent đã đầy đủ slots

elif intent.completeness == "missing":
    # Generate câu hỏi cụ thể từ missing_slots
    async for chunk in _gen_targeted_clarification(
        ctx, state_mgr, request_body.message, intent.missing_slots, start_ms
    ):
        yield chunk
    return
```

**Thêm `_resolve_slots_from_history()`:**

Nhận `intent` + `recent_messages`, scan lịch sử để điền các slot có `slot_source = "history:turnN"` vào `intent.keywords` và `intent.app_ids`.

**Thay `_gen_clarification()` bằng `_gen_targeted_clarification()`:**

Nhận `missing_slots` list, generate câu hỏi cụ thể bằng LLM thay vì hardcoded menu 5 item.
Ví dụ: `missing_slots=["target_system"]` → "Bạn muốn hỏi về ảnh hưởng của restart trên service nào?"

---

### 4. `app/agents/intent.py` — parse thêm fields mới từ LLM response

Trong hàm `classify()`, sau khi `data = json.loads(raw)`, parse thêm:
```python
slots = data.get("slots", {})
slot_source = data.get("slot_source", {})
completeness = data.get("completeness", "full")
missing_slots = data.get("missing_slots", [])
```

Và gán vào `ClassifiedIntent`.

---

### 5. `app/prompts/intent_classify.txt` — cập nhật quy tắc CLARIFICATION

Quy tắc hiện tại dùng CLARIFICATION quá rộng. Sau khi có `completeness`, CLARIFICATION chỉ còn là fallback tường minh cho trường hợp LLM không thể xác định intent nào:

```
- CLARIFICATION: CHỈ dùng khi không thể xác định được intent — câu quá mơ hồ về mọi mặt.
  Trong hầu hết trường hợp, hãy chọn intent cụ thể nhất có thể và đặt completeness="missing"
  với missing_slots liệt kê phần còn thiếu.
```

---

## Không thay đổi

- Pre-LLM fast-path routes (13 routes + G3 dedup) — giữ nguyên, hoạt động tốt
- Post-LLM overrides hiện tại — giữ tạm thời trong quá trình migration, xoá dần khi `completeness` hoạt động ổn định
- `settings.llm_max_history_turns` — giới hạn window history vẫn ở đây, không thay đổi
