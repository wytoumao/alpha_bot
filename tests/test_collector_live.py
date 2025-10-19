import os

import pytest

from collector.collector import AlphaCollector


@pytest.mark.asyncio
async def test_alpha_collect_live():
    if not os.getenv("ALPHA_LIVE_TEST"):
        pytest.skip("Set ALPHA_LIVE_TEST=1 to enable live collector test.")

    url = os.getenv("ALPHA_URL", "https://alpha123.uk/zh")
    collector = AlphaCollector(url)

    events = await collector.fetch_events()

    assert isinstance(events, list)
    assert all(event.token for event in events)
