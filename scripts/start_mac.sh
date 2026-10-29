#!/usr/bin/env bash
# Start trading_workstation in Docker (macOS/Linux). Idempotent: safe to run repeatedly.
# Usage: ./scripts/start_mac.sh [--build] [--no-open]
set -euo pipefail
# Git Bash on Windows would rewrite container paths like /app/db into C:/Program Files/Git/...
export MSYS_NO_PATHCONV=1

IMAGE="trading-workstation"
CONTAINER="trading-workstation"
VOLUME="trading-workstation-data"
PORT="${PORT:-8000}"
URL="http://localhost:${PORT}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Relative host paths from here on (absolute Git Bash paths would not reach docker.exe unconverted)
cd "$ROOT"
BUILD=0
OPEN=1
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=1 ;;
    --no-open) OPEN=0 ;;
    -h|--help) echo "Usage: $0 [--build] [--no-open]"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Start Docker and try again." >&2
  exit 1
fi

if [[ "$BUILD" == 1 ]] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building image $IMAGE..."
  docker build -t "$IMAGE" .
fi

# Replace an existing container (running or stopped); the data volume is kept
if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "Replacing existing container $CONTAINER..."
  docker rm -f "$CONTAINER" >/dev/null
fi

ENV_ARGS=()
if [[ -f .env ]]; then
  ENV_ARGS=(--env-file .env)
else
  echo "Warning: no .env file found; chat will be unavailable. Copy .env.example to .env and set OPENROUTER_API_KEY." >&2
fi

docker run -d \
  --name "$CONTAINER" \
  -p "${PORT}:8000" \
  -v "${VOLUME}:/app/db" \
  "${ENV_ARGS[@]+"${ENV_ARGS[@]}"}" \
  -e DB_PATH=/app/db/trading_workstation.db \
  "$IMAGE" >/dev/null

echo "Waiting for the app to become ready..."
READY=0
for _ in $(seq 1 60); do
  if curl -fsS "${URL}/api/health" >/dev/null 2>&1; then
    READY=1
    break
  fi
  if [[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" != "true" ]]; then
    echo "Container exited. Logs:" >&2
    docker logs "$CONTAINER" >&2 || true
    exit 1
  fi
  sleep 1
done
if [[ "$READY" != 1 ]]; then
  echo "Warning: the app did not answer the health check within 60s; it may still be starting." >&2
fi

echo "trading_workstation is running at ${URL}"
echo "Stop it with ./scripts/stop_mac.sh (your data is kept)."

if [[ "$OPEN" == 1 ]]; then
  if command -v open >/dev/null 2>&1; then open "$URL" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || true
  fi
fi
