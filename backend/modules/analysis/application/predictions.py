"""Use cases: record each end-of-day signal as a prediction, and settle predictions against actual prices."""
import logging
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from modules.marketdata import public as marketdata

from ..domain import predictions as domain
from ..infrastructure.models import AnalysisRun, Prediction, Signal

logger = logging.getLogger(__name__)


def _dec(value):
    return Decimal(str(round(value, 2))) if value is not None else None


def record_predictions(run_id):
    """One prediction per directional signal of a closing (not intraday) run. Returns how many were stored."""
    run = AnalysisRun.objects.get(pk=run_id)
    if run.provisional:
        return 0
    rows = []
    for signal in Signal.objects.filter(run=run).select_related("analysis"):
        d = domain.draft(
            {"strategy": signal.strategy, "direction": signal.direction, "strength": signal.strength, "values": signal.values},
            signal.analysis.indicators.get("close"),
        )
        if d is None:
            continue
        rows.append(Prediction(
            run=run, signal=signal, symbol=signal.symbol, strategy=d.strategy, direction=d.direction, strength=d.strength,
            made_on=run.trading_date, entry_price=_dec(d.entry_price), target_price=_dec(d.target_price),
            stop_price=_dec(d.stop_price), horizon=d.horizon,
        ))
    Prediction.objects.bulk_create(rows, ignore_conflicts=True)  # re-runs of the same day keep the first
    return len(rows)


def _f(value):
    return float(value) if value is not None else None


def settle_predictions():
    """Score every open prediction that the prices since have decided. Returns how many were settled."""
    open_rows = list(Prediction.objects.filter(outcome="").order_by("symbol", "made_on"))
    settled, by_symbol = 0, {}
    for p in open_rows:
        by_symbol.setdefault(p.symbol, []).append(p)
    for symbol, rows in by_symbol.items():
        earliest = min(p.made_on for p in rows)
        candles = marketdata.get_candles(symbol, marketdata.Timeframe.DAILY, start=earliest + timedelta(days=1))
        bars = [(c.trading_date, float(c.high), float(c.low), float(c.close)) for c in candles]
        for p in rows:
            result = domain.score(
                p.direction, float(p.entry_price), _f(p.target_price), _f(p.stop_price), p.horizon,
                [b for b in bars if b[0] > p.made_on],
            )
            if result is None:
                continue
            p.outcome, p.exit_date, p.exit_price = result.outcome, result.exit_date, _dec(result.exit_price)
            p.sessions, p.return_pct, p.correct, p.settled_at = result.sessions, result.return_pct, result.correct, timezone.now()
            p.save(update_fields=["outcome", "exit_date", "exit_price", "sessions", "return_pct", "correct", "settled_at"])
            settled += 1
    logger.info("Settled %d of %d open predictions", settled, len(open_rows))
    return settled
