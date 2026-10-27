# trading_workstation backend

FastAPI backend, managed with [uv](https://docs.astral.sh/uv/). The full spec is in `../planning/PLAN.md`.

**Status:** the market data package (`app/market/`) is complete and tested. The FastAPI app (`app/main.py`), database and API routes are the next build step.

## Market data demo

A live terminal dashboard that streams prices through the same SSE generator the frontend will use:

```bash
cd backend
uv run python demo.py                    # the 10 default tickers
uv run python demo.py --fast             # simulator at 60x speed: livelier moves
uv run python demo.py PYPL brk.b ZZZ     # your own tickers (unknown ones get a random seed)
uv run python demo.py --duration 10      # stop by itself after 10 seconds
```

Press `Ctrl+C` to quit. It uses the simulator unless `MASSIVE_API_KEY` is set in the project's `.env`, in which case it shows real Massive prices (on the free plan, end-of-day prices take ~25 s to load).

Prices flash green or red when they change, the trend column is a sparkline of the prices seen since the demo started, and change % is measured from the seed price (simulator) or the previous close (Massive).

## Tests

```bash
uv run pytest                 # all tests
uv run pytest --cov=app       # with coverage
```

No network access is needed: Massive is replaced by a fake HTTP transport in the tests.
