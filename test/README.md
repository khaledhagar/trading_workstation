# E2E tests (Playwright)

Pinned: `@playwright/test` 1.64.1 (Docker image `mcr.microsoft.com/playwright:v1.64.1-noble`).

The suite expects a **fresh database** and the backend running with `LLM_MOCK=true`.
Tests run serially (one shared DB) and clean up their own positions/watchlist changes.

## Against a local server

```bash
cd frontend && npm run build
cd backend
LLM_MOCK=true STATIC_DIR=../frontend/out DB_PATH=<temp>/e2e.db uv run uvicorn app.main:app --port 8000
cd test && npm ci && npx playwright install chromium && npx playwright test
```

`BASE_URL` overrides the target (default `http://localhost:8000`).

## In Docker

```bash
docker compose -f test/docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from playwright
```
