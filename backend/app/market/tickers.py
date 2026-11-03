import re

from .errors import InvalidTickerError

TICKER_RE = re.compile(r"[A-Z][A-Z.]{0,9}")


def normalize_ticker(raw: object) -> str:
    """Trim, uppercase and validate (PLAN.md §6 Ticker Rules).

    Called once, at the boundary (API route or LLM action). Sources and the cache
    receive already-normalized tickers.

    >>> normalize_ticker("  brk.b ")
    'BRK.B'
    """
    if not isinstance(raw, str):
        raise InvalidTickerError(raw)
    ticker = raw.strip().upper()
    if not TICKER_RE.fullmatch(ticker):
        raise InvalidTickerError(raw)
    return ticker
