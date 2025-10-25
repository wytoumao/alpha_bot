from __future__ import annotations

import asyncio

from alpha_logging import configure as configure_global_logging, get_logger
from collector.models import Event
from collector.reminder import Reminder
from collector.timeutil import in_quiet_hours, now_in_timezone
from config.settings import Settings, load_settings
from notifier.spug import NotificationResult, SpugConfig, SpugNotifier, SpugError
from persistence.database import Database
from persistence.repository import NotificationTask, Repository
from datetime import timedelta


async def dispatch_once(settings: Settings, notifier: SpugNotifier, repository: Repository) -> None:
    logger = get_logger("alpha.dispatch")
    now = now_in_timezone(settings.timezone)
    quiet_mode = in_quiet_hours(now, settings.quiet_hours)
    quiet_channel = settings.spug_quiet_channel if quiet_mode else None

    tasks = await repository.fetch_due_notifications(now)
    logger.info("notifications.due", count=len(tasks), quiet=quiet_mode)

    for task in tasks:
        event_time = task.event_time
        if event_time is None and task.offset_minutes is not None:
            event_time = task.remind_at + timedelta(minutes=task.offset_minutes)
        if event_time and event_time > now:
            reason = "event_time_in_future"
            logger.info(
                "notifier.skip.future",
                id=task.id,
                event_time=event_time.isoformat(),
                now=now.isoformat(),
            )
            await _log_and_mark(repository, task, None, success=False, reason=reason)
            continue
        reminder = _build_reminder_from_task(task, quiet_channel or task.channel)
        try:
            result = notifier.send(reminder, quiet_mode=quiet_mode)
            await _log_and_mark(repository, task, result, success=True)
        except SpugError as exc:
            logger.error("notifier.failed", id=task.id, error=str(exc))
            await _log_and_mark(repository, task, None, success=False, reason=str(exc))


def _build_reminder_from_task(task: NotificationTask, effective_channel: str) -> Reminder:
    details = {**task.details, "channel": effective_channel}
    event = Event(
        token=task.token,
        section=details.get("section", "today"),
        raw_time=task.raw_time or "",
        start_time=task.event_time,
        details=details,
        source="db",
    )
    return Reminder(
        event=event,
        offset_minutes=task.offset_minutes,
        trigger_time=task.remind_at,
        reason="scheduled",
    )


async def _log_and_mark(
    repository: Repository,
    task: NotificationTask,
    result: NotificationResult | None,
    success: bool,
    reason: str | None = None,
) -> None:
    attempt_no = task.attempts + 1
    if result:
        await repository.log_notification_attempt(
            notification_id=task.id,
            attempt_no=attempt_no,
            endpoint=result.endpoint,
            payload=result.payload,
            response_code=result.status_code,
            response_body=result.response_body,
        )
    else:
        await repository.log_notification_attempt(
            notification_id=task.id,
            attempt_no=attempt_no,
            endpoint="/error",
            payload={"token": task.token, "reason": reason or "unknown"},
            response_code=None,
            response_body={"error": reason} if reason else None,
        )
    await repository.mark_notification_sent(task.id, success=success, fail_reason=reason)


async def main() -> None:
    settings = load_settings()
    configure_global_logging(settings.log_level, force=True)
    logger = get_logger("alpha.dispatcher")

    database = Database(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        db=settings.db_name,
        minsize=settings.db_pool_minsize,
        maxsize=settings.db_pool_maxsize,
    )
    await database.connect()
    repository = Repository(database)
    notifier = SpugNotifier(
        SpugConfig(
            base_url=settings.spug_base_url,
            token=settings.spug_token,
            timeout_seconds=settings.spug_timeout_seconds,
            channel=settings.spug_channel,
            quiet_channel=settings.spug_quiet_channel,
            xsend_user_id=settings.spug_xsend_user_id,
            proxy=settings.spug_proxy,
        )
    )

    try:
        while True:
            await dispatch_once(settings, notifier, repository)
            if settings.run_once:
                break
            await asyncio.sleep(60)
            logger.info("dispatch.sleep.complete")
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
