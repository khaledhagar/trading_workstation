# Code Review: Market Data Backend

**Scope:** commit `f863fc8` on `feature/market-data-backend`: `backend/app/market/**` and `backend/tests/market/**`
**Reviewed against:** `PLAN.md` (§5, §6, §8), `MARKET_DATA_DESIGN.md` (which wins where docs disagree), `MARKET_INTERFACE.md`, `MARKET_SIMULATOR.md`, `MASSIVE_API.md`
**Date:** 2026-10-27

> This file replaces an earlier review of the README/plugin commit (`c675ede..d09f51b`). That review is still in git history.

---

## 1. Verdict

> **Update (2026-10-27): all findings are resolved.** See §7 for what changed. The suite is now **241 passed**, coverage 99%. The market data package is ready for the app integration step (lifespan, routes, error handlers), which is the next build step and not part of this commit.

**Original verdict: approve, with one fix recommended before the trade code is built on it.**

The implementation follows `MARKET_DATA_DESIGN.md` closely, the code is clean and well commented, and the test suite is thorough and stable. I found no defect in the normal paths (simulator, Massive snapshot mode, Massive end-of-day mode). There is one medium-severity edge case: a price below half a cent is stored as `0.00`, which the trade code would fill at (§3.1). The rest are low-severity edge cases and notes.

---

## 2. Test Results

Command: `cd backend && uv run pytest`

| Run | Result |
|---|---|
| Full suite | **216 passed** in ~6 s, 0 failures, 0 warnings |
| 5 back-to-back reruns (timing-sensitive tests included) | 216 passed every time (3.8 to 6.8 s). No flakes |
| Coverage (`uv run --with pytest-cov pytest --cov=app`) | **99%** (584 statements, 2 missed) |

The 2 uncovered lines are `massive/source.py:140` (re-raising `CancelledError` inside the poll) and `:148` (the log line for an unexpected non-Massive exception). Both are defensive and fine to leave.

Slowest tests are the statistical engine tests (~0.5 s each). Nothing makes a real network call.

Environment: Windows 11, Python 3.12.13, uv.

---

## 3. Findings

Edge cases were confirmed by running a probe script against the code, not only by reading it.

### 3.1 [Medium] A price below $0.005 is stored as `0.00`

`cache.py:34-40` checks `price > 0` and **then** rounds to 2 decimals. A price such as `0.004` passes the check and is stored as `price = 0.0`.

```
>>> PriceCache().update("ABCW", 0.004).price
0.0
```

**How it can happen:** in end-of-day mode the backend loads the whole US market. Warrants and rights (letters-only symbols such as `ABCDW`, which pass the ticker regex) sometimes close below half a cent. A user, or the LLM, can add one.

**Why it matters:** PLAN.md §8 fills trades at the cached price. A buy at `$0.00` costs nothing, so the cash check always passes and the user can buy any quantity for free. It also breaks the guarantee that the cache never holds a non-positive price.

**Fix:** check the price **after** rounding (reject, or clamp to `0.01`), and add a test. A one-line change in `PriceCache.update`.

### 3.2 [Low] A real ticker is reported as "Unknown" during Massive's daily reset

`massive/source.py:115-118`: in snapshot mode, if a ticker comes back with every price field zero (Massive clears snapshots between 3:30 and 4:00 AM ET, see MASSIVE_API.md §6), `add_ticker` raises `UnknownTickerError`, so the user sees 400 `"Unknown ticker: MSFT"` for a valid symbol.

Confirmed: an all-zeros `MSFT` snapshot gives `UnknownTickerError: Unknown ticker: MSFT`.

**Suggestion:** distinguish "absent from the response" (unknown → 400) from "present but no usable price" (→ `MarketDataUnavailableError` → 503 "try again shortly"). This is a narrow window, so it can wait.

### 3.3 [Low] Calling `SimulatorSource.start()` a second time resets reference prices

`simulator/source.py:33-35` → `_seed()` calls `cache.update(ticker, seed, reference_price=seed)`, and `engine.add()` returns the **current** price for a ticker it already tracks. A second `start()` therefore resets `change_percent` to 0 and sets an unrounded reference (`250.0` → `249.993383…` in the probe). This breaks contract C7.

The lifespan calls `start()` exactly once, so this can't happen today. A guard (`if ticker not in self.engine.tickers()`) would make the contract hold unconditionally.

### 3.4 [Low] `MassiveSource.add_ticker()` before `start()` raises `RuntimeError`

`self.client` raises `RuntimeError`, which the API would turn into a 500 instead of a contract exception. Not reachable with the planned lifespan order (`start()` runs before any request is served). Mentioned only for completeness.

### 3.5 [Low] End-of-day mode reports `up`/`down` for one refresh after a new trading day

PLAN.md §6 says every SSE event in EOD mode reports `direction: "flat"`. When a 30-minute refresh picks up a new trading day, `previous_price` is the old day's close, so `direction` is `up` or `down` until the next refresh rewrites the same price. This is arguably more correct (it really did move), and the frontend flashes on price changes rather than on `direction`. **Suggestion:** reword PLAN.md §6 slightly rather than change the code.

### 3.6 [Note] The free-tier spacing has no safety margin

`free_tier_spacing = 12.0` gives exactly 5 calls per 60 s. If Massive counts a rolling window and network latency shifts the server-side arrival times, a 6th call can land inside the window and return 429. The 429 path backs off correctly (tested), so the effect is a 60 s delay, not a failure. Using 12.5 to 13 s would remove the risk at almost no cost.

### 3.7 [Note] SSE cadence drifts slightly against the simulator

`stream.py` sleeps a flat 0.5 s after each yield, so its period is slightly longer than the simulator's fixed 500 ms cadence. Occasionally one simulator tick is never sent, and occasionally the same tick is sent twice. The frontend already de-duplicates on `timestamp` (PLAN.md §10), and one dropped tick out of hundreds is invisible on a chart, so no change is needed.

### 3.8 [Note] `MASSIVE_POLL_INTERVAL` below 2 is clamped, not reset to the default

PLAN.md §5 says invalid values are "replaced by the defaults". The factory replaces non-numeric/NaN/inf values with 15 but **clamps** values below the minimum to 2 (and logs a warning). That matches `MARKET_DATA_DESIGN.md` §7 and its test, and it's the more useful behaviour. Only the PLAN.md wording is loose.

---

## 4. Spec Compliance

| Requirement | Status | Where |
|---|---|---|
| One abstract interface, two implementations, env-driven choice (PLAN §6, §5) | ✅ | `base.py`, `factory.py` |
| Ticker rules: trim, uppercase, `^[A-Z][A-Z.]{0,9}$`, 400 `"Invalid ticker"` | ✅ | `tickers.py`, `errors.py` |
| Simulator: GBM, ~500 ms, sector correlation, 2–5% events, realistic seeds | ✅ Verified statistically by tests (σ, correlation 0.6 / 0.3 / 0, event size and rate) | `simulator/` |
| Unknown tickers: random $50–$300 seed, default σ, uncorrelated | ✅ | `engine.py:68-80` |
| Reference price = seed (simulator) / `prevDay.c` (snapshot) / previous close (EOD) | ✅ | `source.py` files |
| Massive snapshot mode: one call per poll, price fallback chain | ✅ | `client.py`, `parse.py` |
| Massive EOD mode: auto-detected from a 403, two trading days, ≥ 12 s spacing, 30 min refresh | ✅ | `massive/source.py` |
| Never send an empty `tickers=` filter (D6) | ✅ Tested | `client.py:64` |
| Add seeds the cache before returning (C2) | ✅ Contract-tested on both sources | |
| 503 for provider unavailable / still loading, 20 s cap (D2, D8) | ✅ Via the `MassiveError → MarketDataUnavailableError` subclassing | |
| SSE format: unnamed event, JSON keyed by ticker, millisecond `Z` timestamps, `change_percent` rounded to 2 | ✅ | `stream.py`, `models.py` |
| API key only in the `Authorization` header, never in URLs or logs | ✅ Tested | `client.py:52` |
| No retries in the client; status-code-based error mapping | ✅ | `client.py:93-116` |
| Sources never touch the DB (C8) | ✅ No DB imports in `app/market/` | |

**Not in this commit (expected, by the design's build order):** `app/main.py` lifespan, `db.py`, the API routers, the error handlers from §9.3, and the trade/watchlist wiring from §9.4 to §9.7. The market package exposes everything those pieces need.

---

## 5. Code Quality

Strengths:

- **Clear separation.** The pure engine and parsers have no asyncio or I/O, so the math and parsing are tested synchronously and deterministically. Source classes are thin adapters.
- **Concurrency reasoning is sound.** Everything runs on one event loop. Each source writes the cache without awaiting in between, and `_apply_snapshots` re-checks membership after the HTTP await, so a ticker removed mid-poll is never written back (C4, tested).
- **Defensive parsing.** `_positive()` rejects bools, strings, NaN, inf and zero. Non-dict or non-list JSON shapes are handled. `ns_to_datetime` guards against overflow.
- **Hardening beyond the design doc.** The engine validates its weights, event range and event rate. The factory rejects NaN/inf. `change_percent` normalises `-0.0`. `sync_tickers` adds in sorted order for deterministic logs.
- **Tests.** A shared contract suite runs against both sources. A fake Massive transport covers 401/403/429/5xx, invalid JSON, holiday walks, forbidden dates and mode detection. Statistical tests use fixed seeds and sensible tolerances, and repeated runs show no flakiness.

Minor style points (no action needed):

- The test helpers live in `tests/market/fakes.py` rather than `conftest.py` as §12 of the design suggests. It's an explicit import, which is arguably clearer.
- `pytest-cov` isn't a dev dependency, so the coverage figure in the commit message can't be reproduced with `uv run pytest` alone. Consider adding it to `[dependency-groups].dev`.

---

## 6. Recommended Actions

| Priority | Action |
|---|---|
| **Before trade execution is built** | Fix §3.1: validate the price after rounding in `PriceCache.update`, and add a test |
| Soon | §3.2: return 503 rather than "Unknown ticker" when Massive has the ticker but no usable price |
| Optional | §3.3 guard in `SimulatorSource.start`; §3.6 spacing margin of 12.5 to 13 s; add `pytest-cov` to the dev dependencies |
| Docs | PLAN.md §6: EOD `direction` is `flat` except right after a new trading day (§3.5). PLAN.md §5: values below the minimum poll interval are clamped (§3.8) |

---

## 7. Resolution (2026-10-27)

Every finding above was addressed in a follow-up commit on `feature/market-data-backend`. `MARKET_DATA_DESIGN.md` records the decisions as **D9–D12**, and `PLAN.md` §5/§6 are updated to match.

| Finding | Resolution | Tests added or changed |
|---|---|---|
| §3.1 Sub-cent price stored as `0.00` | `PriceCache.update` now requires the price to be ≥ $0.01 **after** rounding (new `is_priceable()` / `MIN_PRICE`). The Massive parsers skip sub-cent values, so such a ticker is rejected as unknown (snapshot and EOD). The simulator engine floors prices at $0.01 so a tick can never fail | `test_cache_never_stores_a_zero_price`, `test_is_priceable`, sub-cent cases in `test_cache_rejects_bad_price`, `test_sub_cent_values_are_skipped_in_the_fallback_chain`, `test_parse_grouped_skips_sub_cent_closes`, `test_snapshot_add_of_sub_cent_ticker_is_unknown`, `test_sub_cent_poll_keeps_last_price`, `test_eod_sub_cent_ticker_is_unknown`, `test_price_is_floored_at_one_cent` |
| §3.2 Real ticker "Unknown" during the daily reset | New `has_price_data()`. A ticker absent from the response is still `UnknownTickerError` (400); one that is present with every price field zero raises `MarketDataUnavailableError` (503 "try again shortly") | `test_snapshot_add_during_daily_reset_is_unavailable` (replaces `test_snapshot_add_with_no_usable_price_is_unknown`), `test_has_price_data` |
| §3.3 Second `start()` resets references | `SimulatorSource.start()` seeds only tickers it doesn't already track | `test_second_start_keeps_reference_and_price` |
| §3.4 `RuntimeError` before `start()` | `MassiveSource.client` raises `MarketDataUnavailableError` before `start()` or after `stop()`, so an early add maps to 503, not 500 | `test_client_before_start_raises_unavailable`, `test_add_before_start_is_unavailable_not_a_crash`, `test_stop_closes_http_client` |
| §3.5 EOD `direction` after a new day | Docs only: PLAN.md §6 and the design doc now describe the one-refresh up/down after a new trading day | — |
| §3.6 No spacing margin on the free tier | `free_tier_spacing` default 12.0 → **12.5 s** | `test_free_tier_spacing_applies_until_snapshot_detected` |
| §3.7 SSE cadence drift | **No change, by design.** A real-time smoke run confirmed it is cosmetic: an occasional simulator tick is never streamed, and every event still carries a fresh timestamp and correct fields | — |
| §3.8 Poll-interval clamp wording | Docs only: PLAN.md §5 now says values below the minimum are raised to 2 | — |
| §5 `pytest-cov` missing | Added to `[dependency-groups].dev`. `uv run pytest --cov=app` now works out of the box | — |

### Verification after the fixes

| Check | Result |
|---|---|
| `uv run pytest` | **241 passed** (216 before; 25 new or updated tests), 0 failures |
| `uv run pytest --cov=app` | **99%** (604 statements, 2 missed, the same two defensive lines as before) |
| Edge-case probe re-run | `0.004` → rejected; a second `start()` keeps reference `250.0`; an all-zeros snapshot → `MarketDataUnavailableError`; an add before `start()` → `MarketDataUnavailableError` |
| Real-time smoke run (factory → simulator → `price_events`, production 500 ms interval, 11 tickers) | `retry: 2000` first, then well-formed events with all 11 tickers and the exact contract fields, prices moving, clean stop |

### Still to build (next step, outside the market data package)

`app/main.py` lifespan, `db.py` (`tracked_tickers`, `resync_market`), the `/api/stream/prices` route, the error handlers in design §9.3, and the watchlist/trade wiring in §9.4–§9.7.
