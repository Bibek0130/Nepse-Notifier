"""The analysis module's public interface. Returns plain dicts, never ORM models."""
from .application import queries
from .events import SignalsGenerated


def get_run_report(analysis_run_id: int) -> dict:
    """Everything a digest needs for one run: run info, signals, and per-symbol levels."""
    return queries.run_report(analysis_run_id)


def get_latest_run_id() -> int | None:
    run = queries.latest_run()
    return run.pk if run else None


def get_latest_analysis(symbol: str) -> dict | None:
    return queries.latest_for_symbol(symbol)


__all__ = ["SignalsGenerated", "get_latest_analysis", "get_latest_run_id", "get_run_report"]
