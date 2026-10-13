"""Known strategies. Each takes the computed context and returns zero or more Signals.

Thresholds are the textbook defaults; they live in ``StrategyConfig`` so they can be
tuned per deployment without touching the rules.
"""
from dataclasses import dataclass

from . import indicators as ind
from .entities import Direction, Signal


@dataclass(frozen=True)
class StrategyConfig:
    rsi_overbought: float = 70
    rsi_oversold: float = 30
    volume_spike_ratio: float = 2.0
    breakout_volume_ratio: float = 1.5
    trades_spike_ratio: float = 2.0
    min_forecast_r2: float = 0.6
    min_forecast_slope_pct: float = 0.3


@dataclass(frozen=True)
class Context:
    """Everything a strategy might need, computed once per symbol."""

    series: object  # PriceSeries
    sma20: list
    sma50: list
    sma200: list
    rsi14: list
    macd: list
    macd_signal: list
    avg_volume20: float | None
    avg_trades20: float | None
    support: object  # Level | None
    resistance: object
    prev_support: object  # levels computed as of yesterday, for breakouts
    prev_resistance: object
    forecast: object
    config: StrategyConfig


def trend(ctx):
    """Golden/death cross of the 50- and 200-day averages."""
    if ind.crossed_above(ctx.sma50, ctx.sma200):
        yield Signal("trend", Direction.BULLISH, 3, "Golden cross: 50-day average crossed above the 200-day",
                     {"sma50": ctx.sma50[-1], "sma200": ctx.sma200[-1]})
    elif ind.crossed_below(ctx.sma50, ctx.sma200):
        yield Signal("trend", Direction.BEARISH, 3, "Death cross: 50-day average crossed below the 200-day",
                     {"sma50": ctx.sma50[-1], "sma200": ctx.sma200[-1]})


def moving_average_cross(ctx):
    """Price crossing its 50-day average, a medium-term trend change."""
    closes = ctx.series.closes
    if ind.crossed_above(closes, ctx.sma50):
        yield Signal("ma_cross", Direction.BULLISH, 2, "Price closed above its 50-day average", {"close": closes[-1], "sma50": ctx.sma50[-1]})
    elif ind.crossed_below(closes, ctx.sma50):
        yield Signal("ma_cross", Direction.BEARISH, 2, "Price closed below its 50-day average", {"close": closes[-1], "sma50": ctx.sma50[-1]})


def rsi_momentum(ctx):
    cfg, value = ctx.config, ctx.rsi14[-1]
    if value is None:
        return
    previous = ctx.rsi14[-2] if len(ctx.rsi14) > 1 else None
    if value >= cfg.rsi_overbought:
        yield Signal("rsi", Direction.BEARISH, 1, f"RSI {value:.0f}: overbought, momentum may fade", {"rsi14": value})
    elif value <= cfg.rsi_oversold:
        yield Signal("rsi", Direction.BULLISH, 1, f"RSI {value:.0f}: oversold, a rebound is possible", {"rsi14": value})
    elif previous is not None and previous <= cfg.rsi_oversold < value:
        yield Signal("rsi", Direction.BULLISH, 2, f"RSI recovered above {cfg.rsi_oversold:.0f} from oversold", {"rsi14": value})
    elif previous is not None and previous >= cfg.rsi_overbought > value:
        yield Signal("rsi", Direction.BEARISH, 2, f"RSI fell below {cfg.rsi_overbought:.0f} from overbought", {"rsi14": value})


def macd_momentum(ctx):
    if ind.crossed_above(ctx.macd, ctx.macd_signal):
        yield Signal("macd", Direction.BULLISH, 2, "MACD crossed above its signal line", {"macd": ctx.macd[-1], "signal": ctx.macd_signal[-1]})
    elif ind.crossed_below(ctx.macd, ctx.macd_signal):
        yield Signal("macd", Direction.BEARISH, 2, "MACD crossed below its signal line", {"macd": ctx.macd[-1], "signal": ctx.macd_signal[-1]})


def breakout(ctx):
    """Close through yesterday's resistance (or support), confirmed by volume."""
    closes, volumes, cfg = ctx.series.closes, ctx.series.volumes, ctx.config
    if len(closes) < 2 or not ctx.avg_volume20:
        return
    close, prev_close, ratio = closes[-1], closes[-2], volumes[-1] / ctx.avg_volume20
    confirmed = ratio >= cfg.breakout_volume_ratio
    r, s = ctx.prev_resistance, ctx.prev_support
    if r and prev_close <= r.price < close:
        yield Signal("breakout", Direction.BULLISH, 3 if confirmed else 1,
                     f"Broke above resistance {r.price:g}" + (f" on {ratio:.1f}x average volume" if confirmed else " on light volume"),
                     {"level": r.price, "close": close, "volume_ratio": round(ratio, 2)})
    elif s and prev_close >= s.price > close:
        yield Signal("breakout", Direction.BEARISH, 3 if confirmed else 1,
                     f"Broke below support {s.price:g}" + (f" on {ratio:.1f}x average volume" if confirmed else " on light volume"),
                     {"level": s.price, "close": close, "volume_ratio": round(ratio, 2)})


def volume_spike(ctx):
    """Unusual volume or number of transactions versus the 20-day average."""
    s, cfg = ctx.series, ctx.config
    direction = Direction.NEUTRAL
    if len(s.closes) >= 2:
        direction = Direction.BULLISH if s.closes[-1] > s.closes[-2] else Direction.BEARISH if s.closes[-1] < s.closes[-2] else Direction.NEUTRAL
    if ctx.avg_volume20 and s.volumes[-1] >= cfg.volume_spike_ratio * ctx.avg_volume20:
        ratio = s.volumes[-1] / ctx.avg_volume20
        yield Signal("volume", direction, 2, f"Volume {ratio:.1f}x the 20-day average",
                     {"volume": s.volumes[-1], "avg_volume20": round(ctx.avg_volume20), "ratio": round(ratio, 2)})
    if ctx.avg_trades20 and s.trades[-1] and s.trades[-1] >= cfg.trades_spike_ratio * ctx.avg_trades20:
        ratio = s.trades[-1] / ctx.avg_trades20
        yield Signal("transactions", direction, 1, f"Transactions {ratio:.1f}x the 20-day average",
                     {"trades": s.trades[-1], "avg_trades20": round(ctx.avg_trades20), "ratio": round(ratio, 2)})


def trend_projection(ctx):
    f, cfg = ctx.forecast, ctx.config
    if not f or f.r_squared < cfg.min_forecast_r2 or abs(f.slope_pct_per_day) < cfg.min_forecast_slope_pct:
        return
    direction = Direction.BULLISH if f.slope_per_day > 0 else Direction.BEARISH
    yield Signal("forecast", direction, 1,
                 f"Steady {'up' if f.slope_per_day > 0 else 'down'}trend ({f.slope_pct_per_day:+.2f}%/day, fit {f.r_squared:.2f}); "
                 f"projects about {f.projected_close:g} in {f.horizon_days} sessions if it continues",
                 {"projected_close": f.projected_close, "r_squared": f.r_squared})


STRATEGIES = [trend, moving_average_cross, rsi_momentum, macd_momentum, breakout, volume_spike, trend_projection]
