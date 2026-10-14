"""Statistical arbitrage through mean reversion: pairs trading and basket mean reversion.

Two price series that move together (cointegrated) keep a stable spread
``log(A) - beta * log(B)``. When the spread stretches far from its mean (a large z-score)
it tends to snap back, so the stock that ran ahead is expected to lag and the one left
behind to catch up. A basket is the same idea with B being the equal-weighted average of
the stock's sector (or the whole market when sectors are unknown).

NEPSE has no short selling, so a "rich" leg is reported as bearish (avoid / take profit)
and the "cheap" leg as bullish (buy candidate). Pure Python.
"""
import math
from dataclasses import dataclass

from .entities import Direction, Signal

LOOKBACK = 120  # sessions used to fit the hedge ratio and spread statistics
ENTRY_Z = 2.0  # spread this many standard deviations from its mean triggers a signal
STOP_Z = 3.5  # spread stretched this far means the relationship has likely broken
ADF_CRITICAL = -3.34  # Engle-Granger 5% critical value for two series
MAX_HALF_LIFE = 30  # sessions; slower reversion is not worth trading
MIN_CORRELATION = 0.5  # of daily log returns
STRATEGY_PAIRS = "pairs"
STRATEGY_BASKET = "basket_reversion"


@dataclass(frozen=True)
class SpreadFit:
    beta: float
    alpha: float
    mean: float
    std: float
    z: float
    adf_t: float
    half_life: float
    correlation: float

    @property
    def mean_reverting(self):
        return (
            self.adf_t < ADF_CRITICAL
            and 0 < self.half_life <= MAX_HALF_LIFE
            and self.correlation >= MIN_CORRELATION
            and self.std > 0
        )


def ols(xs, ys):
    """Least-squares fit y = alpha + beta * x. Returns (alpha, beta, residuals, beta_standard_error)."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return my, 0.0, [y - my for y in ys], math.inf
    beta = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    alpha = my - beta * mx
    residuals = [y - alpha - beta * x for x, y in zip(xs, ys)]
    dof = n - 2
    se = math.sqrt(sum(r * r for r in residuals) / dof / sxx) if dof > 0 else math.inf
    return alpha, beta, residuals, se


def adf_t_stat(series):
    """Dickey-Fuller t-statistic (no lags) for ``series``: very negative means it reverts to its mean."""
    lagged = series[:-1]
    diffs = [b - a for a, b in zip(series[:-1], series[1:])]
    _, gamma, _, se = ols(lagged, diffs)
    return gamma / se if se and math.isfinite(se) else 0.0


def half_life(series):
    """Sessions for a deviation to halve, from an AR(1) fit of the spread's changes."""
    lagged = series[:-1]
    diffs = [b - a for a, b in zip(series[:-1], series[1:])]
    _, gamma, _, _ = ols(lagged, diffs)
    if gamma >= 0:
        return math.inf
    return -math.log(2) / math.log(1 + gamma) if gamma > -1 else 0.5


def _returns(logs):
    return [b - a for a, b in zip(logs[:-1], logs[1:])]


def correlation(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    return cov / math.sqrt(vx * vy) if vx and vy else 0.0


def fit_spread(a_closes, b_closes, lookback=LOOKBACK) -> SpreadFit | None:
    """Fit log(A) = alpha + beta * log(B) over the last ``lookback`` aligned closes."""
    if len(a_closes) < lookback or len(b_closes) < lookback:
        return None
    a = [math.log(p) for p in a_closes[-lookback:]]
    b = [math.log(p) for p in b_closes[-lookback:]]
    alpha, beta, spread, _ = ols(b, a)
    if beta <= 0:
        return None
    n = len(spread)
    mean = sum(spread) / n
    std = math.sqrt(sum((s - mean) ** 2 for s in spread) / (n - 1))
    return SpreadFit(
        beta=beta,
        alpha=alpha,
        mean=mean,
        std=std,
        z=(spread[-1] - mean) / std if std else 0.0,
        adf_t=adf_t_stat(spread),
        half_life=half_life(spread),
        correlation=correlation(_returns(a), _returns(b)),
    )


def _strength(z):
    return 3 if abs(z) >= 3 else 2


def _levels(price, fit):
    """Price at which the spread is back at its mean (target) and stretched to STOP_Z (stop), other leg unchanged."""
    deviation = fit.z * fit.std
    target = price * math.exp(-deviation)
    stop = price * math.exp(math.copysign(STOP_Z, fit.z) * fit.std - deviation)
    return round(target, 1), round(stop, 1)


def _values(fit, price, peer):
    target, stop = _levels(price, fit)
    return {
        "z": round(fit.z, 2),
        "beta": round(fit.beta, 3),
        "half_life": round(fit.half_life, 1),
        "adf_t": round(fit.adf_t, 2),
        "peer": peer,
        "target": target,
        "stop": stop,
    }


def pair_signals(sym_a, a_closes, sym_b, b_closes, entry_z=ENTRY_Z):
    """Signals for both legs of a pair whose spread is stretched. Yields (symbol, Signal)."""
    fit = fit_spread(a_closes, b_closes)
    if fit is None or not fit.mean_reverting or abs(fit.z) < entry_z or abs(fit.z) >= STOP_Z:
        return
    rich, cheap = (sym_a, sym_b) if fit.z > 0 else (sym_b, sym_a)
    note = f"z {abs(fit.z):.1f}, half-life {fit.half_life:.0f} sessions"
    # The fit is A on B, so A's levels come from it directly; B's from the mirrored deviation.
    a_vals = _values(fit, a_closes[-1], sym_b)
    mirrored = SpreadFit(1 / fit.beta, 0, 0, fit.std / fit.beta, -fit.z, fit.adf_t, fit.half_life, fit.correlation)
    b_vals = _values(mirrored, b_closes[-1], sym_a)
    vals = {sym_a: a_vals, sym_b: b_vals}
    yield rich, Signal(STRATEGY_PAIRS, Direction.BEARISH, _strength(fit.z),
                       f"Pairs: expensive versus {cheap} ({note}); expect it to lag as the gap closes", vals[rich])
    yield cheap, Signal(STRATEGY_PAIRS, Direction.BULLISH, _strength(fit.z),
                        f"Pairs: cheap versus {rich} ({note}); expect it to catch up as the gap closes", vals[cheap])


def basket_index(closes_by_symbol, members):
    """Equal-weighted index of ``members``: average of each member's price relative to its first close."""
    series = [closes_by_symbol[m] for m in members]
    length = min(len(s) for s in series)
    series = [s[-length:] for s in series]
    return [sum(s[i] / s[0] for s in series) / len(series) * 100 for i in range(length)]


def basket_signal(symbol, closes, index, basket_name, entry_z=ENTRY_Z):
    fit = fit_spread(closes, index)
    if fit is None or not fit.mean_reverting or abs(fit.z) < entry_z or abs(fit.z) >= STOP_Z:
        return None
    rich = fit.z > 0
    return Signal(
        STRATEGY_BASKET,
        Direction.BEARISH if rich else Direction.BULLISH,
        _strength(fit.z),
        f"Basket mean reversion: {'above' if rich else 'below'} its usual level versus the {basket_name} basket "
        f"(z {fit.z:+.1f}, half-life {fit.half_life:.0f} sessions); expect it to {'fall back' if rich else 'recover'}",
        _values(fit, closes[-1], basket_name),
    )


def align(dates_by_symbol, closes_by_symbol, symbols):
    """Closes of ``symbols`` restricted to the dates they all traded, oldest first."""
    common = set.intersection(*(set(dates_by_symbol[s]) for s in symbols))
    out = {}
    for s in symbols:
        out[s] = [c for d, c in zip(dates_by_symbol[s], closes_by_symbol[s]) if d in common]
    return out


def scan(dates_by_symbol, closes_by_symbol, groups, lookback=LOOKBACK, entry_z=ENTRY_Z):
    """Run pairs and basket mean reversion over every group of related symbols.

    ``groups`` maps a group name (a sector, or "market") to its symbols. Pairs are only
    formed inside a group. Returns a list of (symbol, Signal).
    """
    pairs, results = {}, []
    for name, members in groups.items():
        members = sorted(m for m in members if len(closes_by_symbol.get(m, [])) >= lookback)
        if len(members) < 2:
            continue
        aligned = align(dates_by_symbol, closes_by_symbol, members)
        if len(aligned[members[0]]) < lookback:
            continue
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                for symbol, signal in pair_signals(a, aligned[a], b, aligned[b], entry_z):
                    # A stock can sit in many stretched pairs; keep only its most stretched one.
                    if symbol not in pairs or abs(signal.values["z"]) > abs(pairs[symbol].values["z"]):
                        pairs[symbol] = signal
        if len(members) >= 3:
            for m in members:
                peers = [p for p in members if p != m]
                index = basket_index(aligned, peers)
                signal = basket_signal(m, aligned[m], index, name, entry_z)
                if signal:
                    results.append((m, signal))
    return sorted(pairs.items()) + results
