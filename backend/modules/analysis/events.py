from dataclasses import dataclass

from modules.shared.events import DomainEvent


@dataclass(frozen=True)
class SignalsGenerated(DomainEvent):
    """An analysis run finished. Notifications subscribes to build the email digest."""

    analysis_run_id: int
    trading_date: str  # ISO date
    provisional: bool
    signals_count: int
