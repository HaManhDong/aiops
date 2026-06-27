"""
AES-256-GCM encryption cho credentials lưu trong MariaDB.
Key đọc từ env var ENCRYPTION_KEY hoặc app settings (64 hex chars = 32 bytes).
"""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _get_key() -> bytes:
    raw = os.environ.get("ENCRYPTION_KEY", "")
    if not raw:
        from app.config import settings
        raw = settings.encryption_key
    if len(raw) != 64:
        raise RuntimeError(
            "ENCRYPTION_KEY phải là 64 hex chars (32 bytes). "
            "Sinh key: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    return bytes.fromhex(raw)


def encrypt(plaintext: str) -> str:
    """Mã hóa plaintext → base64(iv + ciphertext + gcm_tag) lưu vào DB."""
    key = _get_key()
    aesgcm = AESGCM(key)
    iv = os.urandom(12)
    ciphertext = aesgcm.encrypt(iv, plaintext.encode(), None)
    return base64.b64encode(iv + ciphertext).decode()


def decrypt(ciphertext_b64: str) -> str:
    """Giải mã base64 string từ DB → plaintext."""
    key = _get_key()
    aesgcm = AESGCM(key)
    raw = base64.b64decode(ciphertext_b64)
    iv = raw[:12]
    ciphertext = raw[12:]
    return aesgcm.decrypt(iv, ciphertext, None).decode()
