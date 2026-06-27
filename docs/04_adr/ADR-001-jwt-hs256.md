# ADR-001: Dùng JWT HS256 thay vì RS256

**Trạng thái**: Accepted
**Ngày**: 2026-04-23
**Tác giả**: Team VST AI

## Bối cảnh

Hệ thống cần xác thực API với JWT. Có hai lựa chọn chính:
- **HS256** (HMAC-SHA256): symmetric, cùng key để sign và verify
- **RS256** (RSA-SHA256): asymmetric, private key sign / public key verify

## Quyết định

Dùng **HS256**.

## Lý do

1. **On-premise, single-tenant**: VST là môi trường nội bộ, chỉ có một service cần verify JWT (API service). Lợi thế chính của RS256 là cho phép nhiều service verify mà không cần chia sẻ secret — không áp dụng ở đây.
2. **Đơn giản hơn**: không cần quản lý certificate, không cần PKI infrastructure.
3. **Đủ an toàn**: với secret 256-bit ngẫu nhiên, HS256 không thể brute-force trong thực tế.

## Hậu quả và giảm thiểu rủi ro

| Rủi ro | Giảm thiểu |
|---|---|
| Key rotation buộc invalidate tất cả token | Có thể chấp nhận: đội vận hành login lại (~10 người) |
| Nếu key lộ, attacker sign được token | Lưu key trong env var Docker secret, không commit git |
| Không có `jti` blacklist | Token TTL = 8 giờ — đủ ngắn để không cần blacklist |

## Thay đổi tương lai

Nếu sau này cần microservice khác verify JWT hoặc expose API ra ngoài, chuyển sang RS256.
