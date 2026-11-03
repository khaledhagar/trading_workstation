#!/usr/bin/env bash
# Stop and remove the trading_workstation container. The data volume is kept.
set -euo pipefail

CONTAINER=trading-workstation
if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  docker rm -f "$CONTAINER" >/dev/null
  echo "Stopped $CONTAINER (data volume kept)."
else
  echo "$CONTAINER is not running."
fi
