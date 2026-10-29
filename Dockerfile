# syntax=docker/dockerfile:1
# trading_workstation — single container: FastAPI serves the API, SSE and the Next.js static export.

# ---- Stage 1: build the frontend static export ----
FROM node:20-slim AS frontend
WORKDIR /app/frontend
ENV NEXT_TELEMETRY_DISABLED=1
# Dependencies first, so this layer is cached until package*.json changes
COPY frontend/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python runtime ----
FROM python:3.12-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/backend/.venv/bin:$PATH"

WORKDIR /app/backend
# Dependencies first (cached until the lockfile changes)
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev

COPY --from=frontend /app/frontend/out /app/static

ENV DB_PATH=/app/db/trading_workstation.db \
    STATIC_DIR=/app/static
RUN mkdir -p /app/db
VOLUME ["/app/db"]

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
