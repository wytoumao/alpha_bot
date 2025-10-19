import json
from pathlib import Path

from collector.parser import parse_html_document, parse_json_payloads


FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_json_payloads_extracts_events():
    payload = json.loads((FIXTURES / "airdrop.json").read_text(encoding="utf-8"))
    events = parse_json_payloads([payload])
    tokens = {event.token for event in events}
    assert "ALPHA" in tokens
    assert "BETA" in tokens
    assert any(event.raw_time == "TBA" for event in events)


def test_parse_html_document_maps_sections_and_tba():
    html = (FIXTURES / "airdrop.html").read_text(encoding="utf-8")
    events = parse_html_document(html)
    assert len(events) == 2
    today_event = next(event for event in events if event.section == "today")
    assert today_event.token == "DELTA"
    upcoming_event = next(event for event in events if event.section == "upcoming")
    assert upcoming_event.raw_time.lower() == "tba"


def test_parse_html_document_handles_empty_state():
    html = (FIXTURES / "empty.html").read_text(encoding="utf-8")
    events = parse_html_document(html)
    assert events == []
