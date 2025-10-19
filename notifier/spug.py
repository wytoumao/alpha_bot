from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import requests
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from collector.models import Event
from collector.reminder import Reminder


class SpugError(RuntimeError):
    pass


@dataclass
class SpugConfig:
    base_url: str
    token: Optional[str]
    timeout_seconds: int
    channel: str
    quiet_channel: Optional[str]
    xsend_user_id: Optional[str]
    template_id: Optional[str]
    targets: Iterable[str]


class SpugNotifier:
    def __init__(self, config: SpugConfig):
        self.config = config
        self.logger = structlog.get_logger(__name__)

    def send(self, reminder: Reminder, quiet_mode: bool = False) -> None:
        channel = self.config.channel
        if quiet_mode and self.config.quiet_channel:
            channel = self.config.quiet_channel

        title, body = self._build_message(reminder, channel, quiet_mode)

        if self.config.xsend_user_id:
            self._xsend(channel, title, body)
        elif self.config.template_id and self.config.targets:
            self._template_send(title, body)
        else:
            raise SpugError("Spug configuration incomplete. Provide xsend user id or template id with targets.")

    def _build_message(self, reminder: Reminder, channel: str, quiet_mode: bool) -> tuple[str, str]:
        event = reminder.event
        offset = reminder.offset_minutes
        prefix = f"{event.token}"
        if event.start_time:
            prefix = f"{event.token} {event.start_time.strftime('%Y-%m-%d %H:%M')}"
        title = f"[Alpha] {prefix}"

        lines = [
            f"Section: {event.section}",
        ]
        if event.start_time:
            lines.append(f"Start: {event.start_time.strftime('%Y-%m-%d %H:%M %Z')}")
        else:
            lines.append(f"Time: {event.raw_time or 'TBA'}")
        if offset is not None:
            lines.append(f"Reminder: T-{offset} min")
        if quiet_mode:
            lines.append("Quiet hours fallback channel")
        for key, value in event.details.items():
            if isinstance(value, (str, int, float)):
                lines.append(f"{key}: {value}")

        body = "\n".join(lines)
        return title, body

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(SpugError),
    )
    def _xsend(self, channel: str, title: str, body: str) -> None:
        url = f"{self.config.base_url.rstrip('/')}/xsend/{self.config.xsend_user_id}"
        payload = {
            "title": title,
            "content": body,
            "channel": channel,
        }
        response = self._post(url, payload)
        if response.status_code >= 300:
            raise SpugError(f"xsend failed: {response.status_code} {response.text}")
        self.logger.info("spug.xsend.success", channel=channel)

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(SpugError),
    )
    def _template_send(self, title: str, body: str) -> None:
        url = f"{self.config.base_url.rstrip('/')}/send/{self.config.template_id}"
        payload = {
            "targets": list(self.config.targets),
            "title": title,
            "content": body,
        }
        response = self._post(url, payload)
        if response.status_code >= 300:
            raise SpugError(f"template send failed: {response.status_code} {response.text}")
        self.logger.info("spug.template.success", targets=len(self.config.targets))

    def _post(self, url: str, payload: dict) -> requests.Response:
        headers = {"Content-Type": "application/json"}
        if self.config.token:
            headers["Authorization"] = f"Token {self.config.token}"
        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.config.timeout_seconds,
            )
            return response
        except requests.RequestException as exc:
            raise SpugError(str(exc)) from exc
