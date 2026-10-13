"""Build the price series analysis runs on, from the market data module's public interface."""
from datetime import timedelta

from modules.marketdata import public as marketdata

from ..domain.entities import PriceSeries

HISTORY_DAYS = 420  # enough calendar days for a 200-session average


def load_series(symbol, trading_date, timeframe):
    """Daily bars up to ``trading_date``.

    For an intraday (3H) run the day hasn't closed yet, so the latest snapshot is
    appended as a provisional bar for today.
    """
    bars = marketdata.get_candles(symbol, marketdata.Timeframe.DAILY, start=trading_date - timedelta(days=HISTORY_DAYS), end=trading_date)
    provisional = False
    if timeframe == marketdata.Timeframe.INTRADAY_3H.value and (not bars or bars[-1].trading_date < trading_date):
        snapshots = marketdata.get_candles(symbol, marketdata.Timeframe.INTRADAY_3H, start=trading_date, end=trading_date)
        if snapshots:
            bars = [*bars, snapshots[-1]]
            provisional = True

    return PriceSeries(
        symbol=symbol,
        dates=[b.trading_date for b in bars],
        opens=[float(b.open) for b in bars],
        highs=[float(b.high) for b in bars],
        lows=[float(b.low) for b in bars],
        closes=[float(b.close) for b in bars],
        volumes=[float(b.volume) for b in bars],
        trades=[float(b.trades) if b.trades is not None else None for b in bars],
        provisional=provisional,
    )
