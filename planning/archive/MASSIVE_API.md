# Massive API (formerly Polygon.io): Stock Prices Reference

Reference for the Massive REST endpoints this project uses to get **real-time / delayed** and **end-of-day** prices for **multiple tickers**. It is the research behind [`MARKET_INTERFACE.md`](MARKET_INTERFACE.md), which defines how the backend actually uses these endpoints.

*Researched 2026-10-18 from the official docs (`massive.com/docs`, index at `massive.com/llms.txt`), the pricing page, and the source of the official Python client (`github.com/massive-com/client-python`, PyPI `massive` 2.9.0).*

---

## 1. Key Facts at a Glance

| Item | Value |
|---|---|
| Base URL | `https://api.massive.com` (the old `https://api.polygon.io` still works during the transition) |
| Auth | `Authorization: Bearer <key>` header **or** `?apiKey=<key>` query parameter |
| Env var | `MASSIVE_API_KEY` (the official client also reads this name by default) |
| Ticker case | **Case-sensitive**: always send uppercase (`AAPL`, `BRK.B`) |
| Timestamps | Mixed units. Bars (`t`) are **Unix milliseconds**; trades, quotes and the snapshot `updated` field are **Unix nanoseconds** |
| Official Python client | `pip install massive` / `uv add massive`, `from massive import RESTClient`, Python ≥ 3.10, **synchronous** (urllib3) |

### ⚠️ The plan tier decides which endpoints you can call

This is the most important finding, and it **changes an assumption in `PLAN.md` §6**: the multi-ticker snapshot endpoint is **not available on the free plan**.

| Plan | Price/month | Rate limit | Data recency | History | Snapshots | Last Trade |
|---|---|---|---|---|---|---|
| **Basic** (free) | $0 | **5 calls / minute** | **End-of-day** | 2 years | ❌ Not included | ❌ |
| **Starter** | $29 | Unlimited | 15-minute delayed | 5 years | ✅ | ❌ |
| **Developer** | $79 | Unlimited | 15-minute delayed | 10 years | ✅ | ✅ |
| **Advanced** | $199 | Unlimited | Real-time | 20+ years | ✅ | ✅ |

(Annual billing is 20% cheaper. There are also Business plans, which add `fmv` and are irrelevant here.)

What this means for the project:

- **Free key → end-of-day prices only.** The right tool is *Daily Market Summary* (one call returns every US stock's OHLC for a date), not the snapshot. Prices change once per trading day, so the live stream will look flat.
- **Starter or above → the Full Market Snapshot** with a `tickers=` filter. One call returns all watched tickers, and there's no rate limit, so polling every 2–15 s is fine.
- Requesting an endpoint your plan doesn't include returns **HTTP 403**. The backend uses that to detect the plan automatically (see `MARKET_INTERFACE.md` §5).

---

## 2. Endpoints Used by This Project

| # | Purpose | Endpoint | Free? | Tickers per call |
|---|---|---|---|---|
| 2.1 | Live prices, many tickers | `GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=…` | ❌ | Any number (empty = whole market) |
| 2.2 | Live price, one ticker | `GET /v2/snapshot/locale/us/markets/stocks/tickers/{ticker}` | ❌ | 1 |
| 2.3 | EOD prices, whole market | `GET /v2/aggs/grouped/locale/us/market/stocks/{date}` | ✅ | All (~10k) |
| 2.4 | Previous close, one ticker | `GET /v2/aggs/ticker/{ticker}/prev` | ✅ | 1 |
| 2.5 | Daily open/close, one ticker | `GET /v1/open-close/{ticker}/{date}` | ✅ | 1 |
| 2.6 | Historical bars | `GET /v2/aggs/ticker/{ticker}/range/{mult}/{timespan}/{from}/{to}` | ✅ | 1 |
| 2.7 | Live, many tickers (alt.) | `GET /v3/snapshot?ticker.any_of=…` | ❌ | ≤ 250, paginated |
| 2.8 | Last trade, one ticker | `GET /v2/last/trade/{ticker}` | ❌ (Developer+) | 1 |
| 2.9 | Market open/closed | `GET /v1/marketstatus/now` | ✅ | n/a |
| 2.10 | Ticker exists? | `GET /v3/reference/tickers/{ticker}` | ✅ | 1 |

The backend only *needs* **2.1** (paid) and **2.3** (free). The rest are documented for completeness and future features.

### 2.1 Full Market Snapshot (filtered to our tickers): the paid-tier workhorse

`GET /v2/snapshot/locale/us/markets/stocks/tickers`

| Query param | Type | Description |
|---|---|---|
| `tickers` | string | Comma-separated, case-sensitive list, e.g. `AAPL,TSLA,GOOG`. **Empty or omitted returns the whole market** (10,000+ tickers), so always pass it |
| `include_otc` | bool | Include OTC securities. Default `false` |

Plan access: Starter/Developer (15-min delayed), Advanced (real-time). **Not on Basic.**

Data reset: snapshot data is **cleared daily at 3:30 AM ET** and repopulates from ~4:00 AM ET. Between those times, fields can be missing or zero.

**Sample response** (from the docs):

```json
{
  "count": 1,
  "status": "OK",
  "tickers": [
    {
      "ticker": "BCAT",
      "day":      {"o": 20.64, "h": 20.64, "l": 20.506, "c": 20.506, "v": 37216, "vw": 20.616, "dv": "37216.0"},
      "min":      {"o": 20.506, "h": 20.506, "l": 20.506, "c": 20.506, "v": 5000, "vw": 20.5105,
                   "av": 37216, "n": 1, "t": 1684428600000, "dv": "5000.0", "dav": "37216.0"},
      "prevDay":  {"o": 20.79, "h": 21, "l": 20.5, "c": 20.63, "v": 292738, "vw": 20.6939},
      "lastTrade":{"p": 20.506, "s": 2416, "t": 1605192894630916600, "x": 4, "i": "71675577320245", "c": [14, 41], "ds": "2416.0"},
      "lastQuote":{"p": 20.5, "s": 13, "P": 20.6, "S": 22, "t": 1605192959994246100},
      "todaysChange": -0.124,
      "todaysChangePerc": -0.601,
      "updated": 1605192894630916600
    }
  ]
}
```

**Field reference**

| Field | Meaning | Notes |
|---|---|---|
| `ticker` | Symbol | |
| `day` | Today's bar so far: `o h l c v vw` | Can be all zeros before the session's first trade |
| `min` | Latest minute bar: `o h l c v vw`, `av` (accumulated volume), `n` (trades), `t` (**ms**) | |
| `prevDay` | Previous session's bar | `prevDay.c` = **previous close**, our reference price |
| `lastTrade` | `p` price, `s` size, `t` (**ns**), `x` exchange, `c` conditions | **Only if your plan includes trades.** Starter does **not**, so don't rely on it |
| `lastQuote` | `p`/`s` bid price/size, `P`/`S` ask price/size, `t` (**ns**) | Only if your plan includes quotes |
| `todaysChange` / `todaysChangePerc` | Change vs previous close | We compute our own `change_percent` from `prevDay.c` instead |
| `updated` | Last update (**ns**) | |

**Choosing "the current price" from a snapshot.** Use the first value that is present and > 0:

1. `lastTrade.p`: most precise, but missing on Starter
2. `min.c`: close of the latest minute bar
3. `day.c`: today's close so far
4. `prevDay.c`: before today's first trade, the last known price *is* yesterday's close

Tickers that Massive doesn't know about are simply **absent** from `tickers[]`, with no error. That is how an add is validated (see §5).

### 2.2 Single Ticker Snapshot

`GET /v2/snapshot/locale/us/markets/stocks/tickers/{stocksTicker}`: same object as one element of 2.1, wrapped as `{"status": "OK", "request_id": "…", "ticker": {…}}`. Same plan access as 2.1. An unknown ticker returns **404** (`status: "NOT_FOUND"`). The project uses 2.1 with a one-ticker `tickers=` list instead, so both cases go through one code path.

### 2.3 Daily Market Summary (Grouped Daily): the free-tier workhorse

`GET /v2/aggs/grouped/locale/us/market/stocks/{date}`

| Param | Type | Description |
|---|---|---|
| `date` (path) | `YYYY-MM-DD` | Trading date |
| `adjusted` | bool | Split-adjusted. Default `true` |
| `include_otc` | bool | Default `false` |

Plan access: **all plans**. Basic gets end-of-day data with 2 years of history.

```json
{
  "adjusted": true,
  "queryCount": 3,
  "resultsCount": 3,
  "status": "OK",
  "request_id": "…",
  "results": [
    {"T": "KIMpL", "o": 26.07, "h": 26.25, "l": 25.91, "c": 25.9102, "v": 4369,   "vw": 26.0407, "n": 74,   "t": 1602705600000},
    {"T": "VSAT",  "o": 34.9,  "h": 35.47, "l": 34.21, "c": 34.24,   "v": 312583, "vw": 34.4736, "n": 4966, "t": 1602705600000}
  ]
}
```

- `T` = ticker, `c` = close for that day, `t` = **ms** timestamp of the end of the window, `otc` present only when true.
- **One call returns every US stock**, which is ideal at 5 calls/minute. With two calls (latest trading day plus the one before) you get today's price (`c` of the latest day) and the reference price (`c` of the day before) for *any* ticker, so validating a newly added ticker needs **no extra call**.
- For a weekend, a holiday, or a date whose data isn't published yet, it returns `resultsCount: 0` and no `results` (or an empty array). Walk back one trading day and retry.
- The response is large (~10k rows, roughly 1 MB gzip-compressed). Refresh it occasionally, not on every tick.

### 2.4 Previous Day Bar

`GET /v2/aggs/ticker/{stocksTicker}/prev?adjusted=true`: all plans.

```json
{
  "ticker": "AAPL", "adjusted": true, "queryCount": 1, "resultsCount": 1, "status": "OK",
  "results": [{"T": "AAPL", "o": 115.55, "h": 117.59, "l": 114.13, "c": 115.97, "v": 131704427, "vw": 116.3058, "t": 1605042000000}]
}
```

One ticker per call, so at 5 calls/minute it doesn't scale to a 10-ticker watchlist. Use 2.3 instead.

### 2.5 Daily Ticker Summary (Open/Close)

`GET /v1/open-close/{stocksTicker}/{date}`: all plans.

```json
{"status": "OK", "symbol": "AAPL", "from": "2023-01-09",
 "open": 324.66, "high": 326.2, "low": 322.3, "close": 325.12,
 "volume": 26122646, "preMarket": 324.5, "afterHours": 322.1}
```

Its unique value is `preMarket` / `afterHours`. It's also one ticker per call, so we don't use it.

### 2.6 Custom Bars (historical OHLC)

`GET /v2/aggs/ticker/{stocksTicker}/range/{multiplier}/{timespan}/{from}/{to}`

| Param | Description |
|---|---|
| `multiplier`, `timespan` | e.g. `1` + `minute`/`hour`/`day`/`week`/`month`/`quarter`/`year` |
| `from`, `to` | `YYYY-MM-DD` or Unix-ms timestamp |
| `adjusted` | Default `true` |
| `sort` | `asc` / `desc` |
| `limit` | Base aggregates used, default 5,000, max 50,000 |

The response has `results[]` of `{o,h,l,c,v,vw,n,t}` (`t` = **ms**, start of the bar) and an optional **`next_url`** for pagination; the official client follows it automatically. All plans (Basic: end-of-day).

*Not used today*: PLAN.md §6 deliberately has no server-side price history. This is the endpoint to use if the main chart should ever be pre-filled with history.

### 2.7 Unified Snapshot (alternative to 2.1)

`GET /v3/snapshot?ticker.any_of=AAPL,MSFT&limit=250`: multi-asset, up to 250 tickers, **paginated** (`limit` defaults to **10**, so always set it), with snake_case fields (`last_trade.price`, `session.close`, `session.previous_close`, `market_status`). Unknown tickers come back as items with an `error`/`message` instead of being dropped. Not on Basic. 2.1 is simpler for stocks-only and needs no pagination, so we prefer it.

### 2.8 Last Trade

`GET /v2/last/trade/{stocksTicker}` → `{"status": "OK", "results": {"T": "AAPL", "p": 129.8473, "s": 25, "t": 1617901342969834000, …}}`. **Developer plan and above only**, one ticker per call. The snapshot already contains the same data.

### 2.9 Market Status

`GET /v1/marketstatus/now` (all plans): `market` (`"open"`, `"closed"`, `"extended-hours"`), `earlyHours`, `afterHours`, `exchanges.nyse`/`nasdaq`, `serverTime`. This could later drive a "Market closed" badge, or slow polling outside market hours. Optional.

### 2.10 Ticker Overview

`GET /v3/reference/tickers/{ticker}` (all plans): `results.name`, `results.active`, `results.market`, … It's a clean way to validate a symbol and fetch a company name, but it costs one call per ticker. In free mode the grouped-daily data already answers "does it exist?", so we don't need it.

---

## 3. Authentication & Errors

```bash
# Header (preferred: keeps the key out of URLs and logs)
curl -H "Authorization: Bearer $MASSIVE_API_KEY" \
  "https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT"

# Query parameter
curl "https://api.massive.com/v2/aggs/grouped/locale/us/market/stocks/2026-10-16?adjusted=true&apiKey=$MASSIVE_API_KEY"
```

| HTTP | Meaning | How the backend reacts |
|---|---|---|
| 200 | OK, `status` is `"OK"` (or `"DELAYED"` for delayed data) | Parse |
| 401 | Missing/invalid key | Log an error, keep the last prices, retry on the next poll |
| 403 | Endpoint not in your plan (e.g. snapshot on Basic) | **Switch to end-of-day mode** |
| 404 | Unknown resource (single-ticker endpoints) | Treat the ticker as unknown |
| 429 | Rate limit exceeded (Basic: > 5/min) | Skip this poll and back off |
| 5xx | Server problem | Log, keep the last prices, retry on the next poll |

Error bodies are JSON shaped like `{"status": "ERROR" | "NOT_AUTHORIZED" | "NOT_FOUND", "request_id": "…", "error"/"message": "…"}`. The docs don't publish a full catalogue of messages, so **branch on the HTTP status code, never on the message text**.

---

## 4. Code Examples

### 4.1 Plain `httpx` (async): what the backend uses

The backend calls the REST API directly with `httpx.AsyncClient` rather than the official client, because the official client is synchronous and would block the event loop (and with it the SSE streams). Section 4.3 has the full reasoning.

```python
import os
import httpx

BASE_URL = "https://api.massive.com"

def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {os.environ['MASSIVE_API_KEY']}"},
        timeout=httpx.Timeout(10.0),
    )

async def fetch_snapshots(client: httpx.AsyncClient, tickers: list[str]) -> dict[str, dict]:
    """Paid plans: one call for all tickers. Returns {ticker: raw snapshot dict}."""
    resp = await client.get(
        "/v2/snapshot/locale/us/markets/stocks/tickers",
        params={"tickers": ",".join(sorted(tickers))},
    )
    resp.raise_for_status()  # 403 here means "plan has no snapshots"
    return {t["ticker"]: t for t in resp.json().get("tickers") or []}

async def fetch_grouped_daily(client: httpx.AsyncClient, day: str) -> dict[str, float]:
    """All plans: every US stock's close on `day` (YYYY-MM-DD). Empty dict if no data."""
    resp = await client.get(
        f"/v2/aggs/grouped/locale/us/market/stocks/{day}",
        params={"adjusted": "true"},
    )
    resp.raise_for_status()
    return {r["T"]: r["c"] for r in resp.json().get("results") or []}

def snapshot_price(snap: dict) -> float | None:
    """Best available current price, following the fallback order in §2.1."""
    for value in (
        (snap.get("lastTrade") or {}).get("p"),
        (snap.get("min") or {}).get("c"),
        (snap.get("day") or {}).get("c"),
        (snap.get("prevDay") or {}).get("c"),
    ):
        if value:  # skips None and 0
            return float(value)
    return None

def snapshot_reference(snap: dict) -> float | None:
    value = (snap.get("prevDay") or {}).get("c")
    return float(value) if value else None
```

Usage:

```python
async with make_client() as client:
    snaps = await fetch_snapshots(client, ["AAPL", "MSFT", "NVDA"])
    for ticker, snap in snaps.items():
        print(ticker, snapshot_price(snap), snapshot_reference(snap))
```

### 4.2 Finding the last two trading days (free tier)

```python
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo  # on Windows, add the `tzdata` package

NY = ZoneInfo("America/New_York")

def previous_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:  # Sat=5, Sun=6
        d -= timedelta(days=1)
    return d

async def latest_two_closes(client, max_calls: int = 5) -> tuple[dict[str, float], dict[str, float]]:
    """Return (latest_closes, previous_closes). Weekends are skipped without a call;
    holidays and not-yet-published days cost one call each and are skipped."""
    d = datetime.now(NY).date()
    if d.weekday() >= 5:
        d = previous_weekday(d)
    found: list[dict[str, float]] = []
    for _ in range(max_calls):
        closes = await fetch_grouped_daily(client, d.isoformat())
        if closes:
            found.append(closes)
            if len(found) == 2:
                return found[0], found[1]
        d = previous_weekday(d)
    raise RuntimeError("Could not find two trading days of data")
```

On Basic, calls must be **≥ 12 s apart** (5/min). The backend's client enforces that spacing itself (see `MARKET_INTERFACE.md` §5.3).

### 4.3 The official `massive` client (sync)

Useful for scripts, notebooks and quick checks. Inside FastAPI it would have to run in `asyncio.to_thread(...)`.

```python
from massive import RESTClient

client = RESTClient()             # reads MASSIVE_API_KEY; or RESTClient(api_key="...")
# client = RESTClient(retries=0)  # recommended on the free tier, see below

# 2.1: snapshot for several tickers (paid)
for s in client.get_snapshot_all("stocks", tickers=["AAPL", "MSFT", "NVDA"]):
    price = (s.last_trade.price if s.last_trade else None) or (s.min.close if s.min else None)
    print(s.ticker, price, s.prev_day.close if s.prev_day else None, s.todays_change_percent)

# 2.2: one ticker (paid)
s = client.get_snapshot_ticker("stocks", "AAPL")

# 2.3: whole-market end-of-day bars (free)
closes = {a.ticker: a.close for a in client.get_grouped_daily_aggs("2026-10-16", adjusted=True)}

# 2.4: previous close (free)
prev = client.get_previous_close_agg("AAPL")   # list of PreviousCloseAgg; prev[0].close

# 2.5: open/close for a date (free)
oc = client.get_daily_open_close_agg("AAPL", "2026-10-16")   # oc.open, oc.close, oc.after_hours

# 2.6: historical bars; the iterator follows next_url automatically (free)
bars = list(client.list_aggs("AAPL", 1, "day", "2026-09-01", "2026-10-16", limit=50000))

# 2.7: unified snapshot (paid)
snaps = list(client.list_universal_snapshots(ticker_any_of=["AAPL", "MSFT"], limit=250))

# 2.8 / 2.9
trade = client.get_last_trade("AAPL")          # Developer+ only
status = client.get_market_status()            # status.market == "open" | "closed" | ...
```

Model attribute names are snake_case (`last_trade.price`, `prev_day.close`, `todays_change_percent`, `min.close`, `updated`).

Things to know about the client:

| Behaviour | Detail | Consequence |
|---|---|---|
| Synchronous | Built on `urllib3` | Blocks the asyncio loop unless run in a thread |
| Auto-retry | `retries=3` by default on 413/429/499/5xx, with a backoff of 0.1 s, 0.2 s, 0.4 s | On the free tier, one rate-limited call can turn into **4 calls**, deepening the 429. Pass `retries=0` |
| Errors | `massive.exceptions.AuthError` (no key), `BadResponse` (any non-200; the body is the message) | No typed 403/429, so you'd parse the message, which section 3 advises against |
| Base URL | Defaults to `api.massive.com` | |
| Dependencies | `urllib3`, `websockets`, `certifi` | |

**Decision:** the backend uses `httpx.AsyncClient` (4.1). It's natively async, gives direct access to status codes, and has no hidden retries. We only need two endpoints, so the official client adds little. `httpx` is also easy to fake in tests with `httpx.MockTransport`.

---

## 5. Validating a Ticker Before Adding It

PLAN.md §6 requires an add to be rejected with `"Unknown ticker: XYZ"` when Massive has no data for it.

- **Paid (snapshot mode):** one call to 2.1 with `tickers=XYZ`. If the result list is empty, or the ticker has no usable price, it's unknown. The same response seeds the cache.
- **Free (end-of-day mode):** look `XYZ` up in the in-memory grouped-daily map (2.3). It's not there → unknown. **No API call is needed**, which matters at 5 calls/minute.

---

## 6. Practical Notes & Gotchas

- **Delayed ≠ broken.** On Starter/Developer, snapshot prices are 15 minutes old. That's fine for a demo terminal; the UI doesn't need to label it.
- **Outside market hours** the snapshot keeps returning the last values, so prices simply stop moving. Polling still works, and the SSE stream stays healthy because it re-sends cached prices every tick (see `MARKET_INTERFACE.md` §6).
- **3:30–4:00 AM ET reset**: snapshot fields can be missing. The fallback chain in §2.1 ends at `prevDay.c`, and if even that is missing the ticker is skipped for that poll, keeping its last cached price.
- **Dotted tickers** (`BRK.B`) are written with a dot in Massive's stock endpoints. Pass them as-is.
- **Free tier does not mean the snapshot runs every 15 s.** PLAN.md §6 implies the free tier can poll the snapshot every 15 seconds. It can't: snapshots aren't in Basic at all. In free mode the backend refreshes end-of-day data every 30 minutes instead (`MARKET_INTERFACE.md` §5).
- **WebSockets** (`wss://socket.massive.com/stocks`) exist on paid plans for push updates. They're out of scope: PLAN.md chose REST polling for simplicity.

---

## 7. Sources

- Docs index: <https://massive.com/llms.txt>
- REST quickstart (base URL, auth): <https://massive.com/docs/rest/quickstart>
- Full Market Snapshot: <https://massive.com/docs/rest/stocks/snapshots/full-market-snapshot>
- Single Ticker Snapshot: <https://massive.com/docs/rest/stocks/snapshots/single-ticker-snapshot>
- Unified Snapshot: <https://massive.com/docs/rest/stocks/snapshots/unified-snapshot>
- Daily Market Summary: <https://massive.com/docs/rest/stocks/aggregates/daily-market-summary>
- Previous Day Bar: <https://massive.com/docs/rest/stocks/aggregates/previous-day-bar>
- Daily Ticker Summary: <https://massive.com/docs/rest/stocks/aggregates/daily-ticker-summary>
- Custom Bars: <https://massive.com/docs/rest/stocks/aggregates/custom-bars>
- Last Trade: <https://massive.com/docs/rest/stocks/trades-quotes/last-trade>
- Market Status: <https://massive.com/docs/rest/stocks/market-operations/market-status>
- Ticker Overview: <https://massive.com/docs/rest/stocks/tickers/ticker-overview>
- Pricing: <https://massive.com/pricing>
- Python client: <https://github.com/massive-com/client-python> (`massive/rest/snapshot.py`, `aggs.py`, `base.py`, `models/`)
