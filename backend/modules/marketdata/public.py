"""The market data module's public interface.

Other modules import ONLY from here (enforced by import-linter). Everything
returned is a plain domain object or dict, never an ORM model.
"""
from .application import queries
from .domain.entities import Candle, Timeframe
from .events import CandlesIngested


def get_candles(symbol: str, timeframe: Timeframe | str = Timeframe.DAILY, start=None, end=None) -> list[Candle]:
    return queries.candles(symbol, Timeframe(timeframe).value, start, end)


def get_latest_quotes() -> list[dict]:
    return queries.latest_quotes()


def get_market_summary() -> dict:
    return queries.market_summary()


def list_symbols() -> list[str]:
    return list(queries.instruments().values_list("symbol", flat=True))


def get_sectors() -> dict[str, str]:
    """Sector of each active symbol ("" when unknown; sectors are filled in via admin)."""
    return dict(queries.instruments().values_list("symbol", "sector"))


__all__ = ["Candle", "CandlesIngested", "Timeframe", "get_candles", "get_latest_quotes", "get_market_summary", "get_sectors", "list_symbols"]
