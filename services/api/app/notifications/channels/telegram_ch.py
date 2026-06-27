from __future__ import annotations

import structlog
import httpx

from app.notifications.channels.base import NotificationChannel

log = structlog.get_logger()

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _telegram_token() -> str:
    from app.config import settings
    return settings.telegram_bot_token


class TelegramChannel(NotificationChannel):
    async def send(self, recipients: list[str], subject: str, body: str) -> None:
        """recipients = list of Telegram chat_id (str)."""
        token = _telegram_token()
        text = f"*{subject}*\n\n{body}"
        url = _TELEGRAM_API.format(token=token)

        async with httpx.AsyncClient(timeout=15.0) as client:
            for chat_id in recipients:
                resp = await client.post(url, json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                })
                if resp.status_code != 200:
                    raise RuntimeError(
                        f"Telegram API error chat_id={chat_id}: {resp.text[:200]}"
                    )
        log.info("telegram_sent", chat_ids=recipients, subject=subject)
