"""Market data domain objects. Pure Python: no Django, no I/O."""
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class Timeframe(StrEnum):
    INTRADAY_3H = "3H"
    DAILY = "1D"


class RunKind(StrEnum):
    INTRADAY = "intraday"
    END_OF_DAY = "eod"
    BACKFILL = "backfill"


@dataclass(frozen=True)
class Quote:
    """One symbol's prices exactly as a source reported them at fetch time."""

    symbol: str
    ltp: Decimal
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    previous_close: Decimal | None = None
    change_percent: Decimal | None = None
    volume: int = 0
    turnover: Decimal | None = None
    trades: int | None = None


@dataclass(frozen=True)
class HistoricalBar:
    """One daily bar from a history source."""

    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = 0


@dataclass(frozen=True)
class Candle:
    """The canonical OHLCV record the rest of the system works with."""

    symbol: str
    timeframe: Timeframe
    ts: datetime
    trading_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = 0
    previous_close: Decimal | None = None
    turnover: Decimal | None = None
    trades: int | None = None

    @classmethod
    def from_quote(cls, quote: Quote, timeframe: Timeframe, ts: datetime, trading_date: date):
        # Untraded or partially reported symbols fall back to LTP for missing OHLC.
        return cls(
            symbol=quote.symbol,
            timeframe=timeframe,
            ts=ts,
            trading_date=trading_date,
            open=quote.open if quote.open is not None else quote.ltp,
            high=quote.high if quote.high is not None else quote.ltp,
            low=quote.low if quote.low is not None else quote.ltp,
            close=quote.ltp,
            volume=quote.volume,
            previous_close=quote.previous_close,
            turnover=quote.turnover,
            trades=quote.trades,
        )


@dataclass(frozen=True)
class Issue:
    rule: str
    message: str
    severity: str = "reject"  # "reject" quarantines the candle; "flag" keeps it but records the issue


@dataclass
class ValidationResult:
    accepted: list[Candle] = field(default_factory=list)
    quarantined: list[tuple[Candle, list[Issue]]] = field(default_factory=list)
    flagged: list[tuple[Candle, list[Issue]]] = field(default_factory=list)
