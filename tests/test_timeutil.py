from datetime import datetime

from zoneinfo import ZoneInfo

from collector.timeutil import parse_event_time, parse_quiet_hours


def test_parse_event_time_hhmm_rolls_over_midnight():
    tz = "Asia/Taipei"
    reference = datetime(2024, 5, 26, 23, 30, tzinfo=ZoneInfo(tz))
    event_time = parse_event_time("00:15", tz, reference)
    assert event_time.date().day == 27
    assert event_time.hour == 0
    assert event_time.minute == 15


def test_parse_quiet_hours_handles_wraparound():
    start, end = parse_quiet_hours("22:00-07:30")
    assert start.hour == 22
    assert end.hour == 7
