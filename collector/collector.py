from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

import structlog
from playwright.async_api import Browser, Page, Response, TimeoutError, async_playwright
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from .models import Event
from .parser import parse_html_document, parse_json_payloads


class AlphaCollector:
    def __init__(
        self,
        url: str,
        locale: str = "en",
        wait_selector: str | None = None,
        extra_wait_ms: int = 1000,
    ):
        self.url = url
        self.locale = locale
        self.wait_selector = wait_selector
        self.extra_wait_ms = extra_wait_ms
        self.logger = structlog.get_logger(__name__)

    async def fetch_events(self) -> List[Event]:
        json_payloads: List[Dict[str, Any]] = []
        html_content = ""

        async def runner() -> None:
            nonlocal json_payloads, html_content
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                try:
                    page = await browser.new_page()
                    page.on("response", lambda r: asyncio.create_task(self._track_response(r, json_payloads)))
                    await page.goto(self.url, wait_until="networkidle")
                    if self.wait_selector:
                        try:
                            await page.wait_for_selector(self.wait_selector, timeout=8000)
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
        return self._deduplicate(events)

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
        except Exception as exc:  # best-effort logging only
            self.logger.debug("collector.response_parse_failed", url=response.url, error=str(exc))

    def _deduplicate(self, events: List[Event]) -> List[Event]:
        unique: dict[tuple[str, str], Event] = {}
        for event in events:
            key = (event.section, f"{event.token}|{event.raw_time}")
            if key not in unique or unique[key].source == "dom":
                unique[key] = event
        return list(unique.values())
