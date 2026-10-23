"""Market data: one interface, two sources, one shared price cache.

Code outside app.market imports only these names, never simulator/ or massive/ directly.
"""

from .base import MarketDataSource
from .cache import PriceCache
from .errors import InvalidTickerError, MarketDataUnavailableError, UnknownTickerError
from .factory import create_market_data_source
from .models import PriceUpdate
from .stream import price_events
from .tickers import normalize_ticker

__all__ = [
    "MarketDataSource",
    "PriceCache",
    "PriceUpdate",
    "InvalidTickerError",
    "UnknownTickerError",
    "MarketDataUnavailableError",
    "create_market_data_source",
    "normalize_ticker",
    "price_events",
]
