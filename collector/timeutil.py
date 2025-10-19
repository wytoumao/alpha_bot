from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from typing import Optional, Tuple

from zoneinfo import ZoneInfo


QUIET_DELIMITERS = {"-", "–", "—", "to"}
TBA_MARKERS = {"tba", "to be announced", "待定", "—", "-", "", "na", "n/a"}


def get_timezone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def now_in_timezone(name: str) -> datetime:
    return datetime.now(get_timezone(name))


def parse_event_time(raw_time: str, timezone: str, reference: Optional[datetime] = None) -> Optional[datetime]:
    if not raw_time:
        return None
    raw_normalized = raw_time.strip()
    if raw_normalized.lower() in TBA_MARKERS:
        return None

    tz = get_timezone(timezone)
    reference = reference or datetime.now(tz)

    iso_candidate = _parse_iso_datetime(raw_normalized, tz)
    if iso_candidate:
        return iso_candidate

    hhmm_candidate = _parse_hhmm(raw_normalized, tz, reference)
    if hhmm_candidate:
        return hhmm_candidate

    date_only_candidate = _parse_date_only(raw_normalized, tz)
    if date_only_candidate:
        return date_only_candidate

    return None


def _parse_iso_datetime(value: str, tz: ZoneInfo) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt.astimezone(tz)
    except ValueError:
        return None


def _parse_hhmm(value: str, tz: ZoneInfo, reference: datetime) -> Optional[datetime]:
    match = re.search(r"(?P<hour>\d{1,2}):(?P<minute>\d{2})", value)
    if not match:
        return None
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    candidate = datetime.combine(reference.date(), time(hour, minute, tzinfo=tz)).astimezone(tz)
    if candidate < reference - timedelta(hours=1):
        candidate += timedelta(days=1)
    return candidate


def _parse_date_only(value: str, tz: ZoneInfo) -> Optional[datetime]:
    match = re.search(r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})", value)
    if not match:
        return None
    return datetime(
        int(match.group("year")),
        int(match.group("month")),
        int(match.group("day")),
        tzinfo=tz,
    )


def is_within_window(
    event_time: Optional[datetime],
    now: datetime,
    ahead_minutes: int,
) -> bool:
    if not event_time:
        return False
    if event_time < now:
        return False
    delta = event_time - now
    return delta <= timedelta(minutes=ahead_minutes)


def in_quiet_hours(now: datetime, quiet_window: Optional[Tuple[time, time]]) -> bool:
    if not quiet_window:
        return False
    start, end = quiet_window
    now_time = now.timetz().replace(tzinfo=None)
    if start <= end:
        return start <= now_time < end
    return now_time >= start or now_time < end


def parse_quiet_hours(raw: Optional[str]) -> Optional[Tuple[time, time]]:
    if not raw:
        return None
    cleaned = str(raw).strip()
    for delim in QUIET_DELIMITERS:
        if delim in cleaned:
            parts = [part.strip() for part in cleaned.split(delim)]
            break
    else:
        parts = [part.strip() for part in cleaned.split()]
    if len(parts) != 2:
        return None
    try:
        start = _parse_time(parts[0])
        end = _parse_time(parts[1])
        return start, end
    except ValueError:
        return None


def _parse_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))
