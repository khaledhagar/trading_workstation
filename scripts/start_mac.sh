#!/usr/bin/env bash
# Start trading_workstation in Docker. Usage: ./scripts/start_mac.sh [--build] [--no-open]
set -euo pipefail

IMAGE=trading-workstation
CONTAINER=trading-workstation
VOLUME=trading-workstation-data
PORT=8000
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BUILD=0
OPEN=1
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=1 ;;
    --no-open) OPEN=0 ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

if [ ! -f "$ROOT/.env" ]; then
  echo "No .env found; creating one from .env.example (set OPENROUTER_API_KEY for chat)."
  cp "$ROOT/.env.example" "$ROOT/.env"
fi

if [ "$BUILD" = 1 ] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building image $IMAGE..."
  docker build -t "$IMAGE" "$ROOT"
fi

# Replace any existing container (idempotent).
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true

docker run -d --name "$CONTAINER" \
  -v "$VOLUME":/app/db \
  -p "$PORT":8000 \
  --env-file "$ROOT/.env" \
  --restart unless-stopped \
  "$IMAGE" >/dev/null

URL="http://localhost:$PORT"
echo -n "Waiting for the app"
for _ in $(seq 1 30); do
  if curl -fs "$URL/api/health" >/dev/null 2>&1; then break; fi
  echo -n "."; sleep 1
done
echo
echo "trading_workstation is running at $URL"

if [ "$OPEN" = 1 ]; then
  if command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || true
  fi
fi
