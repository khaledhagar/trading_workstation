# trading_workstation — AI Trading Workstation

## What This Is

A visually stunning, Bloomberg-style AI trading workstation that streams live (simulated or real) market prices, lets a single user trade a simulated $10,000 portfolio with instant market orders, and includes an LLM chat copilot that analyzes the portfolio and executes trades and watchlist changes through natural language. It ships as one Docker container on port 8000 (FastAPI + static Next.js export + SQLite), with no login. It is the capstone project of an agentic AI coding course, built entirely by coding agents to demonstrate that orchestrated agents can produce a production-quality full-stack app.

## Core Value

Open `http://localhost:8000` with one command and immediately see live-streaming prices you can trade, by hand or by asking the AI, with the portfolio updating in real time.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Live price streaming over SSE (simulator by default, Massive API optional) with flash animations and sparklines
- [ ] Watchlist management (add/remove, manual or via AI), default 10 tickers
- [ ] Simulated portfolio: market-order buy/sell, instant fill, fractional shares, $10k starting cash
- [ ] Portfolio visualizations: heatmap (treemap), P&L chart from snapshots, positions table
- [ ] AI chat assistant (LiteLLM → OpenRouter → Cerebras `gpt-oss-120b`, structured outputs) that auto-executes trades and watchlist changes, with a deterministic mock mode
- [ ] SQLite persistence with automatic init/seed at startup
- [ ] Dark, data-dense terminal UI with connection status, live header totals, empty/loading states
- [ ] Single-container Docker deployment with start/stop scripts (macOS/Linux + Windows)
- [ ] Unit tests (pytest, Vitest) and Playwright E2E tests in a docker-compose test harness

The authoritative, detailed spec for every item above is `planning/PLAN.md` (§2–§12), with the market-data implementation design in `planning/MARKET_DATA_DESIGN.md`. Those documents are the contract; REQUIREMENTS.md breaks them into testable items.

### Out of Scope

- Authentication / multi-user — single hardcoded `"default"` user; schema keeps `user_id` for the future only
- Limit/stop orders, order book, partial fills, fees — market orders only, by design (PLAN.md §3)
- Realized P&L tracking — not required by spec
- Server-side price history — charts are built on the frontend from SSE since page load (PLAN.md §6)
- WebSockets — SSE is sufficient for one-way push
- Token-by-token LLM streaming — complete JSON response plus a loading indicator
- Trade confirmation dialogs — auto-execution is a deliberate demo choice
- Cloud deployment (Terraform / App Runner) — optional stretch goal, not core
- Root `docker-compose.yml` for production — the start/stop scripts cover running the app

## Context

- **Course capstone:** the build itself is the demo. Agents coordinate through files in `planning/`, which hold the shared contract between frontend and backend work.
- **Spec maturity:** `PLAN.md` went through a thorough review (§13, all items resolved), and it pins API contracts, the SSE event format, error codes, trading rules, the DB schema, LLM behavior and mock rules, frontend states and the Docker layout. `MARKET_DATA_DESIGN.md` contains near-complete code for the market data layer (cache, simulator, Massive client, SSE stream, lifespan wiring) and wins over the other market docs on any conflict.
- **Supporting docs:** `MARKET_INTERFACE.md`, `MARKET_SIMULATOR.md`, `MASSIVE_API.md`.
- **LLM integration:** must use the repo's `cerebras-inference` skill (`.claude/skills/cerebras/SKILL.md`), with LiteLLM `acompletion` inside async routes.
- **Repo state:** greenfield. `frontend/` exists but is empty, and there is no backend yet. `README.md` already documents the intended quick start and tests, and `planning/REVIEW.md` flags that those referenced artifacts don't exist yet (`.env.example`, `scripts/`, `Dockerfile`, `test/docker-compose.test.yml`), so the build must create all of them.
- **Dev environment:** Windows 11, project inside a OneDrive-synced folder (one reason the Docker DB uses a named volume rather than a bind mount).

## Constraints

- **Tech stack**: FastAPI (Python 3.12, `uv`), Next.js + TypeScript static export with Tailwind, SQLite, SSE — fixed by PLAN.md §3
- **Charts**: TradingView Lightweight Charts (main and P&L charts, attribution kept), hand-rolled SVG sparklines, Recharts `Treemap` for the heatmap — PLAN.md §10
- **LLM**: LiteLLM → OpenRouter, model `openrouter/openai/gpt-oss-120b` with Cerebras as provider, structured outputs validated by Pydantic `model_validate_json` — PLAN.md §9
- **Deployment**: one container, one port (8000), multi-stage Dockerfile (Node 20 → Python 3.12), named volume `trading-workstation-data` at `/app/db` — PLAN.md §11
- **Config**: env vars `OPENROUTER_API_KEY`, `MASSIVE_API_KEY`, `MASSIVE_MODE`, `MASSIVE_POLL_INTERVAL`, `LLM_MOCK`, `DB_PATH`; `.env` loaded from the project root locally, `--env-file` in Docker. The app must start without an OpenRouter key (chat degrades gracefully)
- **Visual**: dark theme (`#0d1117`/`#1a1a2e`), accent yellow `#ecad0a`, blue `#209dd7`, purple `#753991` for submit buttons; desktop-first
- **Testing**: E2E runs with `LLM_MOCK=true` in a Playwright container version-matched to `@playwright/test`
- **Secrets**: `.env` is gitignored and must never be read into agent context or committed; commit `.env.example` instead

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Build the full PLAN.md scope as v1 | User request: "build the entire project as described in planning/plan.md" | — Pending |
| Vertical MVP phase structure | Get a working end-to-end slice (live prices on screen) early, then add trading, visualizations, chat, packaging | — Pending |
| Skip project-level research | PLAN.md + MARKET_DATA_DESIGN.md already fix the stack, contracts and pitfalls; per-phase research still runs | — Pending |
| Fully automatic pipeline (YOLO) | User wants the whole project built without per-step approvals | — Pending |
| MARKET_DATA_DESIGN.md wins over other market docs | Stated in that document; it contains the implementation code | — Pending |
| SSE over WebSockets, static Next.js export, SQLite, single container | PLAN.md §3 rationale table | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-11-03 after initialization*
