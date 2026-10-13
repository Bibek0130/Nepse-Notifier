import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def on_candles_ingested(run_id, timeframe, trading_date, symbols):
    """Entry point for analysis after each ingestion run.

    Step 2 replaces this with a chord: one analyze_symbol task per symbol,
    then aggregate_signals, which hands the result to notifications.
    """
    logger.info("Run %s: %d %s candles for %s ready for analysis", run_id, len(symbols), timeframe, trading_date)
    return len(symbols)
