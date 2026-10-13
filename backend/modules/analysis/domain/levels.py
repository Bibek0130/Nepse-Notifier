"""Support and resistance from swing highs and lows."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Level:
    price: float
    touches: int
    kind: str  # "support" or "resistance"


def swing_points(highs, lows, window=3):
    """Indices of local maxima in ``highs`` and minima in ``lows`` (``window`` bars each side)."""
    peaks, troughs = [], []
    for i in range(window, len(highs) - window):
        if highs[i] == max(highs[i - window : i + window + 1]):
            peaks.append(i)
        if lows[i] == min(lows[i - window : i + window + 1]):
            troughs.append(i)
    return peaks, troughs


def cluster(prices, tolerance_pct):
    """Group nearby prices; returns [(average_price, count)], strongest first."""
    groups = []
    for price in sorted(prices):
        if groups and abs(price - groups[-1][-1]) / groups[-1][-1] * 100 <= tolerance_pct:
            groups[-1].append(price)
        else:
            groups.append([price])
    return sorted(((sum(g) / len(g), len(g)) for g in groups), key=lambda x: -x[1])


def find_levels(highs, lows, close, lookback=120, window=3, tolerance_pct=1.5):
    """Nearest support below and resistance above ``close``, from the last ``lookback`` bars.

    Swing highs and lows both count as levels (old resistance can become support).
    Returns (support, resistance); either may be None.
    """
    highs, lows = highs[-lookback:], lows[-lookback:]
    peaks, troughs = swing_points(highs, lows, window)
    candidates = [highs[i] for i in peaks] + [lows[i] for i in troughs]
    levels = cluster(candidates, tolerance_pct)

    below = [(p, n) for p, n in levels if p < close]
    above = [(p, n) for p, n in levels if p > close]
    support = max(below, key=lambda x: x[0], default=None)
    resistance = min(above, key=lambda x: x[0], default=None)
    return (
        Level(round(support[0], 2), support[1], "support") if support else None,
        Level(round(resistance[0], 2), resistance[1], "resistance") if resistance else None,
    )
