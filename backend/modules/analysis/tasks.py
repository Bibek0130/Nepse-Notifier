"""Celery entry points for analysis: fan out one task per symbol, then finish the run."""
import logging

from celery import chord, shared_task

from .application import run as use_cases

logger = logging.getLogger(__name__)


@shared_task
def on_candles_ingested(run_id, timeframe, trading_date, symbols):
    """Subscriber for marketdata's CandlesIngested event."""
    run = use_cases.start_run(run_id, timeframe, trading_date, symbols)
    if not symbols:
        finish_run.delay(run.pk)
        return run.pk
    chord((analyze_symbol.s(run.pk, symbol) for symbol in symbols), finish_run.si(run.pk)).apply_async()
    return run.pk


@shared_task(acks_late=True)
def analyze_symbol(run_id, symbol):
    # One bad symbol must not stop the chord, or finish_run would never fire.
    try:
        return use_cases.analyze_symbol(run_id, symbol)
    except Exception:
        logger.exception("Analysis run %s failed for %s", run_id, symbol)
        return None


@shared_task
def finish_run(run_id):
    return use_cases.finish_run(run_id).pk
