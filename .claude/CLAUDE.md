## Project

**trading_workstation — AI Trading Workstation**

A visually stunning, Bloomberg-style AI trading workstation that streams live (simulated or real) market prices, lets a single user trade a simulated $10,000 portfolio with instant market orders, and includes an LLM chat copilot that analyzes the portfolio and executes trades and watchlist changes through natural language. It ships as one Docker container on port 8000 (FastAPI + static Next.js export + SQLite), with no login. It is the capstone project of an agentic AI coding course, built entirely by coding agents to demonstrate that orchestrated agents can produce a production-quality full-stack app.

**Core Value:** Open `http://localhost:8000` with one command and immediately see live-streaming prices you can trade, by hand or by asking the AI, with the portfolio updating in real time.

### Constraints

- **Tech stack**: FastAPI (Python 3.12, `uv`), Next.js + TypeScript static export with Tailwind, SQLite, SSE — fixed by PLAN.md §3
- **Charts**: TradingView Lightweight Charts (main and P&L charts, attribution kept), hand-rolled SVG sparklines, Recharts `Treemap` for the heatmap — PLAN.md §10
- **LLM**: LiteLLM → OpenRouter, model `openrouter/openai/gpt-oss-120b` with Cerebras as provider, structured outputs validated by Pydantic `model_validate_json` — PLAN.md §9
- **Deployment**: one container, one port (8000), multi-stage Dockerfile (Node 20 → Python 3.12), named volume `trading-workstation-data` at `/app/db` — PLAN.md §11
- **Config**: env vars `OPENROUTER_API_KEY`, `MASSIVE_API_KEY`, `MASSIVE_MODE`, `MASSIVE_POLL_INTERVAL`, `LLM_MOCK`, `DB_PATH`; `.env` loaded from the project root locally, `--env-file` in Docker. The app must start without an OpenRouter key (chat degrades gracefully)
- **Visual**: dark theme (`#0d1117`/`#1a1a2e`), accent yellow `#ecad0a`, blue `#209dd7`, purple `#753991` for submit buttons; desktop-first
- **Testing**: E2E runs with `LLM_MOCK=true` in a Playwright container version-matched to `@playwright/test`
- **Secrets**: `.env` is gitignored and must never be read into agent context or committed; commit `.env.example` instead

## Code Layout

- `backend/app/main.py` — FastAPI app, lifespan (DB → market data → snapshot task), error mapping, static mount
- `backend/app/market/` — `MarketDataSource` interface, simulator (GBM), Massive client, `PriceCache`, SSE generator
- `backend/app/db.py` — schema, seed data, connection helper; `backend/app/portfolio.py` — trades, valuation, snapshots, watchlist
- `backend/app/chat.py` — LLM prompt/context, structured output, mock mode, action execution
- `frontend/src/` — Next.js app (`app/page.tsx`), components, hooks (`usePriceStream`, `usePriceFlash`), pure logic in `lib/`
- `test/` — Playwright E2E suite and `docker-compose.test.yml`

## Testing

- Backend: `cd backend && uv run pytest`
- Frontend: `cd frontend && npm test` and `npm run lint` (type-check)
- E2E: `docker compose -f test/docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from e2e`

## Project Skills

| Skill | Description | Path |
|-------|-------------|------|
| cerebras-inference | Use this to write code to call an LLM using LiteLLM and OpenRouter with the Cerebras inference provider | `.claude/skills/cerebras/SKILL.md` |
