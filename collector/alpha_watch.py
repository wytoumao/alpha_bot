from __future__ import annotations

import asyncio
from alpha_logging import configure as configure_global_logging, get_logger

from config.settings import Settings, load_settings
from notifier.spug import NotificationResult, SpugConfig, SpugNotifier, SpugError
from persistence.database import Database
from persistence.repository import NotificationTask, Repository

from .collector import AlphaCollector
from .models import Event
from .reminder import Reminder
from .timeutil import in_quiet_hours, now_in_timezone, parse_event_time


async def run_once(settings: Settings, notifier: SpugNotifier, repository: Repository) -> None:
    logger = get_logger("alpha.watch")
    collector = AlphaCollector(
        settings.alpha_url,
        locale=settings.language,
        timezone=settings.timezone,
        proxy=settings.playwright_proxy,
    )
    now = now_in_timezone(settings.timezone)

    try:
        events = await collector.fetch_events()
        logger.info("collector.events", count=len(events))
    except Exception as exc:
        logger.error("collector.failed", error=str(exc))
        return

    for event in events:
        event.start_time = parse_event_time(event.raw_time, settings.timezone, now)

    events = [
        event
        for event in events
        if event.start_time and event.start_time.date() == now.date()
    ]
    # Second guard: details_json.date must be today when present
    today_str = now.strftime("%Y-%m-%d")
    events = [
        e for e in events
        if (e.details.get("date") or e.details.get("Date") or today_str) == today_str
    ]
    for event in events:
        event.section = "today"
        event.details["section"] = "today"

    event_ids = await repository.upsert_events(events, now)
    await repository.ensure_notifications(
        event_ids=event_ids,
        events=events,
        reminder_offsets=settings.reminder_offsets,
        default_channel=settings.spug_channel,
        now=now,
    )

    quiet_mode = in_quiet_hours(now, settings.quiet_hours)
    quiet_channel = settings.spug_quiet_channel if quiet_mode else None
    tasks = await repository.fetch_due_notifications(now)
    logger.info("notifications.due", count=len(tasks), quiet=quiet_mode)

    for task in tasks:
        reminder = _build_reminder_from_task(task, quiet_channel or task.channel)
        try:
            result = notifier.send(reminder, quiet_mode=quiet_mode)
            await _log_and_mark(repository, task, result, success=True)
        except SpugError as exc:
            logger.error("notifier.failed", id=task.id, error=str(exc))
            await _log_and_mark(repository, task, None, success=False, reason=str(exc))


def _build_reminder_from_task(task: NotificationTask, effective_channel: str) -> Reminder:
    details = {**task.details, "channel": effective_channel}
    section = details.get("section", "today")
    event = Event(
        token=task.token,
        section=section,
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
    logger = get_logger("alpha.main")

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
            template_id=settings.spug_template_id,
            targets=settings.spug_targets,
        )
    )

    try:
        while True:
            await run_once(settings, notifier, repository)
            if settings.run_once:
                break
            await asyncio.sleep(60)
            logger.info("alpha.sleep.complete")
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
