from dataclasses import dataclass

from modules.shared.events import DomainEvent


@dataclass(frozen=True)
class CandlesIngested(DomainEvent):
    """New validated candles are in Postgres. Published after the transaction commits."""

    run_id: int
    timeframe: str
    trading_date: str  # ISO date
    symbols: list[str]
