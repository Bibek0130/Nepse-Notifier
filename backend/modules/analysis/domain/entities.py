"""Analysis domain objects. Pure Python."""
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from .forecast import Forecast
from .levels import Level


class Direction(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class PriceSeries:
    """Daily bars for one symbol, oldest first."""

    symbol: str
    dates: list[date]
    opens: list[float]
    highs: list[float]
    lows: list[float]
    closes: list[float]
    volumes: list[float]
    trades: list[float | None]
    # True when the last bar is today's intraday snapshot rather than a closed day.
    provisional: bool = False

    def __len__(self):
        return len(self.closes)


@dataclass(frozen=True)
class Signal:
    strategy: str
    direction: Direction
    strength: int  # 1 = weak, 2 = moderate, 3 = strong
    message: str
    values: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Analysis:
    symbol: str
    trading_date: date
    provisional: bool
    indicators: dict
    support: Level | None
    resistance: Level | None
    forecast: Forecast | None
    signals: list[Signal]
