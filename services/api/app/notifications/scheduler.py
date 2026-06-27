from __future__ import annotations

from uuid import uuid4
import structlog

log = structlog.get_logger()


async def run_notification_job(config_id: str) -> None:
    """Chạy một notification job theo config_id."""
    from app.database import get_db
    from app.models.notification import NotificationConfig, NotificationLog
    from app.notifications.registry import get_channel
    from app.notifications.report_builder import build_daily_report

    async for db in get_db():
        cfg = await db.get(NotificationConfig, config_id)
        if not cfg or not cfg.is_enabled:
            return

        status = "sent"
        error_msg = None
        try:
            report = await build_daily_report(cfg.app_id, cfg.report_window_hours)
            subject = f"[AIOps] Báo cáo định kỳ — {cfg.name}"
            channel = get_channel(cfg.channel)
            await channel.send(cfg.recipients, subject, report)
            log.info(
                "notification_sent",
                config_id=config_id,
                channel=cfg.channel,
                recipients=len(cfg.recipients),
            )
        except Exception as exc:
            status = "failed"
            error_msg = str(exc)[:500]
            log.error("notification_failed", config_id=config_id, error=error_msg)

        db.add(
            NotificationLog(
                config_id=config_id,
                channel=cfg.channel,
                status=status,
                recipients_count=len(cfg.recipients),
                error_message=error_msg,
            )
        )
        await db.commit()
        break


def setup_notification_scheduler(scheduler) -> None:
    """
    Đăng ký tất cả notification_configs đang enabled vào APScheduler.
    Gọi khi startup. Dùng cron trigger theo schedule_cron từ DB.
    """
    import asyncio
    from apscheduler.triggers.cron import CronTrigger

    async def _load_and_register():
        from app.database import get_db
        from app.models.notification import NotificationConfig
        from sqlalchemy import select

        async for db in get_db():
            rows = (
                await db.execute(
                    select(NotificationConfig).where(NotificationConfig.is_enabled == True)
                )
            ).scalars().all()

            for cfg in rows:
                _register_job(scheduler, cfg.id, cfg.schedule_cron, cfg.channel)
            log.info("notification_jobs_registered", count=len(rows))
            break

    # Chạy async loader trong event loop hiện tại
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_load_and_register())
        else:
            loop.run_until_complete(_load_and_register())
    except Exception as exc:
        log.warning("notification_scheduler_setup_error", error=str(exc))


def _register_job(scheduler, config_id: str, cron_expr: str, channel: str) -> None:
    from apscheduler.triggers.cron import CronTrigger

    job_id = f"notif_{config_id}"
    # Xóa job cũ nếu đã tồn tại (để không bị duplicate khi reload)
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass

    try:
        parts = cron_expr.split()
        if len(parts) != 5:
            raise ValueError(f"Cron expression phải có 5 phần: '{cron_expr}'")

        minute, hour, day, month, day_of_week = parts
        scheduler.add_job(
            run_notification_job,
            CronTrigger(
                minute=minute, hour=hour, day=day,
                month=month, day_of_week=day_of_week,
            ),
            args=[config_id],
            id=job_id,
            replace_existing=True,
        )
        log.info("notification_job_registered", job_id=job_id, channel=channel, cron=cron_expr)
    except Exception as exc:
        log.error("notification_job_register_error", config_id=config_id, error=str(exc))


def reload_job(scheduler, config_id: str, schedule_cron: str, channel: str, is_enabled: bool) -> None:
    """Gọi từ router sau khi create/update/delete config."""
    job_id = f"notif_{config_id}"
    if not is_enabled:
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass
        return
    _register_job(scheduler, config_id, schedule_cron, channel)
