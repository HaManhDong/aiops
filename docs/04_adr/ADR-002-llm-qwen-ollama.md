# ADR-002: Dùng Qwen 2.5 14B qua Ollama (on-premise)

**Trạng thái**: Accepted
**Ngày**: 2026-04-23
**Tác giả**: Team AIOps

## Bối cảnh

Hệ thống cần LLM để:
1. Phân loại intent từ câu hỏi ngôn ngữ tự nhiên
2. Tổng hợp câu trả lời từ log/metrics data

Các lựa chọn đã xem xét:
- Claude API / GPT-4 (cloud)
- Qwen 2.5 14B qua Ollama (on-premise)
- Llama 3.1 8B qua Ollama (on-premise)

## Quyết định

Dùng **Qwen 2.5 14B** qua **Ollama** chạy on-premise trên server VST.

## Lý do

1. **Bảo mật dữ liệu**: log hệ thống ERP chứa thông tin nhạy cảm (lỗi nghiệp vụ, stack trace, IP nội bộ). Không thể gửi ra cloud.
2. **Không giới hạn ngôn ngữ**: Qwen 2.5 14B có năng lực đa ngôn ngữ tốt trong nhóm model open-source tại thời điểm chọn (2026-Q1), phù hợp cho đội vận hành dùng ngôn ngữ tự nhiên lẫn thuật ngữ kỹ thuật.
3. **Chi phí**: không phụ thuộc API key, không tốn tiền per-token sau khi deploy.
4. **Ollama**: đơn giản nhất để self-host, có HTTP API tương thích, hỗ trợ streaming.

## Hậu quả

| Hạn chế | Giảm thiểu |
|---|---|
| Cần GPU server (≥16GB VRAM) | VST đã có server GPU sẵn |
| Latency cao hơn cloud API (~2-5s first token) | Streaming SSE — user thấy token ngay |
| Model không update tự động | Review model mỗi 6 tháng, upgrade nếu có bản tốt hơn |
| Ollama URL hardcode nguy hiểm | Đọc từ env var `OLLAMA_URL` — xem skill `02_agent_layer.md` |

## Thay đổi tương lai

Nếu VST cho phép gửi log ra ngoài hoặc cần chất lượng cao hơn, có thể chuyển sang Claude API với on-prem proxy.
