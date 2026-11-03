# Roadmap: trading_workstation

## Overview

The build runs as six vertical slices, and each one leaves a working app at `http://localhost:8000`. Phase 1 is a walking skeleton: a self-initializing FastAPI + SQLite backend whose GBM simulator streams prices over SSE into a dark Next.js watchlist with price flashes, sparklines and a connection dot. Phase 2 makes the watchlist editable, adds the main price chart and adds the optional Massive data source. Phase 3 adds trading, so cash, positions and live total value update in real time. Phase 4 adds the AI copilot, which trades and edits the watchlist from natural language. Phase 5 completes the terminal with the P&L heatmap, the portfolio-value chart, every empty/loading state and the final dense layout. Phase 6 packages everything into one Docker container with start/stop scripts and confirms it with the full unit and Playwright E2E suites.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Live Market Stream** - Self-initializing backend + simulator + SSE feeding a live, flashing watchlist at localhost:8000
- [ ] **Phase 2: Watchlist Control & Market Data Sources** - Add/remove tickers, click-to-chart main price chart, optional Massive real data
- [ ] **Phase 3: Trading & Live Portfolio** - Trade bar with instant market orders, positions table, live header totals, snapshots
- [ ] **Phase 4: AI Trading Copilot** - Chat panel whose LLM analyzes the portfolio and auto-executes trades and watchlist changes
- [ ] **Phase 5: Portfolio Visualizations & Terminal Polish** - P&L heatmap, portfolio-value chart, all empty/loading states, final dense layout
- [ ] **Phase 6: Docker Ship & End-to-End Verification** - One-container deployment, start/stop scripts, full unit + Playwright E2E suites

## Phase Details

### Phase 1: Live Market Stream
**Goal**: Users who start the backend locally and open `http://localhost:8000` see the 10 default tickers streaming live simulated prices in a dark terminal watchlist, backed by a database that initializes itself
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: FND-01, FND-02, FND-03, FND-04, FND-05, FND-06, FND-07, MKT-01, MKT-03, MKT-07, WATCH-01, WATCH-04, UI-01, UI-02, UI-03
**Success Criteria** (what must be TRUE):
  1. After building the frontend static export and running `uv run uvicorn` in `backend/`, opening `http://localhost:8000` shows a dark-themed watchlist of AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX. Prices change about every 500ms, each change flashes green (up) or red (down) and fades over ~500ms, and each row shows daily change % and an inline-SVG sparkline that fills in from page load
  2. The header connection dot is green while events arrive, turns yellow within ~5s of stopping the backend, and goes green again by itself when the backend restarts, with no page reload
  3. On first start `db/trading_workstation.db` is created and seeded ($10,000 cash for user `default`, 10 watchlist tickers). Restarting keeps existing data without re-seeding, deleting the file gives a clean reset, and git never tracks the DB file
  4. `GET /api/health` returns `{"status": "ok"}`. `GET /api/watchlist` returns the 10 tickers with price fields and millisecond `Z` timestamps. `GET /api/stream/prices` emits one unnamed event per tick, a JSON object keyed by ticker in the PLAN.md §6 format. With no frontend build present, the API still runs and logs a notice
  5. Backend pytest tests for the price cache, GBM simulator and SSE event format pass, as do frontend Vitest tests for the price flash and the SSE hook (capped per-ticker buffers, 5s staleness status)
**Plans**: TBD
**UI hint**: yes

### Phase 2: Watchlist Control & Market Data Sources
**Goal**: Users can curate their watchlist from the panel, click any ticker to see a large live price chart, and optionally run on real Massive market data instead of the simulator
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: MKT-02, MKT-04, MKT-05, MKT-06, WATCH-02, WATCH-03, WATCH-05, UI-05
**Success Criteria** (what must be TRUE):
  1. User types a ticker such as ` pypl` into the watchlist panel and it appears as `PYPL`, already priced and streaming. Adding an already-watched ticker changes nothing, and input like `123` shows the backend's `"Invalid ticker"` message inline
  2. User removes a ticker from the panel, and an unheld ticker leaves both the watchlist and the SSE stream. Removing an unwatched ticker through the API returns 404
  3. Clicking a watchlist ticker shows a large live Lightweight Charts price chart for it, with attribution visible. The first watchlist ticker is auto-selected on load, and the chart reads "Waiting for price data…" until it has 2 points
  4. With `MASSIVE_API_KEY` set, the stream carries Massive prices: snapshot mode on paid keys, eod mode on free keys, auto-detected or forced with `MASSIVE_MODE`. Adding a ticker Massive doesn't know returns 400 `"Unknown ticker: XYZ"`, and a provider outage returns 503 `"Market data unavailable, try again shortly"` while the stream keeps the last known prices
  5. The simulator and Massive sources pass the same interface-conformance test suite, and unit tests with fake responses cover Massive parsing and mode detection, so no live key is needed
**Plans**: TBD
**UI hint**: yes

### Phase 3: Trading & Live Portfolio
**Goal**: Users can buy and sell shares instantly from a trade bar and watch cash, positions and total portfolio value update in real time
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: TRADE-01, TRADE-02, TRADE-03, TRADE-04, TRADE-05, TRADE-06, TRADE-07, PORT-01, PORT-02, PORT-04, UI-04
**Success Criteria** (what must be TRUE):
  1. User enters a ticker and quantity in the trade bar and clicks Buy. The order fills instantly at the current price with no confirmation, header cash drops by quantity × price, and a positions-table row shows ticker, quantity, avg cost, current price, unrealized P&L and % change
  2. The header's total portfolio value moves with every price tick (cash + Σ quantity × latest SSE price, falling back to `current_price`) without extra requests
  3. Selling part of a position lowers its quantity and leaves avg cost unchanged, and selling the rest removes the row. Overselling, overbuying and invalid quantities (≤ 0, or more than 4 decimals) show the backend's exact messages inline, e.g. `"Insufficient shares: have X, tried to sell Y"` and `"Insufficient cash: need $X, have $Y"`
  4. Buying an unwatched ticker adds it to the watchlist panel automatically. Removing a held ticker from the watchlist keeps it streaming and valued in the portfolio, and positions and cash survive a backend restart
  5. Every trade is one atomic transaction that also records a portfolio snapshot; snapshots are also recorded at startup and every 30s. Pytest covers weighted avg cost, full-exit deletion, rounding, insufficient cash and shares, and concurrent trades that cannot both pass validation, and Vitest covers the live total-value calculation
**Plans**: TBD
**UI hint**: yes

### Phase 4: AI Trading Copilot
**Goal**: Users can chat with the trading_workstation assistant, which analyzes their live portfolio and executes trades and watchlist changes from natural language, with every outcome shown inline
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: CHAT-01, CHAT-02, CHAT-03, CHAT-04, CHAT-05, CHAT-06, CHAT-07, CHAT-08, CHAT-09, CHAT-10
**Success Criteria** (what must be TRUE):
  1. User opens the docked, collapsible chat panel and sees a welcome message with example prompts when there is no history. After sending a message, a typing indicator shows and input stays disabled until the assistant's reply appears
  2. Asking "Buy 10 AAPL" or "add PYPL" executes the action under the same rules as manual trades. Executed and failed actions (e.g. insufficient cash) render inline in distinct styles, and the header, positions table and watchlist refresh on their own
  3. Reloading the page restores the conversation (last 50 messages). On the next turn the assistant knows the outcomes of earlier actions and the current portfolio
  4. With `LLM_MOCK=true`, the deterministic buy/sell/add/remove/fail/default rules produce the specified replies through the real execution and persistence path. `fail`, like any real LLM error, 30s timeout or invalid response, returns `"Sorry, I couldn't process that request. Please try again."` with no actions
  5. Without `OPENROUTER_API_KEY`, the app starts with a warning, and chat replies `"The AI assistant isn't configured. Set OPENROUTER_API_KEY in .env and restart."` without calling the LLM. With a key, replies come from `openrouter/openai/gpt-oss-120b` on Cerebras via structured output, and pytest plus Vitest cover response parsing, failure handling, mock rules and inline action rendering
**Plans**: TBD
**UI hint**: yes

### Phase 5: Portfolio Visualizations & Terminal Polish
**Goal**: Users can read their portfolio at a glance from a P&L-colored heatmap and a portfolio-value chart, in a dense terminal layout where every panel handles its empty and loading states
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: PORT-03, PORT-05, PORT-06, UI-06, UI-07
**Success Criteria** (what must be TRUE):
  1. The heatmap draws one rectangle per position, sized by market value and colored by P&L %: red at ≤ −5%, gray at 0%, green at ≥ +5%. Each tile is labeled with ticker and P&L %, with ticker only on small tiles
  2. The P&L chart plots total portfolio value over time from `GET /api/portfolio/history` (the 1,000 most recent snapshots at most, oldest first) and gains points after trades and every 30s
  3. Each specified empty or loading state appears: the empty-watchlist message, `—` for unpriced tickers, "Select a ticker", "Waiting for price data…", the no-positions message in both heatmap and positions table, and "Collecting portfolio history…"
  4. On a wide desktop screen every panel is visible at once in a dense terminal layout: header, watchlist, main chart, heatmap, P&L chart, positions table, trade bar and chat. The app stays usable at tablet width
  5. Vitest tests for the heatmap color scale, including clamping at ±5%, pass
**Plans**: TBD
**UI hint**: yes

### Phase 6: Docker Ship & End-to-End Verification
**Goal**: Users can launch the whole workstation with one command as a single container with persistent data, and the full unit and E2E test suites prove it works
**Mode:** mvp
**Depends on**: Phase 5
**Requirements**: DEPLOY-01, DEPLOY-02, DEPLOY-03, DEPLOY-04, TEST-01, TEST-02, TEST-03, TEST-04
**Success Criteria** (what must be TRUE):
  1. Running `./scripts/start_mac.sh` or `.\scripts\start_windows.ps1` builds the image if needed (or when given `--build`), starts the container and prints `http://localhost:8000`, where one container on one port serves the full app. Rerunning any start or stop script is safe
  2. Trades, watchlist and chat history survive stop + start and image rebuilds through the `trading-workstation-data` named volume, and the stop scripts never remove the volume
  3. `docker compose -f test/docker-compose.test.yml up --build` runs the app with `LLM_MOCK=true` plus a version-matched Playwright container, and every E2E scenario passes: fresh start, add/remove ticker, buy, sell, portfolio visualizations, mocked AI chat trade, SSE reconnection
  4. `cd backend && uv run pytest` and `cd frontend && npm test` pass and together cover every area PLAN.md §12 lists: market data, trading, LLM, API routes, price flash, SSE hook, portfolio calc, heatmap colors and chat actions
  5. The README quick start and test commands work exactly as written. `.env.example` is committed, `.env` and the DB file are gitignored, and `db/.gitkeep` exists
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Live Market Stream | 0/TBD | Not started | - |
| 2. Watchlist Control & Market Data Sources | 0/TBD | Not started | - |
| 3. Trading & Live Portfolio | 0/TBD | Not started | - |
| 4. AI Trading Copilot | 0/TBD | Not started | - |
| 5. Portfolio Visualizations & Terminal Polish | 0/TBD | Not started | - |
| 6. Docker Ship & End-to-End Verification | 0/TBD | Not started | - |
