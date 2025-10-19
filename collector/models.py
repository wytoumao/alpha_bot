from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass(slots=True)
class Event:
    token: str
    section: str
    raw_time: str
    start_time: Optional[datetime]
    details: Dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"
    url: Optional[str] = None

    def reminder_key(self, offset_minutes: int) -> str:
        time_part = (
            self.start_time.strftime("%Y-%m-%d %H:%M")
            if self.start_time
            else self.raw_time or "unknown"
        )
        return f"{self.section}|{self.token}|{time_part}|{offset_minutes}"

    def without_time_key(self) -> str:
        return f"{self.section}|{self.token}|{self.raw_time or 'unknown'}|NEW"
