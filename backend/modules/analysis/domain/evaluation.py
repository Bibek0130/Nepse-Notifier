"""Evaluate one strategy: replay it over history, score every call against what prices did, and time it.

The replay is walk-forward (each day sees only bars up to that day) and scores calls the way a
NEPSE investor could actually trade them. Pure Python.

- Buy calls are long trades. NEPSE has no short selling, so sell (bearish) calls are not trades:
  they are scored separately as exit warnings (did the price fall over the horizon?).
- The digest goes out after the close, so a buy is entered at the next session's open. The
  call's stop and target keep the same distance from the entry as from the signal close, and a
  session that opens beyond the stop or target exits at that open.
- Every trade pays NEPSE costs (broker commission and SEBON fee both ways, the DP charge, and
  capital gains tax on a profit), so returns are what an investor keeps.
- Significance: the strategy's average return is compared with random buys of other stocks on
  the same days, settled by the same rules (a permutation test). Calls on the same day move
  together with the market, and a stop/target changes the odds of a "hit", so comparing a hit
  rate with how often prices rise would be misleading.

Measures, all computed from settled buy trades:
- accuracy: hit rate (made money after costs), with a 95% confidence interval, the hit rate of
  random buys, and the p-value of the permutation test;
- forecast vs actual: where a strategy names a target price, the error between that target
  and the close at the horizon (MAE, RMSE, bias), plus how often the target was reached;
- trade quality: average return, win/loss sizes, profit factor, expectancy, Sharpe, Sortino;
- risk: an equity curve with max drawdown, and a Monte Carlo bootstrap of the calls;
- speed: wall time, milliseconds per bar for the whole analysis and for the strategy alone,
  and how many sessions calls take to resolve.
"""
import bisect
import math
import random
import statistics
import time
from dataclasses import asdict, dataclass, field

from .backtest import _days, window
from .engine import analyze
from .predictions import DEFAULT_HORIZON, HORIZONS, draft
from .strategies import StrategyConfig

MAX_OPEN = 4  # equity curve stakes 1/4 of capital per trade, like the paper's four-trade limit
MONTE_CARLO_RUNS = 1000
RANDOM_RUNS = 200  # sets of random buys the strategy's average return is compared with
TRADING_DAYS = 240  # NEPSE sessions in a year, roughly


@dataclass(frozen=True)
class Costs:
    """What a round trip costs on NEPSE, as fractions of the trade value (SEBON/broker schedule)."""

    commission: float = 0.0037  # broker commission each way, the NPR 50k-500k slab
    sebon_fee: float = 0.00015  # each way
    dp_charge: float = 25  # NPR per sale
    trade_value: float = 100_000  # NPR per trade, to turn the DP charge into a fraction
    capital_gains_tax: float = 0.075  # on a profit from shares held under a year

    def net_return_pct(self, gross_pct):
        """What an investor keeps, in percent of what they paid, from a ``gross_pct`` price move."""
        each_way = self.commission + self.sebon_fee
        paid = 1 + each_way
        received = (1 + gross_pct / 100) * (1 - each_way) - self.dp_charge / self.trade_value
        profit = received - paid
        if profit > 0:
            profit *= 1 - self.capital_gains_tax
        return profit / paid * 100


COSTS = Costs()


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
    edge_pct: float  # return in the predicted direction, before costs
    correct: bool  # price moved the predicted way
    close_at_horizon: float | None  # the actual close ``horizon`` sessions later, when known
    signal_close: float | None = None  # the close the call was made at (a replayed buy enters at the next open)


@dataclass
class Replay:
    trades: list  # settled buy trades
    open_calls: int = 0  # buy calls too recent to settle
    bars: int = 0  # symbol-days evaluated
    analysis_seconds: float = 0.0
    strategy_seconds: float = 0.0
    baseline: dict = None  # horizon -> list of every-day returns, for comparison
    exits: list = field(default_factory=list)  # sell calls: price change over the horizon, in percent
    open_exits: int = 0  # sell calls too recent to settle
    universe: dict = field(default_factory=dict)  # symbol -> PriceSeries, for the random buys


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
        replay.universe[series.symbol] = series
        for i in _days(series, start, end):
            replay.bars += 1
            t = time.perf_counter()
            analysis = analyze(window(series, i), config, [timed])
            replay.analysis_seconds += time.perf_counter() - t
            if not analysis:
                continue
            for signal in analysis.signals:
                _settle(replay, series, i, draft(signal, closes[i]))
        # Every-day returns over the horizons this strategy uses: what simply buying would have done.
        for i in _days(series, start, end):
            if i + horizon < len(closes) and closes[i]:
                replay.baseline[horizon].append((closes[i + horizon] / closes[i] - 1) * 100)
    replay.strategy_seconds += clock[0]
    return replay


CROSS_WINDOW = 200  # sessions per stock each replayed day of a cross-sectional strategy sees (they look back 120)


def replay_cross_section(series_by_symbol, name, scan, start=None, end=None, window_size=CROSS_WINDOW, progress=None) -> Replay:
    """Walk forward over the trading days and settle every call a cross-sectional strategy makes.

    ``scan`` takes {symbol: PriceSeries as of that day} and returns [(symbol, Signal)], like the
    live run does over every stock that traded that day; only signals named ``name`` count.
    ``progress(done, total)`` is called after each day.
    """
    horizon = HORIZONS.get(name, DEFAULT_HORIZON)
    replay = Replay(trades=[], baseline={horizon: []}, universe=dict(series_by_symbol))
    days = sorted({d for s in series_by_symbol.values() for d in s.dates if (not start or d >= start) and (not end or d <= end)})
    for n, day in enumerate(days, 1):
        windows, at = {}, {}
        for symbol, s in series_by_symbol.items():
            i = bisect.bisect_right(s.dates, day) - 1
            if i >= 0 and s.dates[i] == day:  # only stocks that traded that day, like a live run
                windows[symbol], at[symbol] = window(s, i, window_size), i
        replay.bars += len(windows)
        t = time.perf_counter()
        found = [(symbol, signal) for symbol, signal in scan(windows) if signal.strategy == name]
        spent = time.perf_counter() - t
        replay.analysis_seconds += spent
        replay.strategy_seconds += spent
        for symbol, signal in found:
            s, i = series_by_symbol[symbol], at[symbol]
            _settle(replay, s, i, draft(signal, s.closes[i]))
        if progress:
            progress(n, len(days))
    for s in series_by_symbol.values():
        for i, d in enumerate(s.dates):
            if (not start or d >= start) and (not end or d <= end) and i + horizon < len(s.closes) and s.closes[i]:
                replay.baseline[horizon].append((s.closes[i + horizon] / s.closes[i] - 1) * 100)
    return replay


def _settle(replay, series, i, d):
    """Score draft ``d`` made at the close of bar ``i`` against the bars after it, and add it to ``replay``."""
    if d is None:
        return
    closes = series.closes
    if d.direction != "bullish":
        # NEPSE can't be sold short: a sell call is an exit warning, scored by whether the price fell.
        if i + d.horizon < len(closes) and closes[i]:
            replay.exits.append((closes[i + d.horizon] / closes[i] - 1) * 100)
        else:
            replay.open_exits += 1
        return
    stop_pct = d.stop_price / d.entry_price - 1 if d.stop_price else None
    target_pct = d.target_price / d.entry_price - 1 if d.target_price else None
    result = simulate_long(series, i, stop_pct, target_pct, d.horizon)
    if result is None:
        replay.open_calls += 1
        return
    outcome, j, exit_price, entry, stop, target = result
    change = round((exit_price / entry - 1) * 100, 3)
    replay.trades.append(Trade(
        series.symbol, series.dates[i], d.direction, round(entry, 2), _round(target), _round(stop), d.horizon,
        outcome, series.dates[j], round(exit_price, 2), j - i, change, change, change > 0,
        closes[i + d.horizon] if i + d.horizon < len(closes) else None, closes[i],
    ))


def simulate_long(series, i, stop_pct, target_pct, horizon):
    """Buy at the open after bar ``i`` and hold up to ``horizon`` sessions, with a stop and target
    ``stop_pct`` / ``target_pct`` (fractions, or None) away from the entry.

    Returns (outcome, exit bar, exit price, entry, stop, target), or None until enough bars exist.
    A session that opens beyond the stop or target exits at its open; when one session's range
    touches both, the stop counts (we can't tell which came first).
    """
    first = i + 1
    if first + horizon > len(series.closes):
        return None
    entry = series.opens[first] or series.closes[i]
    stop = entry * (1 + stop_pct) if stop_pct is not None else None
    target = entry * (1 + target_pct) if target_pct is not None else None
    for j in range(first, first + horizon):
        if j > first:  # the entry session opens at the entry price
            o = series.opens[j]
            if o and stop is not None and o <= stop:
                return "stop", j, o, entry, stop, target
            if o and target is not None and o >= target:
                return "target", j, o, entry, stop, target
        if stop is not None and series.lows[j] <= stop:
            return "stop", j, stop, entry, stop, target
        if target is not None and series.highs[j] >= target:
            return "target", j, target, entry, stop, target
    j = first + horizon - 1
    return "horizon", j, series.closes[j], entry, stop, target


def random_buys(trades, universe, runs=RANDOM_RUNS, costs=COSTS, seed=11):
    """The strategy's buys redone ``runs`` times with random stocks, under the same stop, target and
    horizon rules. Returns (average net returns, one per run; hit rate of all random buys), or None
    when there is nothing to compare with.

    Each run swaps every stock the strategy bought for one random stock, kept for all of that
    stock's calls. Calls on one stock a few days apart share most of their future, and calls on one
    day share the market's move; random buys with the same structure have the same luck, so the
    comparison doesn't flatter a strategy that keeps buying the same stock.
    """
    if not trades or not universe:
        return None
    by_day, index = {}, {}
    for symbol, s in universe.items():
        index[symbol] = {d: i for i, d in enumerate(s.dates)}
        for i, d in enumerate(s.dates):
            by_day.setdefault(d, []).append((s, i))
    plans = []
    for t in trades:
        stop_pct = t.stop / t.entry - 1 if t.stop else None
        target_pct = t.target / t.entry - 1 if t.target else None
        if by_day.get(t.made_on):
            plans.append((t.symbol, t.made_on, stop_pct, target_pct, t.horizon))
    if not plans:
        return None
    symbols = sorted(universe)
    rng, means, wins, total = random.Random(seed), [], 0, 0
    for _ in range(runs):
        swap, nets = {}, []
        for symbol, day, stop_pct, target_pct, horizon in plans:
            other = swap.setdefault(symbol, rng.choice(symbols))
            i = index[other].get(day)
            result = simulate_long(universe[other], i, stop_pct, target_pct, horizon) if i is not None else None
            for _attempt in range(5):  # that stock didn't trade that day, or is too near the end of its history
                if result:
                    break
                s, i = rng.choice(by_day[day])
                result = simulate_long(s, i, stop_pct, target_pct, horizon)
            if result:
                _, _, exit_price, entry, _, _ = result
                net = costs.net_return_pct((exit_price / entry - 1) * 100)
                nets.append(net)
                wins += net > 0
                total += 1
        if nets:
            means.append(statistics.fmean(nets))
    return (means, wins / total * 100) if means else None


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


def permutation_p_value(actual, random_means):
    """Two-sided p-value that an average return of ``actual`` came from the same luck as ``random_means``."""
    if not random_means:
        return None
    n = len(random_means)
    above = sum(m >= actual for m in random_means)
    below = sum(m <= actual for m in random_means)
    return round(min(1.0, 2 * (min(above, below) + 1) / (n + 1)), 4)


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
    """Share of days the price rose, and the average return, for each horizon.

    The up rate is smoothed (one imagined up day and one down day), so a short history that only
    ever rose doesn't make chance a certainty, which would leave no p-value to compute.
    """
    out = {}
    for h, returns in baseline.items():
        if returns:
            out[h] = {"up_rate": (sum(r > 0 for r in returns) + 1) / (len(returns) + 2), "avg_return": sum(returns) / len(returns),
                      "samples": len(returns)}
    return out


def metrics(replay: Replay, start=None, end=None, costs=COSTS, random_runs=RANDOM_RUNS) -> dict:
    trades = sorted(replay.trades, key=lambda t: (t.exit_date, t.symbol))
    n = len(trades)
    gross = [t.edge_pct for t in trades]
    edges = [costs.net_return_pct(e) for e in gross]  # what an investor keeps
    hits = sum(e > 0 for e in edges)
    wins = [e for e in edges if e > 0]
    losses = [e for e in edges if e <= 0]
    base = _baseline_rates(replay.baseline or {})

    low, high = wilson_interval(hits, n)
    mean = statistics.fmean(edges) if edges else None
    std = statistics.pstdev(edges) if n > 1 else None
    downside = math.sqrt(sum(min(e, 0) ** 2 for e in edges) / n) if n else None
    avg_sessions = statistics.fmean(t.sessions for t in trades) if trades else None
    per_year = TRADING_DAYS / avg_sessions if avg_sessions else None

    randoms = random_buys(trades, replay.universe, random_runs, costs)
    random_means, random_hit_rate = randoms or (None, None)
    random_avg = statistics.fmean(random_means) if random_means else None

    forecasts = [(t.target, t.close_at_horizon) for t in trades if t.target and t.close_at_horizon]
    errors = [(actual - target) / target * 100 for target, actual in forecasts]
    with_target = [t for t in trades if t.target]

    curve = equity_curve(edges)
    years = None
    if trades and start and end:
        years = max((end - start).days / 365.25, 1 / 365.25)
    base_avg = None
    if trades:
        weights = [base[t.horizon]["avg_return"] for t in trades if t.horizon in base]
        base_avg = statistics.fmean(weights) if weights else None
    exits = replay.exits
    fell_base = [1 - base[h]["up_rate"] for h in base]

    return {
        "calls": n + replay.open_calls,
        "settled": n,
        "open": replay.open_calls,
        "bullish": n,
        "bearish": len(exits),
        "costs": {**asdict(costs), "round_trip_pct": _round(-costs.net_return_pct(0), 3)},
        "accuracy": {
            "hit_rate": _pct(hits, n),
            "hit_rate_ci95": [low, high],
            "chance_hit_rate": _round(random_hit_rate, 1),
            "p_value": permutation_p_value(mean, random_means) if mean is not None else None,
            "random_runs": len(random_means or []),
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
            "avg_gross_return_pct": _round(statistics.fmean(gross)) if gross else None,
            "median_return_pct": _round(statistics.median(edges)) if edges else None,
            "avg_win_pct": _round(statistics.fmean(wins)) if wins else None,
            "avg_loss_pct": _round(statistics.fmean(losses)) if losses else None,
            "win_loss_ratio": _round(statistics.fmean(wins) / abs(statistics.fmean(losses))) if wins and losses and statistics.fmean(losses) else None,
            # None when there were no losing calls (it would be infinite); 0 when there were no winners.
            "profit_factor": _round(sum(wins) / abs(sum(losses))) if losses and sum(losses) else (0.0 if n and not wins else None),
            "gross_profit_factor": _profit_factor(gross),
            "random_avg_return_pct": _round(random_avg),
            "edge_vs_random_pct": _round(mean - random_avg) if mean is not None and random_avg is not None else None,
            "baseline_avg_return_pct": _round(base_avg),
            "sharpe": _round(mean / std * math.sqrt(per_year)) if std and per_year else None,
            "sortino": _round(mean / downside * math.sqrt(per_year)) if downside and per_year else None,
        },
        "exit_warnings": {
            "calls": len(exits) + replay.open_exits,
            "settled": len(exits),
            "fell_pct": _pct(sum(e < 0 for e in exits), len(exits)),
            "chance_fell_pct": _round(statistics.fmean(fell_base) * 100, 1) if fell_base else None,
            "avg_move_pct": _round(statistics.fmean(exits)) if exits else None,
        },
        "risk": {
            "stake_per_trade_pct": round(100 / MAX_OPEN),
            "total_return_pct": _round((curve[-1] - 1) * 100) if n else None,
            "cagr_pct": _round((curve[-1] ** (1 / years) - 1) * 100) if years and curve[-1] > 0 else None,
            "max_drawdown_pct": max_drawdown(curve) if n else None,
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


def _profit_factor(edges):
    wins, losses = sum(e for e in edges if e > 0), -sum(e for e in edges if e <= 0)
    return _round(wins / losses) if losses else (0.0 if edges and not wins else None)


def _streak(edges):
    best = run = 0
    for e in edges:
        run = run + 1 if e <= 0 else 0
        best = max(best, run)
    return best


def trade_rows(replay: Replay, limit=50, costs=COSTS):
    """The most recent settled buy trades, for a sample table."""
    rows = sorted(replay.trades, key=lambda t: t.made_on, reverse=True)[:limit]
    return [{**asdict(t), "made_on": t.made_on.isoformat(), "exit_date": t.exit_date.isoformat(),
             "net_pct": _round(costs.net_return_pct(t.edge_pct))} for t in rows]
