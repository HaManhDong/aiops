from __future__ import annotations

from app.notifications.channels.base import NotificationChannel
from app.notifications.channels.email_ch import EmailChannel
from app.notifications.channels.telegram_ch import TelegramChannel

_CHANNELS: dict[str, NotificationChannel] = {
    "email": EmailChannel(),
    "telegram": TelegramChannel(),
}


def get_channel(name: str) -> NotificationChannel:
    ch = _CHANNELS.get(name)
    if ch is None:
        raise ValueError(f"Channel không hợp lệ: {name}. Hỗ trợ: {list(_CHANNELS)}")
    return ch
