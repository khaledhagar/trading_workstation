import time
from datetime import date

import httpx
import pytest

from app.market import MarketDataUnavailableError
from app.market.massive.client import (
    GROUPED_PATH,
    SNAPSHOT_PATH,
    MassiveAuthError,
    MassiveClient,
    MassiveError,
    PlanNotEntitledError,
    RateLimitedError,
)


def client_with(handler, **kw) -> MassiveClient:
    return MassiveClient("secret-key", transport=httpx.MockTransport(handler), **kw)


def client_returning(status: int, seen: list | None = None, body=None, **kw) -> MassiveClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json={"tickers": []} if body is None else body)
    return client_with(handler, **kw)


@pytest.mark.parametrize(
    "status, exc",
    [(401, MassiveAuthError), (403, PlanNotEntitledError), (429, RateLimitedError),
     (404, MassiveError), (500, MassiveError), (502, MassiveError)],
)
async def test_status_mapping(status, exc):
    client = client_returning(status)
    with pytest.raises(exc):
        await client.snapshots(["AAPL"])
    await client.aclose()


def test_every_massive_error_is_a_503():
    for exc in (MassiveError, MassiveAuthError, PlanNotEntitledError, RateLimitedError):
        assert issubclass(exc, MarketDataUnavailableError)


async def test_key_in_header_not_url():
    seen: list[httpx.Request] = []
    client = client_returning(200, seen)
    await client.snapshots(["MSFT", "AAPL", "MSFT"])
    req = seen[0]
    assert req.headers["Authorization"] == "Bearer secret-key"
    assert "secret-key" not in str(req.url)
    assert req.url.path == SNAPSHOT_PATH
    assert req.url.params["tickers"] == "AAPL,MSFT"            # sorted, deduplicated
    assert client.calls == 1
    await client.aclose()


async def test_key_not_in_error_messages():
    client = client_returning(401)
    with pytest.raises(MassiveAuthError) as info:
        await client.snapshots(["AAPL"])
    assert "secret-key" not in str(info.value)
    await client.aclose()


async def test_empty_ticker_list_makes_no_call():
    seen: list[httpx.Request] = []
    client = client_returning(200, seen)
    assert await client.snapshots([]) == {}
    assert seen == [] and client.calls == 0
    await client.aclose()


async def test_snapshots_keyed_by_ticker_and_skips_malformed_rows():
    body = {"tickers": [{"ticker": "AAPL", "min": {"c": 1}}, {"min": {"c": 2}}, "junk", {"ticker": ""}]}
    client = client_returning(200, body=body)
    assert await client.snapshots(["AAPL"]) == {"AAPL": {"ticker": "AAPL", "min": {"c": 1}}}
    await client.aclose()


@pytest.mark.parametrize("body", [{"status": "OK"}, {"tickers": None}, {"tickers": "x"}])
async def test_snapshots_without_rows(body):
    client = client_returning(200, body=body)
    assert await client.snapshots(["AAPL"]) == {}
    await client.aclose()


async def test_grouped_daily_request_and_parse():
    seen: list[httpx.Request] = []
    body = {"results": [{"T": "AAPL", "c": 191.0}, {"T": "MSFT", "c": 421.0}]}
    client = client_returning(200, seen, body=body)
    assert await client.grouped_daily(date(2026, 10, 16)) == {"AAPL": 191.0, "MSFT": 421.0}
    assert seen[0].url.path == GROUPED_PATH.format(day="2026-10-16")
    assert seen[0].url.params["adjusted"] == "true"
    await client.aclose()


async def test_network_error_becomes_massive_error():
    def handler(request):
        raise httpx.ConnectError("boom", request=request)
    client = client_with(handler)
    with pytest.raises(MassiveError, match="ConnectError"):
        await client.snapshots(["AAPL"])
    await client.aclose()


async def test_timeout_becomes_massive_error():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)
    client = client_with(handler)
    with pytest.raises(MassiveError, match="ReadTimeout"):
        await client.grouped_daily(date(2026, 10, 16))
    await client.aclose()


async def test_invalid_json_becomes_massive_error():
    client = client_with(lambda request: httpx.Response(200, content=b"<html>oops"))
    with pytest.raises(MassiveError, match="invalid JSON"):
        await client.snapshots(["AAPL"])
    await client.aclose()


async def test_non_object_json_becomes_massive_error():
    client = client_returning(200, body=[1, 2, 3])
    with pytest.raises(MassiveError, match="unexpected"):
        await client.snapshots(["AAPL"])
    await client.aclose()


async def test_min_interval_spaces_calls():
    client = client_returning(200, min_interval=0.05)
    t0 = time.monotonic()
    await client.snapshots(["AAPL"])
    await client.snapshots(["AAPL"])
    await client.snapshots(["AAPL"])
    assert time.monotonic() - t0 >= 0.09     # 2 gaps; slack for Windows' ~16 ms clock
    await client.aclose()


async def test_no_spacing_by_default():
    client = client_returning(200)
    t0 = time.monotonic()
    for _ in range(5):
        await client.snapshots(["AAPL"])
    assert time.monotonic() - t0 < 0.5
    await client.aclose()
