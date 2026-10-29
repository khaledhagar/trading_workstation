#!/usr/bin/env bash
# Stop and remove the trading_workstation container (macOS/Linux). Data volume is kept. Idempotent.
set -euo pipefail
# Git Bash on Windows would rewrite container paths like /app/db into C:/Program Files/Git/...
export MSYS_NO_PATHCONV=1

CONTAINER="trading-workstation"

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running; nothing to stop."
  exit 0
fi

if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
  docker rm -f "$CONTAINER" >/dev/null
  echo "Stopped and removed container $CONTAINER. Data volume trading-workstation-data is kept."
else
  echo "Container $CONTAINER is not running."
fi
