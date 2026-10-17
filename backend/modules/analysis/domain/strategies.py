"""Known strategies. Each takes the computed context and returns zero or more Signals.

Thresholds are the textbook defaults; they live in ``StrategyConfig`` so they can be
tuned per deployment without touching the rules.
"""
from dataclasses import dataclass

from . import indicators as ind
from . import nepsealpha, pca, stat_arb
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
    # Quant strategies from Poudel & Paudel (2025), tested on NEPSE. The paper does not
    # publish its entry thresholds; these follow its base case where it gives one.
    quant_trend_period: int = 240
    quant_z_window: int = 15
    quant_z_entry: float = -1.5
    quant_rsi_oversold: float = 35
    quant_rsi_momentum: float = 60
    quant_momentum_stop_pct: float = 4.0
    quant_reversion_stop_ma: int = 70
    quant_max_stop_pct: float = 8.0
    quant_reward_risk: float = 4.5
    quant_momentum_cooldown: int = 4
    quant_reversion_cooldown: int = 3


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
    ema5: list
    ema8: list
    ema13: list
    trend_ma: list  # quant regime filter (240-day average)
    stop_ma: list  # quant mean-reversion stop reference (70-day average)
    zscore: list  # close versus its 15-day mean, in standard deviations
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


def _ribbon(close, a, b, c, above):
    if None in (a, b, c):
        return False
    if above:
        return a > max(b, c) and close > max(a, b, c)
    return a < min(b, c) and close < min(a, b, c)


def ema_ribbon(ctx):
    """5-8-13 EMA strategy (switchmarkets.com): the 5 crosses above the 8 and 13 with price above all three.

    Stop goes under the recent swing low, target at 1:1 risk-reward. The bearish mirror
    (price and the 5 drop below the 8 and 13) is an exit signal, since NEPSE has no short selling.
    """
    s = ctx.series
    if len(s.closes) < 6:
        return
    now = [s.closes[-1], ctx.ema5[-1], ctx.ema8[-1], ctx.ema13[-1]]
    before = [s.closes[-2], ctx.ema5[-2], ctx.ema8[-2], ctx.ema13[-2]]
    close = s.closes[-1]
    values = {"ema5": now[1], "ema8": now[2], "ema13": now[3]}
    if _ribbon(*now, above=True) and not _ribbon(*before, above=True):
        stop = min(s.lows[-5:])
        target = close + (close - stop)
        yield Signal("ema_5_8_13", Direction.BULLISH, 2,
                     f"5-8-13 EMA buy: 5-day EMA crossed above the 8 and 13; stop {stop:g}, 1:1 target {target:.1f}",
                     {**values, "stop": stop, "target": round(target, 1)})
    elif _ribbon(*now, above=False) and not _ribbon(*before, above=False):
        stop = max(s.highs[-5:])
        yield Signal("ema_5_8_13", Direction.BEARISH, 2,
                     f"5-8-13 EMA exit: price and the 5-day EMA fell below the 8 and 13 (recent high {stop:g})",
                     {**values, "recent_high": stop})


def _fired_within(condition, days):
    """True if ``condition(offset)`` held on any of the ``days`` bars before the last one."""
    return any(condition(k) for k in range(1, days + 1))


def _quant_levels(close, stop, reward_risk):
    return round(stop, 2), round(close + reward_risk * (close - stop), 1)


def quant_momentum(ctx):
    """Momentum leg of Poudel & Paudel (2025): RSI breaks above 60 while price is above its 240-day average.

    Stop 4% under entry, target at 1:4.5 risk-reward, then a 4-day cooldown. A close
    back below the 240-day average is the exit (the paper moves to cash in downtrends).
    """
    s, cfg, closes = ctx.series, ctx.config, ctx.series.closes
    trend_now = ctx.trend_ma[-1]
    if trend_now is None or len(closes) < cfg.quant_momentum_cooldown + 2:
        return

    def crossed(k):  # RSI crossed the momentum level on bar -1-k, inside the uptrend
        i = len(closes) - 1 - k
        prev, cur, ma = ctx.rsi14[i - 1], ctx.rsi14[i], ctx.trend_ma[i]
        return None not in (prev, cur, ma) and prev <= cfg.quant_rsi_momentum < cur and closes[i] > ma

    if crossed(0) and not _fired_within(crossed, cfg.quant_momentum_cooldown):
        close = closes[-1]
        stop, target = _quant_levels(close, close * (1 - cfg.quant_momentum_stop_pct / 100), cfg.quant_reward_risk)
        yield Signal("quant_momentum", Direction.BULLISH, 2,
                     f"Quant momentum: RSI broke above {cfg.quant_rsi_momentum:g} with price above its "
                     f"{cfg.quant_trend_period}-day average; stop {stop:g}, 1:{cfg.quant_reward_risk:g} target {target:g}",
                     {"rsi14": ctx.rsi14[-1], "trend_ma": round(trend_now, 2), "stop": stop, "target": target})
    elif ind.crossed_below(closes, ctx.trend_ma):
        yield Signal("quant_momentum", Direction.BEARISH, 2,
                     f"Quant exit: price closed below its {cfg.quant_trend_period}-day average, the long-term trend turned down",
                     {"close": closes[-1], "trend_ma": round(trend_now, 2), "recent_high": max(s.highs[-5:])})


def quant_reversion(ctx):
    """Mean-reversion leg of Poudel & Paudel (2025): buy a panic dip inside a long-term uptrend.

    The close is stretched below its 15-day mean (z-score) and RSI is oversold, while price
    is still above the 240-day average. Stop at the 70-day average (at most 8% away, 4% if
    the average is above the price), target 1:4.5, then a 3-day cooldown.
    """
    cfg, closes = ctx.config, ctx.series.closes
    if ctx.trend_ma[-1] is None or len(closes) < cfg.quant_reversion_cooldown + 2:
        return

    def oversold(k):
        i = len(closes) - 1 - k
        z, r, ma = ctx.zscore[i], ctx.rsi14[i], ctx.trend_ma[i]
        return None not in (z, r, ma) and z <= cfg.quant_z_entry and r <= cfg.quant_rsi_oversold and closes[i] > ma

    if not oversold(0) or _fired_within(oversold, cfg.quant_reversion_cooldown):
        return
    close, stop_ma = closes[-1], ctx.stop_ma[-1]
    stop = stop_ma if stop_ma is not None and stop_ma < close else close * (1 - cfg.quant_momentum_stop_pct / 100)
    stop = max(stop, close * (1 - cfg.quant_max_stop_pct / 100))
    stop, target = _quant_levels(close, stop, cfg.quant_reward_risk)
    yield Signal("quant_reversion", Direction.BULLISH, 2,
                 f"Quant mean reversion: {ctx.zscore[-1]:.1f} standard deviations under its {cfg.quant_z_window}-day mean, "
                 f"RSI {ctx.rsi14[-1]:.0f}, still above the {cfg.quant_trend_period}-day trend; stop {stop:g}, target {target:g}",
                 {"zscore": round(ctx.zscore[-1], 2), "rsi14": ctx.rsi14[-1], "trend_ma": round(ctx.trend_ma[-1], 2),
                  "stop": stop, "target": target})


def trend_projection(ctx):
    f, cfg = ctx.forecast, ctx.config
    if not f or f.r_squared < cfg.min_forecast_r2 or abs(f.slope_pct_per_day) < cfg.min_forecast_slope_pct:
        return
    direction = Direction.BULLISH if f.slope_per_day > 0 else Direction.BEARISH
    yield Signal("forecast", direction, 1,
                 f"Steady {'up' if f.slope_per_day > 0 else 'down'}trend ({f.slope_pct_per_day:+.2f}%/day, fit {f.r_squared:.2f}); "
                 f"projects about {f.projected_close:g} in {f.horizon_days} sessions if it continues",
                 {"projected_close": f.projected_close, "r_squared": f.r_squared})


# Per-symbol strategies by the name their signals carry. Each can be switched off in admin.
REGISTRY = {
    "trend": trend,
    "ma_cross": moving_average_cross,
    "rsi": rsi_momentum,
    "macd": macd_momentum,
    "ema_5_8_13": ema_ribbon,
    "breakout": breakout,
    "volume": volume_spike,
    "forecast": trend_projection,
    "quant_momentum": quant_momentum,
    "quant_reversion": quant_reversion,
}
STRATEGIES = list(REGISTRY.values())

# Strategies that compare stocks with each other, run once per analysis run over all symbols.
CROSS_SECTIONAL = {
    "pairs": "Pairs trading: two related stocks whose price gap is stretched (z-score 2+) and has reliably closed before",
    "basket_reversion": "Basket mean reversion: a stock stretched away from its sector (or market) basket, expected to revert",
    "pca_leaders": "PCA sector leaders (Piyush-Quant): in a sideways market, buy the top-loading stocks of a driver sector once it turns up",
    "nepsealpha_hybrid": "NepseAlpha trend + momentum hybrid: market above its 240-day average, buy liquid stocks at RSI under 30 and z-score -2",
    "nepsealpha_seasonal": "NepseAlpha seasonal timing: buy the strongest liquid uptrending stocks in Falgun (mid-Feb), hold until Shrawan (mid-Jul)",
    "nepsealpha_momentum": "NepseAlpha 12-month momentum: monthly, while the market rises, buy the 5 liquid stocks with the best past-year return",
}

DESCRIPTIONS = {
    "trend": "Golden or death cross of the 50- and 200-day averages",
    "ma_cross": "Price crossing its 50-day average",
    "rsi": "RSI(14) overbought, oversold, or recovering from either",
    "macd": "MACD crossing its signal line",
    "ema_5_8_13": "5-8-13 EMA ribbon cross (switchmarkets.com)",
    "breakout": "Close through support or resistance, with volume confirmation",
    "volume": "Volume or transactions at least 2x the 20-day average",
    "forecast": "Steady linear trend projected 5 sessions ahead",
    "quant_momentum": "Quant momentum (Poudel & Paudel 2025): RSI breaks 60 above the 240-day trend, 4% stop, 1:4.5 target",
    "quant_reversion": "Quant mean reversion (Poudel & Paudel 2025): 15-day z-score dip with RSI oversold above the 240-day trend",
    **CROSS_SECTIONAL,
}


def sessions_needed(name, config=StrategyConfig()):
    """Trading days of history a stock needs before ``name`` can make a call at all."""
    needs = {
        "trend": 201,
        "ma_cross": 51,
        "quant_momentum": config.quant_trend_period + 1,
        "quant_reversion": config.quant_trend_period + 1,
        "pairs": stat_arb.LOOKBACK,
        "basket_reversion": stat_arb.LOOKBACK,
        "pca_leaders": pca.LOOKBACK + 1,
        **nepsealpha.SESSIONS_NEEDED,
    }
    return needs.get(name, 30)


def selected(enabled_names=None):
    """Per-symbol strategy functions, limited to ``enabled_names`` when given."""
    if enabled_names is None:
        return STRATEGIES
    return [fn for name, fn in REGISTRY.items() if name in enabled_names]
