import json
from datetime import datetime, timezone

from app.market import PriceCache, price_events

from .fakes import FakeRequest


async def collect(cache: PriceCache, events: int) -> list[str]:
    return [e async for e in price_events(cache, FakeRequest(events), interval=0)]


async def test_event_format():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    events = await collect(cache, 2)
    assert events[0] == "retry: 2000\n\n"
    assert len(events) == 3                                    # retry + 2 data events
    assert events[1].startswith("data: ") and events[1].endswith("\n\n")
    payload = json.loads(events[1].removeprefix("data: "))
    assert payload["AAPL"]["price"] == 190.0
    assert payload["AAPL"]["timestamp"].endswith("Z")


async def test_payload_matches_plan_contract():
    cache = PriceCache()
    ts = datetime(2026, 1, 1, 12, 0, 0, 500_000, tzinfo=timezone.utc)
    cache.update("AAPL", 190.05, reference_price=189.21)
    cache.update("AAPL", 190.12, timestamp=ts)
    cache.update("MSFT", 420.0)
    payload = json.loads((await collect(cache, 1))[1].removeprefix("data: "))
    assert set(payload) == {"AAPL", "MSFT"}
    assert payload["AAPL"] == {
        "ticker": "AAPL", "price": 190.12, "previous_price": 190.05,
        "timestamp": "2026-01-01T12:00:00.500Z", "direction": "up", "change_percent": 0.48,
    }


async def test_compact_json_single_line():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    cache.update("MSFT", 420.0)
    data = (await collect(cache, 1))[1]
    assert data.count("\n") == 2 and ", " not in data and ": " not in data.removeprefix("data: ")


async def test_empty_cache_sends_empty_object():
    events = await collect(PriceCache(), 1)
    assert events[1] == "data: {}\n\n"


async def test_emits_while_unchanged():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    events = await collect(cache, 3)
    assert len(events) == 4 and events[1] == events[2] == events[3]


async def test_reflects_cache_changes_between_events():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    stream = price_events(cache, FakeRequest(10), interval=0)
    await anext(stream)                                        # retry
    first = json.loads((await anext(stream)).removeprefix("data: "))
    cache.remove("AAPL")
    cache.update("PYPL", 70.0)
    second = json.loads((await anext(stream)).removeprefix("data: "))
    await stream.aclose()
    assert set(first) == {"AAPL"} and set(second) == {"PYPL"}


async def test_stops_when_client_disconnects():
    events = await collect(PriceCache(), 0)
    assert events == ["retry: 2000\n\n"]
