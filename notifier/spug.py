from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from alpha_logging import get_logger
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
    proxy: Optional[str]



@dataclass
class NotificationResult:
    endpoint: str
    payload: dict
    status_code: Optional[int]
    response_body: Optional[dict]


class SpugNotifier:
    def __init__(self, config: SpugConfig):
        self.config = config
        self.logger = get_logger(__name__)

    def send(self, reminder: Reminder, quiet_mode: bool = False) -> NotificationResult:
        channel = self.config.channel
        if quiet_mode and self.config.quiet_channel:
            channel = self.config.quiet_channel

        title, body = self._build_message(reminder, channel, quiet_mode)
        self.logger.info(
            "spug.notify.dispatch",
            token=reminder.event.token,
            channel=channel,
            quiet=quiet_mode,
            offset=reminder.offset_minutes,
        )

        if not self.config.xsend_user_id:
            raise SpugError("Spug configuration incomplete. Provide SPUG_XSEND_USER_ID.")

        return self._xsend(channel, title, body)

    def _build_message(self, reminder: Reminder, channel: str, quiet_mode: bool) -> tuple[str, str]:
        event = reminder.event
        title = f"[Alpha 提醒] {event.token}"

        if event.start_time:
            time_line = f"开盘时间：{event.start_time.strftime('%Y-%m-%d %H:%M')}"
        else:
            time_line = f"原始时间：{event.raw_time or '待定'}"

        points = (
            event.details.get("points")
            or event.details.get("积分")
            or "未知"
        )

        lines = [
            time_line,
            f"项目：{event.token}",
            f"积分：{points}",
            "请及时关注最新公告。",
        ]

        body = "\n".join(lines)
        return title, body

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(SpugError),
    )
    def _xsend(self, channel: str, title: str, body: str) -> NotificationResult:
        url = f"{self.config.base_url.rstrip('/')}/xsend/{self.config.xsend_user_id}"
        params = {
            "title": title,
            "content": body,
        }
        if channel:
            params["channel"] = channel

        response = self._request(url, params)
        if response.status_code >= 300:
            raise SpugError(f"xsend failed: {response.status_code} {response.text}")
        self.logger.info("spug.xsend.success", channel=channel)
        return NotificationResult(
            endpoint="/xsend",
            payload=dict(params),
            status_code=response.status_code,
            response_body=_safe_json(response),
        )

    def _request(self, url: str, params: dict) -> requests.Response:
        headers = {}
        if self.config.token:
            headers["Authorization"] = f"Token {self.config.token}"
        proxies = None
        if self.config.proxy:
            proxies = {
                "http": self.config.proxy,
                "https": self.config.proxy,
            }
        try:
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=self.config.timeout_seconds,
                proxies=proxies,
            )
            return response
        except requests.RequestException as exc:
            raise SpugError(str(exc)) from exc


def _safe_json(response: requests.Response) -> Optional[dict]:
    try:
        return response.json()
    except ValueError:
        return None
