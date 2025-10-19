from datetime import datetime, timedelta
from pathlib import Path

from zoneinfo import ZoneInfo

from collector.models import Event
from collector.reminder import ReminderEngine
from collector.state import StateStore


def test_reminder_engine_triggers_offset(tmp_path):
    tz = ZoneInfo("Asia/Taipei")
    now = datetime(2024, 5, 26, 10, 0, tzinfo=tz)
    event = Event(
        token="OMEGA",
        section="today",
        raw_time="10:20",
        start_time=now + timedelta(minutes=20),
        details={},
        source="json",
    )
    state = StateStore(tmp_path / "state.json", ttl=timedelta(hours=48))
    engine = ReminderEngine(state, ahead_minutes=30, reminder_offsets=[20, 5], notify_tba_once=True)

    reminders = engine.evaluate([event], now)
    assert len(reminders) == 1
    reminder = reminders[0]
    assert reminder.offset_minutes == 20

    state.mark_notified(event.reminder_key(20), now)
    reminders_second_pass = engine.evaluate([event], now)
    assert reminders_second_pass == []


def test_reminder_engine_handles_tba(tmp_path):
    tz = ZoneInfo("Asia/Taipei")
    now = datetime(2024, 5, 26, 12, 0, tzinfo=tz)
    event = Event(
        token="SIGMA",
        section="upcoming",
        raw_time="TBA",
        start_time=None,
        details={},
        source="dom",
    )
    state = StateStore(tmp_path / "state.json", ttl=timedelta(hours=48))
    engine = ReminderEngine(state, ahead_minutes=30, reminder_offsets=[20, 5], notify_tba_once=True)

    reminders = engine.evaluate([event], now)
    assert len(reminders) == 1
    assert reminders[0].offset_minutes is None

    state.mark_notified(event.without_time_key(), now)
    reminders_later = engine.evaluate([event], now)
    assert reminders_later == []
