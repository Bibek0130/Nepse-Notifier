"""Evaluate one strategy: replay it over history, score every call against what prices did, and time it.

The replay is walk-forward (each day sees only bars up to that day) and every signal is
turned into a prediction and settled exactly like the live pipeline does (``predictions``),
so the replayed accuracy is comparable with the live track record. Pure Python.

Measures, all computed from settled predictions:
- accuracy: hit rate (price moved the predicted way), with a 95% confidence interval and a
  significance test against what buying on any day would have achieved (the baseline);
- forecast vs actual: where a strategy names a target price, the error between that target
  and the close at the horizon (MAE, RMSE, bias), plus how often the target was reached;
- trade quality: average return, win/loss sizes, profit factor, expectancy, Sharpe, Sortino;
- risk: an equity curve with max drawdown, and a Monte Carlo bootstrap of the calls;
- speed: wall time, milliseconds per bar for the whole analysis and for the strategy alone,
  and how many sessions calls take to resolve.
"""
import math
import random
import statistics
import time
from dataclasses import asdict, dataclass

from .backtest import _days, window
from .engine import analyze
from .predictions import DEFAULT_HORIZON, HORIZONS, draft, score
from .strategies import StrategyConfig

MAX_OPEN = 4  # equity curve stakes 1/4 of capital per trade, like the paper's four-trade limit
MONTE_CARLO_RUNS = 1000
TRADING_DAYS = 240  # NEPSE sessions in a year, roughly


@dataclass(frozen=True)
class Trade:
    symbol: str
    made_on: object  # date
    direction: str
    entry: float
    target: float | None
    stop: float | None
    horizon: int
    outcome: str
    exit_date: object
    exit_price: float
    sessions: int
    return_pct: float  # raw price change
    edge_pct: float  # return in the predicted direction
    correct: bool
    close_at_horizon: float | None  # the actual close ``horizon`` sessions later, when known


@dataclass
class Replay:
    trades: list
    open_calls: int = 0  # signals too recent to settle
    bars: int = 0  # symbol-days evaluated
    analysis_seconds: float = 0.0
    strategy_seconds: float = 0.0
    baseline: dict = None  # horizon -> list of every-day returns, for comparison


def _timed(fn, clock):
    def wrapper(ctx):
        t = time.perf_counter()
        out = list(fn(ctx))
        clock[0] += time.perf_counter() - t
        return out
    wrapper.__name__ = getattr(fn, "__name__", "strategy")
    return wrapper


def replay_strategy(series_list, name, strategy, start=None, end=None, config=StrategyConfig(), replay=None) -> Replay:
    """Walk forward over each series and settle every call ``strategy`` (registered as ``name``) makes.

    Pass the same ``replay`` again to add more series, e.g. one symbol at a time.
    """
    horizon = HORIZONS.get(name, DEFAULT_HORIZON)
    replay = replay or Replay(trades=[], baseline={horizon: []})
    clock = [0.0]
    timed = _timed(strategy, clock)
    for series in series_list:
        closes = series.closes
        for i in _days(series, start, end):
            replay.bars += 1
            t = time.perf_counter()
            analysis = analyze(window(series, i), config, [timed])
            replay.analysis_seconds += time.perf_counter() - t
            if not analysis:
                continue
            for signal in analysis.signals:
                d = draft(signal, closes[i])
                if d is None:
                    continue
                bars = list(zip(series.dates[i + 1 :], series.highs[i + 1 :], series.lows[i + 1 :], closes[i + 1 :]))[: d.horizon]
                result = score(d.direction, d.entry_price, d.target_price, d.stop_price, d.horizon, bars)
                if result is None:
                    replay.open_calls += 1
                    continue
                edge = result.return_pct if d.direction == "bullish" else -result.return_pct
                replay.trades.append(Trade(
                    series.symbol, series.dates[i], d.direction, d.entry_price, d.target_price, d.stop_price, d.horizon,
                    result.outcome, result.exit_date, result.exit_price, result.sessions, result.return_pct, round(edge, 3),
                    result.correct, closes[i + d.horizon] if i + d.horizon < len(closes) else None,
                ))
        # Every-day returns over the horizons this strategy uses: what simply buying would have done.
        for i in _days(series, start, end):
            if i + horizon < len(closes) and closes[i]:
                replay.baseline[horizon].append((closes[i + horizon] / closes[i] - 1) * 100)
    replay.strategy_seconds += clock[0]
    return replay


def _round(v, n=2):
    return None if v is None else round(v, n)


def _pct(part, whole):
    return round(part / whole * 100, 1) if whole else None


def wilson_interval(hits, n, z=1.96):
    """95% confidence interval for a hit rate, in percent."""
    if not n:
        return None, None
    p = hits / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round((centre - spread) * 100, 1), round((centre + spread) * 100, 1)


def p_value(hits, expected_rates):
    """Two-sided p-value that the hit count differs from chance, where chance is a per-call probability."""
    n = len(expected_rates)
    if not n:
        return None
    mean = sum(expected_rates)
    var = sum(p * (1 - p) for p in expected_rates)
    if var == 0:
        return None
    z = (hits - mean) / math.sqrt(var)
    return round(math.erfc(abs(z) / math.sqrt(2)), 4)


def max_drawdown(equity):
    peak, worst = equity[0] if equity else 1.0, 0.0
    for v in equity:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return round(worst * 100, 2)


def equity_curve(edges, stake=1 / MAX_OPEN):
    equity, curve = 1.0, [1.0]
    for e in edges:
        equity *= 1 + stake * e / 100
        curve.append(equity)
    return curve


def monte_carlo(edges, runs=MONTE_CARLO_RUNS, seed=7):
    """Bootstrap: redraw the same number of calls from the real ones (with replacement) ``runs`` times,
    to see the range of results and drawdowns this strategy's calls could plausibly have produced."""
    if len(edges) < 2:
        return None
    rng, finals, drawdowns = random.Random(seed), [], []
    for _ in range(runs):
        curve = equity_curve(rng.choices(edges, k=len(edges)))
        finals.append(curve[-1])
        drawdowns.append(max_drawdown(curve))
    finals.sort()
    drawdowns.sort()
    return {
        "runs": runs,
        "median_return_pct": _round((statistics.median(finals) - 1) * 100),
        "p5_return_pct": _round((finals[int(runs * 0.05)] - 1) * 100),
        "median_max_drawdown_pct": _round(statistics.median(drawdowns)),
        "worst_max_drawdown_pct": drawdowns[0],
        "p5_max_drawdown_pct": drawdowns[int(runs * 0.05)],
        "losing_runs_pct": _pct(sum(f < 1 for f in finals), runs),
    }


def _baseline_rates(baseline):
    """Share of days the price rose, and the average return, for each horizon."""
    out = {}
    for h, returns in baseline.items():
        if returns:
            out[h] = {"up_rate": sum(r > 0 for r in returns) / len(returns), "avg_return": sum(returns) / len(returns),
                      "samples": len(returns)}
    return out


def metrics(replay: Replay, start=None, end=None) -> dict:
    trades = sorted(replay.trades, key=lambda t: (t.exit_date, t.symbol))
    n = len(trades)
    edges = [t.edge_pct for t in trades]
    hits = sum(t.correct for t in trades)
    wins = [e for e in edges if e > 0]
    losses = [e for e in edges if e <= 0]
    base = _baseline_rates(replay.baseline or {})

    def chance(t):
        b = base.get(t.horizon)
        up = b["up_rate"] if b else 0.5
        return up if t.direction == "bullish" else 1 - up

    low, high = wilson_interval(hits, n)
    mean = statistics.fmean(edges) if edges else None
    std = statistics.pstdev(edges) if n > 1 else None
    downside = math.sqrt(sum(min(e, 0) ** 2 for e in edges) / n) if n else None
    avg_sessions = statistics.fmean(t.sessions for t in trades) if trades else None
    per_year = TRADING_DAYS / avg_sessions if avg_sessions else None

    forecasts = [(t.target, t.close_at_horizon) for t in trades if t.target and t.close_at_horizon]
    errors = [(actual - target) / target * 100 for target, actual in forecasts]
    with_target = [t for t in trades if t.target]

    curve = equity_curve(edges)
    years = None
    if trades and start and end:
        years = max((end - start).days / 365.25, 1 / 365.25)
    bullish = [t for t in trades if t.direction == "bullish"]
    base_avg = None
    if bullish:
        weights = [base[t.horizon]["avg_return"] for t in bullish if t.horizon in base]
        base_avg = statistics.fmean(weights) if weights else None

    return {
        "calls": n + replay.open_calls,
        "settled": n,
        "open": replay.open_calls,
        "bullish": len(bullish),
        "bearish": n - len(bullish),
        "accuracy": {
            "hit_rate": _pct(hits, n),
            "hit_rate_ci95": [low, high],
            "chance_hit_rate": _pct(sum(chance(t) for t in trades), n),
            "p_value": p_value(hits, [chance(t) for t in trades]),
            "targets_hit_pct": _pct(sum(t.outcome == "target" for t in trades), n),
            "stops_hit_pct": _pct(sum(t.outcome == "stop" for t in trades), n),
            "expired_pct": _pct(sum(t.outcome == "horizon" for t in trades), n),
        },
        "forecast_error": {
            "samples": len(errors),
            "calls_with_target": len(with_target),
            "target_reached_pct": _pct(sum(t.outcome == "target" for t in with_target), len(with_target)),
            "mae_pct": _round(statistics.fmean(abs(e) for e in errors)) if errors else None,
            "rmse_pct": _round(math.sqrt(statistics.fmean(e * e for e in errors))) if errors else None,
            "bias_pct": _round(statistics.fmean(errors)) if errors else None,
        },
        "returns": {
            "avg_return_pct": _round(mean),
            "median_return_pct": _round(statistics.median(edges)) if edges else None,
            "avg_win_pct": _round(statistics.fmean(wins)) if wins else None,
            "avg_loss_pct": _round(statistics.fmean(losses)) if losses else None,
            "win_loss_ratio": _round(statistics.fmean(wins) / abs(statistics.fmean(losses))) if wins and losses and statistics.fmean(losses) else None,
            "profit_factor": _round(sum(wins) / abs(sum(losses))) if wins and losses and sum(losses) else None,
            "baseline_avg_return_pct": _round(base_avg),
            "edge_vs_baseline_pct": _round(statistics.fmean(t.edge_pct for t in bullish) - base_avg) if bullish and base_avg is not None else None,
            "sharpe": _round(mean / std * math.sqrt(per_year)) if std and per_year else None,
            "sortino": _round(mean / downside * math.sqrt(per_year)) if downside and per_year else None,
        },
        "risk": {
            "stake_per_trade_pct": round(100 / MAX_OPEN),
            "total_return_pct": _round((curve[-1] - 1) * 100),
            "cagr_pct": _round((curve[-1] ** (1 / years) - 1) * 100) if years and curve[-1] > 0 else None,
            "max_drawdown_pct": max_drawdown(curve),
            "longest_losing_streak": _streak(edges),
            "monte_carlo": monte_carlo(edges),
        },
        "speed": {
            "bars_evaluated": replay.bars,
            "analysis_ms_per_bar": _round(replay.analysis_seconds / replay.bars * 1000, 3) if replay.bars else None,
            "strategy_ms_per_bar": _round(replay.strategy_seconds / replay.bars * 1000, 4) if replay.bars else None,
            "avg_sessions_to_resolve": _round(avg_sessions, 1),
            "avg_sessions_to_target": _round(statistics.fmean(t.sessions for t in trades if t.outcome == "target"), 1)
            if any(t.outcome == "target" for t in trades) else None,
        },
    }


def _streak(edges):
    best = run = 0
    for e in edges:
        run = run + 1 if e <= 0 else 0
        best = max(best, run)
    return best


def trade_rows(replay: Replay, limit=50):
    """The most recent settled calls, for a sample table."""
    rows = sorted(replay.trades, key=lambda t: t.made_on, reverse=True)[:limit]
    return [{**asdict(t), "made_on": t.made_on.isoformat(), "exit_date": t.exit_date.isoformat()} for t in rows]
