# trading_workstation — AI Trading Workstation

An AI-powered trading terminal: live streaming prices, a simulated $10k portfolio, and a chat assistant that can analyze your positions and place trades for you. Built entirely by coding agents as the capstone of an agentic AI coding course.

## Features

- Live prices over SSE with green/red flash animations and sparklines
- Market orders with instant fills, fractional shares and no fees
- Portfolio heatmap, P&L chart and positions table
- AI chat (LiteLLM → OpenRouter, Cerebras) that executes trades and edits the watchlist
- Built-in market simulator, or real data via the Massive (Polygon.io) API

## Quick Start

```bash
cp .env.example .env          # then set OPENROUTER_API_KEY
./scripts/start_mac.sh        # Windows: .\scripts\start_windows.ps1
```

Open http://localhost:8000. Stop with `./scripts/stop_mac.sh` (or `stop_windows.ps1`); your data is kept.

Or run Docker directly:

```bash
docker build -t trading-workstation .
docker run -v trading-workstation-data:/app/db -p 8000:8000 --env-file .env trading-workstation
```

To reset all data: `docker volume rm trading-workstation-data` (with the container stopped).

## Configuration

| Variable | Required | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | For chat | LLM access. Without it, everything except chat works |
| `MASSIVE_API_KEY` | No | Real market data. Empty → built-in simulator |
| `LLM_MOCK` | No | `true` for deterministic mock chat replies (tests) |
| `DB_PATH` | No | SQLite file. Default `db/trading_workstation.db` locally, `/app/db/trading_workstation.db` in Docker |

## Stack

Single container on port 8000: **FastAPI** (Python, uv) serves the REST API, SSE stream and the **Next.js** static export (TypeScript, Tailwind). Data lives in **SQLite**, created and seeded automatically at startup.

## Project Layout

```
backend/    FastAPI app, market data, LLM, database
frontend/   Next.js UI
planning/   Specs and agent contracts (start with PLAN.md)
scripts/    Start/stop helpers
test/       Playwright E2E tests
```

## Testing

- Backend: `cd backend && uv run pytest`
- Frontend: `cd frontend && npm test`
- E2E: `docker compose -f test/docker-compose.test.yml up --build`

## License

See [LICENSE](LICENSE).
