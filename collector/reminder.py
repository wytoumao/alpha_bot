from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Sequence, Tuple

import structlog

from .models import Event
from .state import StateStore
from .timeutil import is_within_window


@dataclass(frozen=True)
class Reminder:
    event: Event
    offset_minutes: Optional[int]
    trigger_time: datetime
    reason: str


class ReminderEngine:
    def __init__(
        self,
        state_store: StateStore,
        ahead_minutes: int,
        reminder_offsets: Sequence[int],
        notify_tba_once: bool,
    ):
        self.state_store = state_store
        self.ahead_minutes = ahead_minutes
        self.reminder_offsets = sorted(reminder_offsets, reverse=True)
        self.notify_tba_once = notify_tba_once
        self.logger = structlog.get_logger(__name__)

    def evaluate(self, events: Iterable[Event], now: datetime) -> List[Reminder]:
        reminders: List[Reminder] = []
        for event in events:
            if event.start_time and is_within_window(event.start_time, now, self.ahead_minutes):
                reminders.extend(self._evaluate_timed_event(event, now))
            elif not event.start_time and self.notify_tba_once:
                key = event.without_time_key()
                if not self.state_store.was_notified(key):
                    reminders.append(
                        Reminder(
                            event=event,
                            offset_minutes=None,
                            trigger_time=now,
                            reason="tba",
                        )
                    )
            # else ignore
        return reminders

    def _evaluate_timed_event(self, event: Event, now: datetime) -> List[Reminder]:
        ready: List[Reminder] = []
        for offset in self.reminder_offsets:
            trigger_key = event.reminder_key(offset)
            if self.state_store.was_notified(trigger_key):
                continue
            trigger_time = event.start_time - timedelta(minutes=offset)
            if trigger_time <= now <= event.start_time:
                ready.append(
                    Reminder(
                        event=event,
                        offset_minutes=offset,
                        trigger_time=trigger_time,
                        reason="offset",
                    )
                )
        return ready
