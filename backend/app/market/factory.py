import logging
import os
from collections.abc import Mapping

from .base import MarketDataSource
from .cache import PriceCache
from .massive.source import MassiveSource
from .simulator.source import SimulatorSource

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL = 15.0
MIN_POLL_INTERVAL = 2.0


def _float_env(env: Mapping[str, str], name: str, default: float, minimum: float) -> float:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Ignoring %s=%r (not a number); using %s", name, raw, default)
        return default
    if value != value or value in (float("inf"), float("-inf")):   # NaN / inf
        logger.warning("Ignoring %s=%r; using %s", name, raw, default)
        return default
    if value < minimum:
        logger.warning("%s=%s is below the minimum; using %s", name, raw, minimum)
        return minimum
    return value


def create_market_data_source(
    cache: PriceCache, env: Mapping[str, str] | None = None
) -> MarketDataSource:
    """PLAN.md §5: MASSIVE_API_KEY set → MassiveSource, otherwise the simulator.

    `env` defaults to os.environ; tests pass a plain dict."""
    env = os.environ if env is None else env
    api_key = (env.get("MASSIVE_API_KEY") or "").strip()
    if not api_key:
        logger.info("Market data source: simulator")
        return SimulatorSource(cache)

    mode = (env.get("MASSIVE_MODE") or "").strip().lower() or None
    if mode not in (None, "snapshot", "eod"):
        logger.warning("Ignoring MASSIVE_MODE=%r; auto-detecting", mode)
        mode = None
    interval = _float_env(env, "MASSIVE_POLL_INTERVAL", DEFAULT_POLL_INTERVAL, MIN_POLL_INTERVAL)

    logger.info("Market data source: Massive API (mode=%s)", mode or "auto")
    return MassiveSource(cache, api_key, mode=mode, poll_interval=interval)  # type: ignore[arg-type]
