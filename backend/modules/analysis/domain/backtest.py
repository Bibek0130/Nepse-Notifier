"""Replay the strategies over history and measure what happened after each signal.

Walk-forward: on each past day the engine sees only bars up to that day, exactly as
the live pipeline would have. For every signal we record the close-to-close return
over the next N trading days. Pure Python.
"""
from dataclasses import dataclass, field

from .engine import MIN_BARS, analyze
from .entities import Direction, PriceSeries
from .strategies import STRATEGIES, StrategyConfig

HORIZONS = (5, 10, 20)
WINDOW = 260  # bars the engine sees per day: enough for the 200-day average, and keeps replay fast


@dataclass(frozen=True)
class Outcome:
    symbol: str
    trading_date: object  # date
    strategy: str
    direction: str
    strength: int
    returns: dict  # {horizon: percent return, or None when the future isn't known yet}


@dataclass
class HorizonStats:
    horizon: int
    samples: int = 0
    avg_return: float | None = None
    hit_rate: float | None = None  # share of signals where price moved the signalled way


@dataclass
class StrategyStats:
    strategy: str
    direction: str
    signals: int
    horizons: list[HorizonStats] = field(default_factory=list)


def window(series: PriceSeries, end: int, size: int = WINDOW) -> PriceSeries:
    """The series as it looked at the close of bar ``end`` (inclusive), last ``size`` bars."""
    start = max(0, end + 1 - size)
    s = slice(start, end + 1)
    return PriceSeries(
        symbol=series.symbol,
        dates=series.dates[s],
        opens=series.opens[s],
        highs=series.highs[s],
        lows=series.lows[s],
        closes=series.closes[s],
        volumes=series.volumes[s],
        trades=series.trades[s],
    )


def forward_returns(closes, i, horizons=HORIZONS):
    base = closes[i]
    return {h: round((closes[i + h] / base - 1) * 100, 3) if i + h < len(closes) and base else None for h in horizons}


def _days(series, start_date, end_date):
    """Indexes of the bars to evaluate. Bars after ``end_date`` are only used to measure returns."""
    for i in range(MIN_BARS - 1, len(series)):
        d = series.dates[i]
        if (start_date and d < start_date) or (end_date and d > end_date):
            continue
        yield i


def replay(series: PriceSeries, start_date=None, end_date=None, config=StrategyConfig(), strategies=STRATEGIES, horizons=HORIZONS) -> list[Outcome]:
    outcomes = []
    for i in _days(series, start_date, end_date):
        analysis = analyze(window(series, i), config, strategies)
        if not analysis or not analysis.signals:
            continue
        returns = forward_returns(series.closes, i, horizons)
        outcomes.extend(
            Outcome(series.symbol, series.dates[i], s.strategy, str(s.direction), s.strength, returns) for s in analysis.signals
        )
    return outcomes


def baseline(series: PriceSeries, start_date=None, end_date=None, horizons=HORIZONS) -> dict:
    """Returns over every evaluated day, signal or not: what 'no strategy' would have earned."""
    out = {h: [] for h in horizons}
    for i in _days(series, start_date, end_date):
        for h, r in forward_returns(series.closes, i, horizons).items():
            if r is not None:
                out[h].append(r)
    return out


def _stats(direction, returns, horizon):
    known = [r for r in returns if r is not None]
    stats = HorizonStats(horizon=horizon, samples=len(known))
    if known:
        stats.avg_return = round(sum(known) / len(known), 3)
        if direction == Direction.BULLISH:
            stats.hit_rate = round(sum(r > 0 for r in known) / len(known), 3)
        elif direction == Direction.BEARISH:
            stats.hit_rate = round(sum(r < 0 for r in known) / len(known), 3)
    return stats


def summarize(outcomes: list[Outcome], horizons=HORIZONS, min_strength=1) -> list[StrategyStats]:
    groups = {}
    for o in outcomes:
        if o.strength >= min_strength:
            groups.setdefault((o.strategy, o.direction), []).append(o)
    result = []
    for (strategy, direction), items in sorted(groups.items()):
        result.append(StrategyStats(
            strategy=strategy,
            direction=direction,
            signals=len(items),
            horizons=[_stats(direction, [o.returns[h] for o in items], h) for h in horizons],
        ))
    return result


def summarize_baseline(per_horizon: dict) -> list[HorizonStats]:
    """Average return and share of up-moves across all evaluated days."""
    return [_stats(Direction.BULLISH, returns, h) for h, returns in sorted(per_horizon.items())]
