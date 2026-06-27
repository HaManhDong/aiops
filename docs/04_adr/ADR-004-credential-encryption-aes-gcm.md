# ADR-004: Mã hóa credentials trong DB bằng AES-256-GCM

**Trạng thái**: Accepted
**Ngày**: 2026-04-23
**Tác giả**: Team VST AI

## Bối cảnh

`datasource_configs` lưu `elasticsearch_api_key` và `kibana_api_key`.
Nếu DB bị dump, credentials sẽ bị lộ và attacker có thể đọc/xóa toàn bộ log.

Các lựa chọn:
1. Plaintext trong DB (không chấp nhận)
2. AES-256-CBC (symmetric, nhưng không authenticated)
3. AES-256-GCM (symmetric, authenticated encryption)
4. Dùng HashiCorp Vault hoặc AWS Secrets Manager

## Quyết định

Dùng **AES-256-GCM** với key lưu trong env var `ENCRYPTION_KEY`.

## Lý do

1. **AES-256-GCM vs CBC**: GCM cung cấp authentication tag — phát hiện được nếu ciphertext bị tamper. CBC không có authentication, dễ bị padding oracle attack.
2. **Vault/Secrets Manager**: quá phức tạp cho team 3 người, không có infrastructure để chạy Vault on-premise.
3. **Env var key**: đơn giản, đủ an toàn nếu server được hardened. Key không vào git, inject qua Docker secret hoặc env file trên server.

## Hậu quả

| Rủi ro | Giảm thiểu |
|---|---|
| Mất key → mất toàn bộ credentials | Backup key offline, lưu ≥ 2 nơi tách biệt |
| Key lộ → cần re-encrypt tất cả | Có rotation script trong `07_encryption.md` |
| GCM IV collision nếu dùng lại IV | IV ngẫu nhiên 12 bytes mỗi lần encrypt — xác suất collision cực thấp |

## Implementation

Xem chi tiết trong skill [07_encryption.md](../../.claude/skills/07_encryption.md).

Format lưu DB: `base64(iv_12bytes + ciphertext + gcm_tag_16bytes)` — tất cả trong một TEXT field.
