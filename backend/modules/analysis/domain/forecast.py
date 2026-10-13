"""Simple trend projection: least-squares line through recent closes.

This is a description of the recent trend extended forward, not a prediction
model. ``r_squared`` says how well a straight line fits; low values mean the
projection is not meaningful.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Forecast:
    horizon_days: int
    projected_close: float
    slope_per_day: float
    slope_pct_per_day: float
    r_squared: float
    lookback: int


def linear_trend(closes, lookback=20, horizon=5):
    ys = closes[-lookback:]
    n = len(ys)
    if n < lookback:
        return None
    xs = range(n)
    mean_x, mean_y = (n - 1) / 2, sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    r2 = 1 - ss_res / ss_tot if ss_tot else 1.0
    return Forecast(
        horizon_days=horizon,
        projected_close=round(intercept + slope * (n - 1 + horizon), 2),
        slope_per_day=round(slope, 4),
        slope_pct_per_day=round(slope / ys[-1] * 100, 3) if ys[-1] else 0.0,
        r_squared=round(r2, 3),
        lookback=lookback,
    )
