"""Use cases for the admin Quant section: evaluate one strategy's accuracy and speed."""
import logging
import time
from dataclasses import asdict
from datetime import timedelta

from django.utils import timezone

from modules.marketdata import public as marketdata
from modules.shared.locks import LockNotAcquired, single_flight

from ..domain import evaluation, pca, stat_arb
from ..domain.strategies import CROSS_SECTIONAL, DESCRIPTIONS, REGISTRY, StrategyConfig, sessions_needed
from ..infrastructure.models import AnalysisRun, Prediction, QuantEvaluation
from .backtest import _series
from .cross_section import groups_for

logger = logging.getLogger(__name__)

DEFAULT_DAYS = 365
# The Celery task's time limit: an evaluation still "running" after this died with its worker or thread.
STALE_AFTER = timedelta(hours=1)


class EvaluationRunning(Exception):
    """This strategy already has an evaluation in progress; ``evaluation`` is that one."""

    def __init__(self, evaluation):
        super().__init__(f"{evaluation.strategy} is already being evaluated (#{evaluation.pk})")
        self.evaluation = evaluation


def running_evaluation(strategy):
    """The evaluation in progress for ``strategy``, if any. Ones left behind by a crash are marked failed."""
    running = QuantEvaluation.objects.filter(strategy=strategy, status=QuantEvaluation.Status.RUNNING)
    running.filter(started_at__lt=timezone.now() - STALE_AFTER).update(
        status=QuantEvaluation.Status.FAILED, error="Stopped: did not finish within an hour", finished_at=timezone.now(),
    )
    return running.order_by("-started_at").first()


def can_replay(strategy):
    """Every strategy replays over history: per-symbol ones one stock at a time, pairs, basket and
    PCA leaders over all stocks together, day by day."""
    return strategy in REGISTRY or strategy in CROSS_SECTIONAL


def start_evaluation(strategy, days=DEFAULT_DAYS, symbols=None, end=None):
    """Create a running evaluation, or raise EvaluationRunning if this strategy already has one."""
    if strategy not in DESCRIPTIONS:
        raise ValueError(f"Unknown strategy {strategy!r}")
    end = end or timezone.localdate()
    # One evaluation per strategy at a time, so a double click or a second tab can't start the same work twice.
    try:
        with single_flight(f"quant-evaluation:{strategy}", timeout=30):
            if current := running_evaluation(strategy):
                raise EvaluationRunning(current)
            return QuantEvaluation.objects.create(
                strategy=strategy, start_date=end - timedelta(days=days), end_date=end,
                symbols=[s.upper() for s in symbols or []], parameters=asdict(StrategyConfig()),
            )
    except LockNotAcquired:
        # Another request is creating one this instant.
        raise EvaluationRunning(running_evaluation(strategy) or QuantEvaluation(strategy=strategy)) from None


def start_all(days=DEFAULT_DAYS, only_stale_days=None):
    """Start an evaluation of every strategy that isn't being evaluated already.

    With ``only_stale_days``, skip strategies that already have an evaluation that recent with
    settled calls (one that found nothing to measure, e.g. before the history download, is redone).
    """
    busy = set(QuantEvaluation.objects.filter(status=QuantEvaluation.Status.RUNNING).values_list("strategy", flat=True))
    fresh = set()
    if only_stale_days is not None:
        since = timezone.now() - timedelta(days=only_stale_days)
        recent = QuantEvaluation.objects.filter(status=QuantEvaluation.Status.OK, finished_at__gte=since)
        fresh = {ev.strategy for ev in recent if headline(ev).get("settled")}
    return [start_evaluation(name, days=days) for name in DESCRIPTIONS if name not in busy | fresh]


def run_evaluation(evaluation_id):
    ev = QuantEvaluation.objects.get(pk=evaluation_id)
    started = time.perf_counter()
    try:
        replay, longest, tested = None, 0, 0
        loaded = {}
        for symbol in ev.symbols or marketdata.list_symbols():
            # Bars after the end date only settle the last calls.
            series = _series(symbol, ev.start_date, ev.end_date + timedelta(days=60))
            longest = max(longest, sum(d <= ev.end_date for d in series.dates))
            if not any(ev.start_date <= d <= ev.end_date for d in series.dates):
                continue
            tested += 1
            if ev.strategy in REGISTRY:
                replay = evaluation.replay_strategy(
                    [series], ev.strategy, REGISTRY[ev.strategy], ev.start_date, ev.end_date, replay=replay,
                )
            else:
                loaded[symbol] = series
        if ev.strategy in CROSS_SECTIONAL:
            replay = evaluation.replay_cross_section(loaded, ev.strategy, cross_section_scanner(ev.strategy), ev.start_date, ev.end_date)
        replay = replay or evaluation.Replay(trades=[], baseline={})
        ev.metrics = evaluation.metrics(replay, ev.start_date, ev.end_date)
        ev.metrics["history"] = {"longest_sessions": longest, "sessions_needed": sessions_needed(ev.strategy)}
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


def cross_section_scanner(strategy):
    """What a live run does for pairs, basket or PCA leaders, for one day's {symbol: series}."""
    sectors = marketdata.get_sectors()
    scanner = pca.scan if strategy == pca.STRATEGY else stat_arb.scan

    def scan(series_by_symbol):
        series = {s: v for s, v in series_by_symbol.items() if len(v) >= min(stat_arb.LOOKBACK, pca.LOOKBACK + 1)}
        groups = groups_for(series, sectors)
        dates = {s: v.dates for s, v in series.items()}
        closes = {s: v.closes for s, v in series.items()}
        return scanner(dates, closes, groups)

    return scan


def headline(ev):
    """The measures to headline for an evaluation: the replay's, or the live record's when only live calls settled."""
    replay, live = ev.metrics or {}, ev.live or {}
    return live if not replay.get("settled") and live.get("settled") else replay or live


def missing_metrics(metrics):
    """Why hit rate, p-value or profit factor is blank for one set of measures, or "" when all three are there."""
    if not metrics:
        return "not measured"
    history = metrics.get("history") or {}
    if not metrics.get("calls"):
        need, have = history.get("sessions_needed"), history.get("longest_sessions")
        if need and have is not None and have < need:
            return f"no calls: needs {need} sessions of history, the longest saved is {have}"
        return "no calls in this period"
    if not metrics.get("settled"):
        return f"{metrics['open']} calls, none settled yet"
    if metrics["returns"]["profit_factor"] is None:
        return "no losing calls, so profit factor is unbounded"
    if metrics["accuracy"]["p_value"] is None:
        return "too few calls for a p-value"
    return ""


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
