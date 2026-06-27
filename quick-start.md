# Quick Start — AIOps

Hướng dẫn từng bước để chạy toàn bộ hệ thống AIOps trên máy local (môi trường phát triển).

---

## Yêu cầu hệ thống

| Thành phần | Phiên bản tối thiểu | Ghi chú |
|---|---|---|
| Docker | 24+ | |
| Docker Compose | v2 (plugin) | Dùng `docker compose`, không phải `docker-compose` |
| Node.js | 18+ | Chỉ cần nếu chạy frontend ngoài Docker |
| RAM | 8 GB | 16 GB nếu chạy LLM local (Ollama) |
| Disk | 20 GB trống | Ollama model Qwen 2.5 14B ~9 GB |

> **Không cần GPU.** Ollama chạy được trên CPU (chậm hơn nhưng hoạt động).

---

## Bước 1 — Clone repo

```bash
git clone https://github.com/HaManhDong/aiops.git
cd aiops
```

---

## Bước 2 — Tạo file cấu hình môi trường

```bash
cp .env.example .env
```

Mở `.env` và chỉnh 3 giá trị bắt buộc:

```bash
# Sinh JWT_SECRET (bắt buộc, tối thiểu 32 ký tự)
python3 -c "import secrets; print(secrets.token_hex(32))"

# Sinh ENCRYPTION_KEY (bắt buộc, đúng 64 ký tự hex = 32 bytes)
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Sau đó điền vào `.env`:

```env
JWT_SECRET=<kết quả lệnh đầu tiên>
ENCRYPTION_KEY=<kết quả lệnh thứ hai>
```

Cấu hình LLM — chọn **một** trong hai:

**Option A: Ollama (local, không cần API key)**
```env
LLM_PROVIDER=ollama
LLM_URL=http://ollama:11434
LLM_MODEL=qwen2.5:14b
LLM_API_KEY=
```

**Option B: OpenAI-compatible (vLLM hoặc bất kỳ endpoint nào)**
```env
LLM_PROVIDER=openai_compatible
LLM_URL=http://<host>:8000
LLM_MODEL=Qwen/Qwen2.5-14B-Instruct
LLM_API_KEY=
```

---

## Bước 3 — Khởi động stack backend

```bash
docker compose -f infra/docker-compose.dev.yml up --build -d
```

Lệnh này khởi động:
- **MariaDB 10.11** — port 3306, tự động chạy schema từ `infra/init-db/01_schema.sql`
- **Redis 7** — port 6379
- **Ollama** — port 11434
- **API** — port 8000

Kiểm tra các service đã sẵn sàng:

```bash
docker compose -f infra/docker-compose.dev.yml ps
```

Đợi tất cả trạng thái là `healthy` hoặc `running`.

---

## Bước 4 — Pull model LLM (nếu dùng Ollama)

> Bỏ qua bước này nếu dùng vLLM hoặc OpenAI API.

```bash
docker exec -it aiops-ollama-1 ollama pull qwen2.5:14b
```

Model ~9 GB, lần đầu mất 5–15 phút tuỳ tốc độ mạng. Chỉ cần pull một lần, Docker volume giữ lại sau khi restart.

Kiểm tra model đã sẵn sàng:

```bash
docker exec aiops-ollama-1 ollama list
```

---

## Bước 5 — Kiểm tra API

```bash
# Health check cơ bản
curl http://localhost:8000/health

# Readiness check (kiểm tra DB, Redis, LLM)
curl http://localhost:8000/ready
```

Kết quả mong đợi:
```json
{"status": "ok"}
```

Xem API docs đầy đủ tại: **http://localhost:8000/api/docs**

---

## Bước 6 — Đăng nhập

Tài khoản admin mặc định (đã seed sẵn trong DB):

```
username: admin
password: changeme123
```

Lấy JWT token:

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"changeme123"}' | python3 -m json.tool
```

Lưu token để dùng cho các request tiếp theo:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"changeme123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

---

## Bước 7 — Thử chat

```bash
curl -N -X POST http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"message": "Xin chào, hệ thống có thể làm gì?", "app_id": "erp"}'
```

Response là SSE stream, mỗi dòng có dạng:

```
event: step
data: {"text": "Đang phân tích yêu cầu..."}

event: token
data: {"token": "Xin"}

event: token
data: {"token": " chào"}

event: done
data: {"session_id": "...", "intent": "GREETING", "latency_ms": 1240}
```

---

## Bước 8 — Chạy Frontend

```bash
cd services/frontend
npm install
npm run dev
```

Mở trình duyệt tại **http://localhost:3000**

Đăng nhập với `admin / changeme123`, sau đó vào **Chat** để thử hỏi bằng tiếng Việt.

> **Lưu ý:** Frontend gọi API qua `NEXT_PUBLIC_API_URL` trong `services/frontend/.env.local`.
> Mặc định đã được đặt là `http://localhost:8000`.

---

## Bước 9 — Cấu hình Datasource (tuỳ chọn)

Để hệ thống truy vấn log và metrics thực tế, cần cấu hình datasource qua Admin UI:

1. Vào **http://localhost:3000** → đăng nhập
2. Menu bên trái → **Admin → Datasources → Thêm**
3. Điền thông tin:
   - **App ID**: tên hệ thống (vd: `erp`, `crm`)
   - **Elasticsearch URL**: địa chỉ ES của bạn
   - **App Log Index**: tên index log (vd: `erp-logs-*`)
   - **Prometheus URL**: địa chỉ Prometheus (tuỳ chọn)
4. Nhấn **Test kết nối** để kiểm tra
5. Nhấn **Lưu**

Sau khi cấu hình datasource, hỏi thử:

```
"ERP hôm nay có lỗi nghiêm trọng không?"
"CPU của server erp-app-01 đang ở mức nào?"
"Phân tích nguyên nhân gốc rễ lỗi 500 xảy ra lúc 14h hôm nay"
```

---

## Bước 10 — Khởi động TXT Log Worker (tuỳ chọn)

Nếu có log file dạng text cần thu thập và index vào Elasticsearch:

```bash
docker compose -f infra/docker-compose.dev.yml \
  --profile worker up worker -d
```

Hoặc chạy trực tiếp:

```bash
cd services/worker
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

---

## Dừng toàn bộ hệ thống

```bash
docker compose -f infra/docker-compose.dev.yml down
```

Giữ lại data (MariaDB, Ollama models):

```bash
docker compose -f infra/docker-compose.dev.yml down
# Không thêm -v, data volumes được giữ nguyên
```

Xoá toàn bộ data:

```bash
docker compose -f infra/docker-compose.dev.yml down -v
```

---

## Xử lý sự cố thường gặp

### API trả về 503 ở `/ready`

```bash
# Xem log API
docker compose -f infra/docker-compose.dev.yml logs api --tail=50

# Kiểm tra MariaDB đã healthy chưa
docker compose -f infra/docker-compose.dev.yml ps mariadb
```

Thường do MariaDB chưa khởi động xong. Đợi 30–60 giây rồi thử lại.

### Ollama timeout khi chat

Model chưa load xong hoặc CPU quá tải. Tăng timeout trong `.env`:

```env
LLM_JSON_TIMEOUT=180.0
LLM_STREAM_TIMEOUT=240.0
```

Sau đó restart API:

```bash
docker compose -f infra/docker-compose.dev.yml restart api
```

### Lỗi `JWT_SECRET` hoặc `ENCRYPTION_KEY`

```
ValueError: JWT_SECRET must be at least 32 characters
```

Đảm bảo `.env` đã được điền đúng (xem Bước 2). Key không được để giá trị mặc định `changeme`.

### Frontend không kết nối được API

Kiểm tra `services/frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Đảm bảo API đang chạy ở port 8000:

```bash
curl http://localhost:8000/health
```

### Xem log realtime

```bash
# Tất cả services
docker compose -f infra/docker-compose.dev.yml logs -f

# Chỉ API
docker compose -f infra/docker-compose.dev.yml logs -f api
```

---

## Cấu trúc cổng mặc định

| Service | Port | Ghi chú |
|---|---|---|
| API (FastAPI) | 8000 | REST API + SSE |
| API Docs | 8000/api/docs | Swagger UI |
| Frontend (Next.js) | 3000 | Chạy `npm run dev` |
| MariaDB | 3306 | DB client: `mysql -h 127.0.0.1 -u vst_ai_user -pchangeme vst_ai` |
| Redis | 6379 | `redis-cli -a changeme ping` |
| Ollama | 11434 | `curl http://localhost:11434/api/tags` |
