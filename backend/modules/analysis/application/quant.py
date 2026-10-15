"""Use cases for the admin Quant section: evaluate one strategy's accuracy and speed."""
import logging
import time
from dataclasses import asdict
from datetime import timedelta

from django.utils import timezone

from modules.marketdata import public as marketdata

from ..domain import evaluation
from ..domain.strategies import DESCRIPTIONS, REGISTRY, StrategyConfig
from ..infrastructure.models import AnalysisRun, Prediction, QuantEvaluation
from .backtest import _series

logger = logging.getLogger(__name__)

DEFAULT_DAYS = 365


def can_replay(strategy):
    """Per-symbol strategies replay over history; pairs and basket are scored on live predictions only."""
    return strategy in REGISTRY


def start_evaluation(strategy, days=DEFAULT_DAYS, symbols=None, end=None):
    if strategy not in DESCRIPTIONS:
        raise ValueError(f"Unknown strategy {strategy!r}")
    end = end or timezone.localdate()
    return QuantEvaluation.objects.create(
        strategy=strategy, start_date=end - timedelta(days=days), end_date=end,
        symbols=[s.upper() for s in symbols or []], parameters=asdict(StrategyConfig()),
    )


def run_evaluation(evaluation_id):
    ev = QuantEvaluation.objects.get(pk=evaluation_id)
    started = time.perf_counter()
    try:
        if can_replay(ev.strategy):
            replay, tested = None, 0
            for symbol in ev.symbols or marketdata.list_symbols():
                # Bars after the end date only settle the last calls.
                series = _series(symbol, ev.start_date, ev.end_date + timedelta(days=60))
                if not any(ev.start_date <= d <= ev.end_date for d in series.dates):
                    continue
                tested += 1
                replay = evaluation.replay_strategy(
                    [series], ev.strategy, REGISTRY[ev.strategy], ev.start_date, ev.end_date, replay=replay,
                )
            if replay is not None:
                ev.metrics = evaluation.metrics(replay, ev.start_date, ev.end_date)
                ev.trades = evaluation.trade_rows(replay)
            ev.symbols_tested = tested
        ev.live = live_record(ev.strategy, ev.start_date, ev.end_date)
        ev.status = QuantEvaluation.Status.OK
    except Exception as exc:
        logger.exception("Quant evaluation %s failed", ev.pk)
        ev.status, ev.error = QuantEvaluation.Status.FAILED, str(exc)
    ev.duration_seconds = round(time.perf_counter() - started, 2)
    ev.finished_at = timezone.now()
    ev.save()
    return ev


def live_record(strategy, start, end):
    """The same measures over the predictions the live pipeline actually stored and settled."""
    rows = Prediction.objects.filter(strategy=strategy, made_on__gte=start, made_on__lte=end)
    replay = evaluation.Replay(trades=[], baseline={})
    for p in rows:
        if not p.outcome:
            replay.open_calls += 1
            continue
        ret = p.return_pct or 0.0
        replay.trades.append(evaluation.Trade(
            p.symbol, p.made_on, p.direction, float(p.entry_price), _f(p.target_price), _f(p.stop_price), p.horizon,
            p.outcome, p.exit_date, float(p.exit_price), p.sessions or 0, ret,
            ret if p.direction == "bullish" else -ret, bool(p.correct), None,
        ))
    result = evaluation.metrics(replay, start, end)
    runs = list(AnalysisRun.objects.filter(status=AnalysisRun.Status.OK, finished_at__isnull=False).order_by("-finished_at")[:20])
    timed = [(r.finished_at - r.started_at).total_seconds() for r in runs]
    symbols = sum(r.symbols_analyzed for r in runs)
    result["pipeline"] = {
        "runs": len(runs),
        "avg_run_seconds": round(sum(timed) / len(timed), 1) if timed else None,
        "ms_per_symbol": round(sum(timed) / symbols * 1000, 1) if symbols else None,
    }
    return result


def _f(value):
    return float(value) if value is not None else None
