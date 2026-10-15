"""Turn signals into measurable predictions, and score them against what the price did next.

Every directional signal from an end-of-day run is a prediction: from the closing price,
the stock should move the signalled way within ``horizon`` sessions. Where the strategy
names a target or stop (5-8-13 EMA, pairs, basket, forecast), the first one touched
settles it early. Otherwise it is settled on the close ``horizon`` sessions later.
Pure Python.
"""
from dataclasses import dataclass

DEFAULT_HORIZON = 10  # sessions
HORIZONS = {"forecast": 5, "quant_momentum": 20, "quant_reversion": 20}  # 1:4.5 targets need room


@dataclass(frozen=True)
class Draft:
    strategy: str
    direction: str  # "bullish" or "bearish"
    strength: int
    entry_price: float
    target_price: float | None
    stop_price: float | None
    horizon: int


@dataclass(frozen=True)
class Score:
    outcome: str  # "target", "stop" or "horizon"
    exit_date: object  # date
    exit_price: float
    sessions: int
    return_pct: float  # raw price change from entry to exit
    correct: bool  # price moved the predicted way


def _sane(level, entry, above):
    """Keep a target/stop only if it sits on the expected side of the entry."""
    if level is None:
        return None
    level = float(level)
    return level if (level > entry if above else level < entry) else None


def draft(signal, close) -> Draft | None:
    """A prediction for ``signal`` (a domain Signal or a dict with the same keys), or None if it has no direction."""
    get = signal.get if isinstance(signal, dict) else lambda k: getattr(signal, k)
    direction = str(getattr(get("direction"), "value", get("direction")))
    if direction not in ("bullish", "bearish") or not close:
        return None
    values = get("values") or {}
    bullish = direction == "bullish"
    target = values.get("target", values.get("projected_close"))
    stop = values.get("stop", values.get("recent_high"))
    return Draft(
        strategy=get("strategy"),
        direction=direction,
        strength=get("strength"),
        entry_price=float(close),
        target_price=_sane(target, close, above=bullish),
        stop_price=_sane(stop, close, above=not bullish),
        horizon=HORIZONS.get(get("strategy"), DEFAULT_HORIZON),
    )


def score(direction, entry, target, stop, horizon, bars) -> Score | None:
    """Settle a prediction from the daily ``bars`` after it was made: [(date, high, low, close)], oldest first.

    Returns None while it is still open (no target or stop touched and fewer than ``horizon`` bars).
    When a bar touches both target and stop, the stop counts (we can't tell which came first).
    """
    bullish = direction == "bullish"

    def settle(outcome, i, price):
        change = (price - entry) / entry * 100
        correct = change > 0 if bullish else change < 0
        return Score(outcome, bars[i][0], round(price, 2), i + 1, round(change, 2), correct)

    for i, (_, high, low, close) in enumerate(bars[:horizon]):
        stop_hit = stop is not None and (low <= stop if bullish else high >= stop)
        target_hit = target is not None and (high >= target if bullish else low <= target)
        if stop_hit:
            return settle("stop", i, stop)
        if target_hit:
            return settle("target", i, target)
    if len(bars) >= horizon:
        return settle("horizon", horizon - 1, bars[horizon - 1][3])
    return None


@dataclass
class StrategyRecord:
    strategy: str
    predictions: int = 0
    open: int = 0
    settled: int = 0
    correct: int = 0
    targets: int = 0
    stops: int = 0
    total_edge: float = 0.0  # sum of returns in the predicted direction

    @property
    def hit_rate(self):
        return round(self.correct / self.settled * 100, 1) if self.settled else None

    @property
    def avg_edge(self):
        return round(self.total_edge / self.settled, 2) if self.settled else None

    def as_dict(self):
        return {
            "strategy": self.strategy, "predictions": self.predictions, "open": self.open, "settled": self.settled,
            "correct": self.correct, "hit_rate": self.hit_rate, "avg_return": self.avg_edge,
            "targets_hit": self.targets, "stops_hit": self.stops,
        }


def summarize(rows):
    """Track record per strategy from prediction rows: dicts with strategy, direction, outcome, return_pct, correct."""
    records = {}
    for r in rows:
        rec = records.setdefault(r["strategy"], StrategyRecord(r["strategy"]))
        rec.predictions += 1
        if not r["outcome"]:
            rec.open += 1
            continue
        rec.settled += 1
        rec.correct += bool(r["correct"])
        rec.targets += r["outcome"] == "target"
        rec.stops += r["outcome"] == "stop"
        rec.total_edge += r["return_pct"] if r["direction"] == "bullish" else -r["return_pct"]
    return sorted(
        (rec.as_dict() for rec in records.values()),
        key=lambda d: (d["hit_rate"] is None, -(d["hit_rate"] or 0), d["strategy"]),
    )
