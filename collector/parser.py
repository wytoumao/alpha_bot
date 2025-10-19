from __future__ import annotations

import itertools
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bs4 import BeautifulSoup

from .models import Event

SECTION_KEYWORDS = {
    "today": {
        "today",
        "today's airdrops",
        "今日",
        "今日上币",
        "今日空投",
        "today list",
    },
    "upcoming": {
        "upcoming",
        "即将",
        "即将上币",
        "即将空投",
        "upcoming list",
    },
}

TOKEN_KEYS = ["token", "coin", "project", "name", "symbol", "ticker"]
TIME_KEYS = ["time", "start_time", "startTime", "listing_time", "airdrop_time", "airdropTime"]
DETAIL_KEYS = ["amount", "reward", "notes", "details", "detail", "info", "description"]


def parse_json_payloads(payloads: Iterable[Dict[str, Any]]) -> List[Event]:
    events: List[Event] = []
    for payload in payloads:
        events.extend(_extract_events_from_json(payload))
    return events


def _extract_events_from_json(payload: Dict[str, Any]) -> List[Event]:
    events: List[Event] = []
    for section, items in _iter_candidate_lists(payload):
        section_label = _normalize_section(section)
        for item in items:
            if not isinstance(item, dict):
                continue
            token = _select_first(item, TOKEN_KEYS)
            if not token:
                continue
            time_value = _select_first(item, TIME_KEYS)
            raw_time = str(time_value) if time_value is not None else ""
            details = {
                key: value
                for key, value in item.items()
                if key not in TOKEN_KEYS + TIME_KEYS
            }
            events.append(
                Event(
                    token=str(token).strip(),
                    section=section_label,
                    raw_time=raw_time,
                    start_time=None,  # resolved later
                    details=details,
                    source="json",
                )
            )
    return events


def _iter_candidate_lists(payload: Any, current_key: str = "") -> Iterable[Tuple[str, List[Dict[str, Any]]]]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            nested_key = f"{current_key}.{key}" if current_key else str(key)
            if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
                yield nested_key, value
            else:
                yield from _iter_candidate_lists(value, nested_key)
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            nested_key = f"{current_key}[{index}]" if current_key else str(index)
            yield from _iter_candidate_lists(item, nested_key)
    return []


def parse_html_document(html: str) -> List[Event]:
    soup = BeautifulSoup(html, "html.parser")
    events: List[Event] = []
    seen_rows: set[Tuple[str, str]] = set()

    for header in soup.find_all(["h1", "h2", "h3", "h4"]):
        section_label = _normalize_section(header.get_text(" ", strip=True))
        if not section_label:
            continue
        table = header.find_next("table")
        if table:
            events.extend(_parse_table_section(table, section_label, seen_rows))
            continue
        card_container = header.find_next("div")
        if card_container:
            card_events = _parse_card_section(card_container, section_label, seen_rows)
            events.extend(card_events)
    return events


def _parse_table_section(table, section_label: str, seen_rows: set[Tuple[str, str]]) -> List[Event]:
    events: List[Event] = []
    headers: List[str] = []
    header_row = table.find("tr")
    if header_row:
        headers = [cell.get_text(" ", strip=True).lower() for cell in header_row.find_all(["th", "td"])]

    for row in table.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
        if not cells or (headers and cells == headers):
            continue
        token = _detect_token_from_row(cells, headers)
        if not token:
            continue
        time_value = _detect_time_from_row(cells, headers)
        raw_time = time_value or ""
        key = (section_label, f"{token}|{raw_time}")
        if key in seen_rows:
            continue
        seen_rows.add(key)
        details = _build_details_from_row(cells, headers)
        events.append(
            Event(
                token=token,
                section=section_label,
                raw_time=raw_time,
                start_time=None,
                details=details,
                source="dom",
            )
        )
    return events


def _parse_card_section(container, section_label: str, seen_rows: set[Tuple[str, str]]) -> List[Event]:
    events: List[Event] = []
    cards = container.find_all("div", recursive=False)
    if not cards:
        cards = container.find_all("div")
    for card in cards:
        text_fragments = [frag.strip() for frag in card.get_text("\n", strip=True).splitlines() if frag.strip()]
        if not text_fragments:
            continue
        token = text_fragments[0]
        time_value = ""
        for fragment in text_fragments[1:]:
            if _looks_like_time(fragment):
                time_value = fragment
                break
        key = (section_label, f"{token}|{time_value}")
        if key in seen_rows:
            continue
        seen_rows.add(key)
        details = {"lines": text_fragments[1:]}
        events.append(
            Event(
                token=token,
                section=section_label,
                raw_time=time_value,
                start_time=None,
                details=details,
                source="dom",
            )
        )
    return events


def _normalize_section(text: str) -> str:
    lowered = text.lower()
    for canonical, keywords in SECTION_KEYWORDS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            return canonical
    return "today" if "today" in lowered else "upcoming" if "upcoming" in lowered else "unknown"


def _select_first(data: Dict[str, Any], keys: Iterable[str]) -> Optional[Any]:
    for key in keys:
        for candidate in (key, key.capitalize(), key.upper(), key.lower()):
            if candidate in data and data[candidate]:
                return data[candidate]
    return None


def _detect_token_from_row(cells: List[str], headers: List[str]) -> Optional[str]:
    if headers:
        for idx, header in enumerate(headers):
            if any(token_key in header for token_key in ["token", "coin", "项目", "name", "symbol"]):
                return cells[idx].strip()
    return cells[0].strip() if cells else None


def _detect_time_from_row(cells: List[str], headers: List[str]) -> Optional[str]:
    if headers:
        for idx, header in enumerate(headers):
            if any(time_key in header for time_key in ["time", "时间", "时刻", "开始"]):
                return cells[idx].strip()
    for cell in cells:
        if _looks_like_time(cell):
            return cell.strip()
    return None


def _build_details_from_row(cells: List[str], headers: List[str]) -> Dict[str, Any]:
    if not headers:
        return {"columns": cells}
    details = {}
    for header, cell in itertools.zip_longest(headers, cells, fillvalue=""):
        if not header:
            continue
        header_clean = re.sub(r"\s+", "_", header.strip().lower())
        if header_clean in ("token", "coin", "name", "symbol", "time", "时间"):
            continue
        details[header_clean] = cell.strip()
    return details


def _looks_like_time(value: str) -> bool:
    value = value.strip()
    if not value:
        return False
    if re.search(r"\d{1,2}:\d{2}", value):
        return True
    if re.search(r"\d{4}-\d{2}-\d{2}", value):
        return True
    if value.lower() in {"tba", "to be announced", "—", "-", "n/a"}:
        return True
    return False
