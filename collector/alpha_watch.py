from __future__ import annotations

import asyncio
from alpha_logging import configure as configure_global_logging, get_logger
from pathlib import Path

from config.settings import Settings, load_settings
from persistence.database import Database
from persistence.repository import Repository

from .collector import AlphaCollector
from .models import Event
from .timeutil import now_in_timezone, parse_event_time

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "deploy" / "schema.sql"


async def ingest_once(settings: Settings, repository: Repository) -> None:
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
        default_channel=settings.spug_channel,
        now=now,
    )
    logger.info(
        "ingest.completed",
        events=len(events),
        event_ids=len(event_ids),
    )


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
    await database.ensure_schema(SCHEMA_PATH)
    repository = Repository(database)

    try:
        while True:
            await ingest_once(settings, repository)
            if settings.run_once:
                break
            await asyncio.sleep(60)
            logger.info("alpha.sleep.complete")
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
