from __future__ import annotations

import asyncio
from datetime import timedelta

from alpha_logging import configure as configure_global_logging, get_logger

from config.settings import Settings, load_settings
from notifier.spug import SpugConfig, SpugNotifier, SpugError

from .collector import AlphaCollector
from .reminder import ReminderEngine
from .state import StateStore
from .timeutil import now_in_timezone, parse_event_time, in_quiet_hours


async def run_once(settings: Settings, notifier: SpugNotifier, state: StateStore) -> None:
    logger = get_logger("alpha.watch")
    collector = AlphaCollector(
        settings.alpha_url,
        locale=settings.language,
        timezone=settings.timezone,
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

    state.prune(now)
    engine = ReminderEngine(
        state_store=state,
        ahead_minutes=settings.ahead_minutes,
        reminder_offsets=settings.reminder_offsets,
        notify_tba_once=settings.notify_tba_once,
    )

    reminders = engine.evaluate(events, now)
    logger.info("reminder.ready", count=len(reminders))

    quiet_mode = in_quiet_hours(now, settings.quiet_hours)
    for reminder in reminders:
        try:
            notifier.send(reminder, quiet_mode=quiet_mode)
        except SpugError as exc:
            logger.error("notifier.failed", error=str(exc))
            continue
        if reminder.offset_minutes is not None:
            state.mark_notified(reminder.event.reminder_key(reminder.offset_minutes), now)
        else:
            state.mark_notified(reminder.event.without_time_key(), now)


async def main() -> None:
    settings = load_settings()
    configure_global_logging(settings.log_level, force=True)
    logger = get_logger("alpha.main")

    state = StateStore(settings.state_file, ttl=timedelta(hours=settings.state_ttl_hours))
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

    while True:
        await run_once(settings, notifier, state)
        if settings.run_once:
            break
        await asyncio.sleep(60)
        logger.info("alpha.sleep.complete")


if __name__ == "__main__":
    asyncio.run(main())
