# Skill: Encryption Service (credentials at rest)

## Mục đích
Mọi credential lưu trong MariaDB (`elasticsearch_api_key`, `kibana_api_key`) phải được
encrypt trước khi INSERT và decrypt khi SELECT.
File này định nghĩa toàn bộ spec cho `services/api/app/services/encryption.py`.

## Thuật toán: AES-256-GCM

- **AES-256-GCM** — authenticated encryption: mã hóa + kiểm tra tính toàn vẹn cùng lúc
- IV (nonce) 12 bytes ngẫu nhiên cho mỗi lần encrypt — KHÔNG tái sử dụng IV
- Output format lưu DB: `base64(iv + ciphertext + tag)` — tất cả trong một string

## Env var

```
ENCRYPTION_KEY=<32-byte hex string>   # 64 hex chars = 256 bit
```

Sinh key khi deploy lần đầu:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Lưu trong `.env` (không commit vào git) và inject vào container qua Docker secret hoặc env var.

## File: `services/api/app/services/encryption.py`

```python
"""
AES-256-GCM encryption cho credentials lưu trong MariaDB.
Key đọc từ env var ENCRYPTION_KEY (64 hex chars = 32 bytes).
"""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _get_key() -> bytes:
    """Đọc và validate ENCRYPTION_KEY từ environment."""
    raw = os.environ.get("ENCRYPTION_KEY", "")
    if len(raw) != 64:
        raise RuntimeError(
            "ENCRYPTION_KEY phải là 64 hex chars (32 bytes). "
            "Sinh key bằng: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    return bytes.fromhex(raw)


def encrypt(plaintext: str) -> str:
    """
    Mã hóa plaintext string → base64 string lưu vào DB.
    IV ngẫu nhiên 12 bytes cho mỗi lần gọi — an toàn dùng lại hàm nhiều lần.
    """
    key = _get_key()
    aesgcm = AESGCM(key)
    iv = os.urandom(12)                             # 96-bit nonce, random mỗi lần
    ciphertext = aesgcm.encrypt(iv, plaintext.encode(), None)  # includes 16-byte GCM tag
    return base64.b64encode(iv + ciphertext).decode()


def decrypt(ciphertext_b64: str) -> str:
    """
    Giải mã base64 string từ DB → plaintext string.

    Raises:
        cryptography.exceptions.InvalidTag: nếu dữ liệu bị tamper hoặc key sai
    """
    key = _get_key()
    aesgcm = AESGCM(key)
    raw = base64.b64decode(ciphertext_b64)
    iv = raw[:12]
    ciphertext = raw[12:]                           # phần còn lại = ciphertext + GCM tag
    return aesgcm.decrypt(iv, ciphertext, None).decode()
```

## Dependency cần thêm vào `requirements.txt`

```
cryptography>=42.0.0
```

## Cách dùng trong ConfigService

```python
# Đọc từ DB → decrypt trước khi dùng
from app.services.encryption import decrypt

api_key = decrypt(row.elasticsearch_api_key)   # row.elasticsearch_api_key là base64 từ DB

# Ghi vào DB → encrypt trước khi INSERT
from app.services.encryption import encrypt

encrypted = encrypt(request.elasticsearch_api_key)
row.elasticsearch_api_key = encrypted
```

## Key rotation

Khi cần rotate key:
1. Sinh key mới: `python -c "import secrets; print(secrets.token_hex(32))"`
2. Viết migration script: đọc tất cả rows với key cũ → decrypt → encrypt lại với key mới
3. Cập nhật env var `ENCRYPTION_KEY` và restart service
4. KHÔNG xóa key cũ cho đến khi migration script chạy xong và verify

Migration script template:
```python
async def rotate_encryption_key(db, old_key_hex: str, new_key_hex: str):
    """Chạy một lần duy nhất khi rotate key."""
    import os
    rows = await db.execute(select(DatasourceConfig))
    for row in rows.scalars():
        # Decrypt bằng key cũ
        os.environ["ENCRYPTION_KEY"] = old_key_hex
        plain_es = decrypt(row.elasticsearch_api_key) if row.elasticsearch_api_key else None
        plain_kb = decrypt(row.kibana_api_key) if row.kibana_api_key else None

        # Encrypt lại bằng key mới
        os.environ["ENCRYPTION_KEY"] = new_key_hex
        row.elasticsearch_api_key = encrypt(plain_es) if plain_es else None
        row.kibana_api_key = encrypt(plain_kb) if plain_kb else None

    await db.commit()
```

## Lưu ý quan trọng

1. KHÔNG log giá trị plaintext hay ciphertext — chỉ log "credential updated for app_id=erp"
2. KHÔNG commit `.env` chứa `ENCRYPTION_KEY` vào git (thêm vào `.gitignore`)
3. Key phải được backup riêng — mất key = mất toàn bộ credentials trong DB
4. Test encryption: `assert decrypt(encrypt("test")) == "test"` trong unit test
