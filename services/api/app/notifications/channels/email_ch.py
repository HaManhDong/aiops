from __future__ import annotations

import structlog
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import aiosmtplib

from app.notifications.channels.base import NotificationChannel

log = structlog.get_logger()


def _smtp_settings():
    from app.config import settings
    return (
        settings.smtp_host,
        settings.smtp_port,
        settings.smtp_user,
        settings.smtp_password,
        settings.smtp_from,
        settings.smtp_use_tls,
    )


class EmailChannel(NotificationChannel):
    async def send(self, recipients: list[str], subject: str, body: str) -> None:
        smtp_host, smtp_port, smtp_user, smtp_password, smtp_from, use_tls = _smtp_settings()

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_from
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(body, "plain", "utf-8"))

        await aiosmtplib.send(
            msg,
            hostname=smtp_host,
            port=smtp_port,
            username=smtp_user or None,
            password=smtp_password or None,
            use_tls=use_tls,
        )
        log.info("email_sent", recipients=recipients, subject=subject)
