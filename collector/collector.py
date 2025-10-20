from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from alpha_logging import get_logger
from playwright.async_api import Response, TimeoutError, async_playwright
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential
from zoneinfo import ZoneInfo

from .models import Event
from .parser import parse_html_document, parse_json_payloads

TOOL_SUBSTRINGS = ("工具", "通知", "看板", "提示", "帮助", "目标", "模拟", "推特")


class AlphaCollector:
    def __init__(
        self,
        url: str,
        locale: str = "en",
        wait_selector: str | None = None,
        extra_wait_ms: int = 1000,
        timezone: str = "Asia/Taipei",
        proxy: Optional[str] = None,
        goto_timeout_ms: int = 60000,
    ):
        self.url = url
        self.locale = locale
        self.wait_selector = wait_selector
        self.extra_wait_ms = extra_wait_ms
        self.timezone = timezone
        self.proxy = proxy
        self.goto_timeout_ms = goto_timeout_ms
        self.logger = get_logger(__name__, url=url)

    async def fetch_events(self) -> List[Event]:
        json_payloads: List[Dict[str, Any]] = []
        html_content = ""
        now = datetime.now(ZoneInfo(self.timezone))

        self.logger.info("collector.fetch.start")

        async def runner() -> None:
            nonlocal json_payloads, html_content
            async with async_playwright() as playwright:
                launch_kwargs: Dict[str, Any] = {"headless": True}
                if self.proxy:
                    proxy_config = self._build_proxy_config(self.proxy)
                    launch_kwargs["proxy"] = proxy_config
                    self.logger.info(
                        "collector.proxy.enabled",
                        server=proxy_config.get("server"),
                        authenticated="username" in proxy_config,
                    )
                browser = await playwright.chromium.launch(**launch_kwargs)
                try:
                    page = await browser.new_page()
                    self.logger.info("collector.browser.ready")
                    page.on("response", lambda r: asyncio.create_task(self._track_response(r, json_payloads)))
                    await page.goto(
                        self.url,
                        wait_until="domcontentloaded",
                        timeout=self.goto_timeout_ms,
                    )
                    self.logger.info("collector.page.loaded")
                    if self.wait_selector:
                        try:
                            await page.wait_for_selector(self.wait_selector, timeout=self.goto_timeout_ms // 2)
                        except TimeoutError:
                            self.logger.warning("collector.selector_timeout", selector=self.wait_selector)
                    if self.extra_wait_ms:
                        await page.wait_for_timeout(self.extra_wait_ms)
                    html_content = await page.content()
                finally:
                    await browser.close()

        retry = AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        )
        async for attempt in retry:
            with attempt:
                await runner()

        events: List[Event] = []
        if json_payloads:
            events.extend(parse_json_payloads(json_payloads))
        if html_content:
            events.extend(parse_html_document(html_content))
        deduped = self._deduplicate(events)
        enriched = self._enrich_and_filter(deduped, now)
        self.logger.info(
            "collector.fetch.complete",
            raw_events=len(events),
            json_payloads=len(json_payloads),
            events=len(enriched),
        )
        return enriched

    async def _track_response(self, response: Response, sink: List[Dict[str, Any]]) -> None:
        try:
            if "/api/" not in response.url:
                return
            if response.request.resource_type not in {"xhr", "fetch"}:
                return
            if response.status != 200:
                return
            text = await response.text()
            if not text:
                return
            payload = json.loads(text)
            if isinstance(payload, dict):
                sink.append(payload)
            elif isinstance(payload, list):
                sink.append({"payload": payload})
            self.logger.info("collector.api.captured", url=response.url)
        except Exception as exc:  # best-effort logging only
            self.logger.debug("collector.response_parse_failed", url=response.url, error=str(exc))

    def _deduplicate(self, events: List[Event]) -> List[Event]:
        unique: dict[tuple[str, str], Event] = {}
        for event in events:
            key = (event.section, f"{event.token}|{event.raw_time}")
            if key not in unique or unique[key].source == "dom":
                unique[key] = event
        return list(unique.values())

    def _enrich_and_filter(self, events: List[Event], now: datetime) -> List[Event]:
        today_str = now.strftime("%Y-%m-%d")
        filtered: List[Event] = []
        tool_drops = 0
        non_today_drops = 0

        for event in events:
            if isinstance(event.details, dict):
                date_value = event.details.get("date") or event.details.get("Date")
                if date_value:
                    date_str = str(date_value).strip()
                    if date_str:
                        event.details["date"] = date_str
                        event.section = "today" if date_str == today_str else "upcoming"

            if self._is_tool_card(event):
                self.logger.debug("collector.filter.tool_card", token=event.token)
                tool_drops += 1
                continue

            if event.section != "today":
                non_today_drops += 1
                continue

            filtered.append(event)

        self.logger.info(
            "collector.filter.summary",
            today=today_str,
            kept=len(filtered),
            tool_drops=tool_drops,
            non_today_drops=non_today_drops,
        )
        return filtered

    def _is_tool_card(self, event: Event) -> bool:
        token = event.token or ""
        if any(keyword in token for keyword in TOOL_SUBSTRINGS):
            return True
        details = event.details or {}
        if isinstance(details, dict):
            if any(key in details for key in ("tool", "工具")):
                return True
            lines = details.get("lines")
            if isinstance(lines, list) and any(isinstance(item, str) and any(keyword in item for keyword in TOOL_SUBSTRINGS) for item in lines):
                return True
        return False

    def _build_proxy_config(self, proxy_value: str) -> Dict[str, Any]:
        parsed = urlparse(proxy_value)
        if not parsed.scheme:
            return {"server": proxy_value}
        server = f"{parsed.scheme}://{parsed.hostname}"
        if parsed.port:
            server += f":{parsed.port}"
        proxy_config: Dict[str, Any] = {"server": server}
        if parsed.username:
            proxy_config["username"] = parsed.username
        if parsed.password:
            proxy_config["password"] = parsed.password
        return proxy_config
