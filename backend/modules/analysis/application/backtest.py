"""Use case: replay the strategies over past prices and store how their signals played out."""
import logging
from dataclasses import asdict
from datetime import timedelta

from django.utils import timezone

from modules.marketdata import public as marketdata

from ..domain import backtest as bt
from ..domain.entities import PriceSeries
from ..infrastructure.models import BacktestRun

logger = logging.getLogger(__name__)

WARMUP_DAYS = 500  # calendar days of extra history so day one already has the 240-session quant trend


def _series(symbol, start, end):
    bars = marketdata.get_candles(symbol, marketdata.Timeframe.DAILY, start=start - timedelta(days=WARMUP_DAYS), end=end)
    return PriceSeries(
        symbol=symbol,
        dates=[b.trading_date for b in bars],
        opens=[float(b.open) for b in bars],
        highs=[float(b.high) for b in bars],
        lows=[float(b.low) for b in bars],
        closes=[float(b.close) for b in bars],
        volumes=[float(b.volume) for b in bars],
        trades=[float(b.trades) if b.trades is not None else None for b in bars],
    )


def run_backtest(start, end, symbols=None, horizons=bt.HORIZONS):
    """Replay every strategy for each trading day from ``start`` to ``end``.

    Forward returns may look past ``end`` when the data exists, so recent signals
    still get measured; signals too recent to measure count with samples=0.
    """
    run = BacktestRun.objects.create(start_date=start, end_date=end, horizons=list(horizons))
    try:
        symbols = symbols or marketdata.list_symbols()
        outcomes, baseline, tested = [], {h: [] for h in horizons}, 0
        for symbol in symbols:
            # Load past ``end`` too: those bars only measure what followed the last signals.
            series = _series(symbol, start, end + timedelta(days=60))
            if not any(start <= d <= end for d in series.dates):
                continue
            tested += 1
            outcomes.extend(bt.replay(series, start, end, horizons=horizons))
            for h, returns in bt.baseline(series, start, end, horizons).items():
                baseline[h].extend(returns)
        run.results = {
            str(level): [asdict(s) for s in bt.summarize(outcomes, horizons, min_strength=level)] for level in (1, 2, 3)
        }
        run.baseline = [asdict(s) for s in bt.summarize_baseline(baseline)]
        run.symbols_tested = tested
        run.signals_evaluated = len(outcomes)
        run.status = BacktestRun.Status.OK
    except Exception as exc:
        logger.exception("Backtest %s failed", run.pk)
        run.status = BacktestRun.Status.FAILED
        run.error = str(exc)
    run.finished_at = timezone.now()
    run.save()
    return run
