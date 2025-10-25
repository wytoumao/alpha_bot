from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import time as current_timestamp
from typing import Iterable, List, Optional

from alpha_logging import get_logger
from collector.models import Event
from persistence.database import Database


@dataclass(frozen=True)
class NotificationTask:
    id: int
    event_id: int
    token: str
    event_time: Optional[datetime]
    offset_minutes: Optional[int]
    channel: str
    remind_at: datetime
    details: dict
    attempts: int
    raw_time: Optional[str]


class Repository:
    def __init__(self, database: Database):
        self.db = database
        self.logger = get_logger(__name__)

    @staticmethod
    def _canonical_symbol(event: Event) -> str:
        details = event.details or {}
        symbol = (
            details.get("symbol")
            or details.get("token")
            or details.get("symbol_name")
            or (event.token or "")
        )
        symbol = str(symbol).strip()
        if " " in symbol:
            symbol = symbol.split()[0]
        return symbol.upper()

    @staticmethod
    def _extract_detail_fields(details: dict) -> tuple[Optional[str], Optional[str]]:
        def pick(keys: Iterable[str]) -> Optional[str]:
            for key in keys:
                if key in details and details[key] not in (None, ""):
                    value = details[key]
                    if isinstance(value, str):
                        candidate = value.strip()
                    else:
                        candidate = str(value)
                    if candidate:
                        return candidate
            return None

        amount = pick(["amount", "数量", "allocation", "supply"])
        points = pick(["points", "积分", "score"])
        return amount, points

    @staticmethod
    def _is_valid_time_format(raw_time: Optional[str]) -> bool:
        if not raw_time:
            return False
        return bool(re.search(r"\b\d{1,2}:\d{2}\b", raw_time))

    async def upsert_events(self, events: Iterable[Event], now: datetime) -> List[int]:
        event_ids: List[int] = []
        for event in events:
            # Guard: only persist when details_json.date is today (if provided)
            today_str = now.strftime("%Y-%m-%d")
            dval = event.details.get("date") or event.details.get("Date")
            if dval is not None and str(dval) != today_str:
                # Skip non-today events to keep DB clean
                continue
            if not self._is_valid_time_format(event.raw_time):
                continue
            start_time_str = event.start_time.strftime("%Y-%m-%d %H:%M:%S") if event.start_time else None
            amount_value, points_value = self._extract_detail_fields(event.details)
            details_json = json.dumps(event.details, ensure_ascii=False)
            row = await self.db.fetchone(
                """
                SELECT id FROM alpha_events WHERE token=%s AND raw_time=%s
                """,
                (event.token, event.raw_time),
            )
            if row:
                event_id = row["id"]
                await self.db.execute(
                    """
                    UPDATE alpha_events
                    SET start_time=%s,
                        raw_time=%s,
                        amount=%s,
                        points=%s,
                        details_json=%s,
                    WHERE id=%s
                    """,
                    (
                        start_time_str,
                        event.raw_time,
                        amount_value,
                        points_value,
                        details_json,
                        event_id,
                    ),
                )
            else:
                await self.db.execute(
                    """
                    INSERT INTO alpha_events
                        (token, start_time, raw_time, amount, points, details_json)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        event.token,
                        start_time_str,
                        event.raw_time,
                        amount_value,
                        points_value,
                        details_json,
                    ),
                )
                row = await self.db.fetchone(
                    """
                    SELECT id FROM alpha_events WHERE token=%s AND raw_time=%s
                    """,
                    (event.token, event.raw_time),
                )
                event_id = row["id"]
            event_ids.append(event_id)
        return event_ids

    async def ensure_notifications(
        self,
        event_ids: List[int],
        events: List[Event],
        default_channel: str,
        now: datetime,
    ) -> None:
        current_ts = current_timestamp()
        for event_id, event in zip(event_ids, events):
            if not event.start_time:
                continue
            start_ts = event.start_time.timestamp()
            if current_ts - 30 * 60 >= start_ts:
                continue
            remind_at = event.start_time - timedelta(minutes=30)
            await self._create_notification_task(
                event_id=event_id,
                event=event,
                offset=30,
                remind_at=remind_at,
                channel=default_channel,
            )

    async def _create_notification_task(
        self,
        event_id: int,
        event: Event,
        offset: Optional[int],
        remind_at: datetime,
        channel: str,
    ) -> None:
        await self.db.execute(
            """
            INSERT IGNORE INTO alpha_notifications
                (event_id, offset_minutes, remind_at, channel, metadata)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                event_id,
                offset,
                remind_at.strftime("%Y-%m-%d %H:%M:%S"),
                channel,
                json.dumps(
                    {
                        "token": event.token,
                        "display_name": event.details.get("display_name", event.token),
                        "section": event.section,
                    },
                    ensure_ascii=False,
                ),
            ),
        )

    async def fetch_due_notifications(self, now: datetime) -> List[NotificationTask]:
        rows = await self.db.fetchall(
            """
            SELECT
                n.id,
                n.event_id,
                e.token,
                e.start_time,
                e.raw_time,
                n.offset_minutes,
                n.channel,
                n.remind_at,
                e.details_json,
                n.attempts
            FROM alpha_notifications n
            JOIN alpha_events e ON e.id = n.event_id
            WHERE n.status='pending' AND n.remind_at <= %s
            ORDER BY n.remind_at ASC
            """,
            (now.strftime("%Y-%m-%d %H:%M:%S"),),
        )
        tasks: List[NotificationTask] = []
        for row in rows:
            tasks.append(
                NotificationTask(
                    id=row["id"],
                    event_id=row["event_id"],
                    token=row["token"],
                    event_time=row["start_time"],
                    offset_minutes=row["offset_minutes"],
                    channel=row["channel"],
                    remind_at=row["remind_at"],
                    details=json.loads(row["details_json"]),
                    attempts=row["attempts"],
                    raw_time=row["raw_time"],
                )
            )
        return tasks

    async def mark_notification_sent(self, notification_id: int, success: bool, fail_reason: Optional[str] = None) -> None:
        status = "sent" if success else "failed"
        reason = fail_reason[:255] if fail_reason else None
        await self.db.execute(
            """
            UPDATE alpha_notifications
            SET status=%s,
                sent_at=CASE WHEN %s='sent' THEN NOW() ELSE sent_at END,
                fail_reason=%s,
                attempts=attempts+1
            WHERE id=%s
            """,
            (status, status, reason, notification_id),
        )

    async def log_notification_attempt(
        self,
        notification_id: int,
        attempt_no: int,
        endpoint: str,
        payload: dict,
        response_code: Optional[int],
        response_body: Optional[dict],
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO alpha_notification_logs
                (notification_id, attempt_no, spug_endpoint, payload, response_code, response_body)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                notification_id,
                attempt_no,
                endpoint,
                json.dumps(payload, ensure_ascii=False),
                response_code,
                json.dumps(response_body, ensure_ascii=False) if response_body else None,
            ),
        )
