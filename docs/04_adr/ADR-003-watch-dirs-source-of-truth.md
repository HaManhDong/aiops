# ADR-003: `watch_dirs` — nguồn truth là `datasource_configs`

**Trạng thái**: Accepted
**Ngày**: 2026-04-23
**Tác giả**: Team VST AI

## Bối cảnh

Có hai bảng đều liên quan đến thư mục log cần collect:
- `datasource_configs.txt_watch_dirs` (JSON array)
- `worker_configs.watch_dirs` (JSON array, field trùng lặp)

Điều này gây nhập nhằng: khi admin thêm thư mục mới cần cập nhật cả hai nơi, dễ không nhất quán.

## Quyết định

**`datasource_configs.txt_watch_dirs`** là **nguồn truth duy nhất** cho danh sách thư mục cần scan.

`worker_configs` chỉ chứa:
- `file_patterns`: pattern lọc file (*.txt, *.log)
- `schedule_cron`: cron expression cho APScheduler
- `batch_size`: số docs per bulk request
- `is_enabled`: bật/tắt collector cho app_id

`worker_configs.watch_dirs` field **không được dùng** trong code — sẽ bị xóa trong migration tiếp theo.

## Lý do

1. `datasource_configs` là "source of truth" cho mọi thứ liên quan đến một app/datasource — thư mục log thuộc về datasource, không thuộc về worker config.
2. Admin nên cấu hình ở một nơi duy nhất.
3. Giảm risk khi hai bảng bị out-of-sync.

## Migration cần làm

```sql
-- Xóa field watch_dirs khỏi worker_configs (sau khi verify code đã dùng datasource_configs)
ALTER TABLE worker_configs DROP COLUMN watch_dirs;
```

Thực hiện qua Alembic: `alembic revision --autogenerate -m "remove_worker_watch_dirs"`.
