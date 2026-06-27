from __future__ import annotations

from abc import ABC, abstractmethod


class NotificationChannel(ABC):
    @abstractmethod
    async def send(self, recipients: list[str], subject: str, body: str) -> None:
        """Gửi thông báo. Raise exception nếu thất bại."""
        ...
