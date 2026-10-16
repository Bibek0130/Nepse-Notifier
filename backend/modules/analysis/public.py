"""The analysis module's public interface. Returns plain dicts, never ORM models."""
from .application import queries
from .events import SignalsGenerated

# The quant strategies whose buy calls the email digest picks from (the NEPSE research ones).
QUANT_STRATEGIES = queries.FEATURED


def get_run_report(analysis_run_id: int) -> dict:
    """Everything a digest needs for one run: run info, signals, and per-symbol levels."""
    return queries.run_report(analysis_run_id)


def get_latest_run_id() -> int | None:
    run = queries.latest_run()
    return run.pk if run else None


def get_latest_analysis(symbol: str) -> dict | None:
    return queries.latest_for_symbol(symbol)


def get_strategy_scorecard(days: int = 180) -> dict:
    """How each strategy's stored predictions played out: hit rate, average return, targets and stops hit."""
    return queries.scorecard(days)


__all__ = [
    "QUANT_STRATEGIES", "SignalsGenerated", "get_latest_analysis", "get_latest_run_id", "get_run_report", "get_strategy_scorecard"]
