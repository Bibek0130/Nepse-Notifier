"""Compute indicators, levels, forecast and signals for one symbol."""
from . import indicators as ind
from .entities import Analysis, PriceSeries
from .forecast import linear_trend
from .levels import find_levels
from .strategies import STRATEGIES, Context, StrategyConfig
from .trade_plan import build_trade_plan

MIN_BARS = 30  # below this, most indicators are meaningless


def _last(values):
    v = values[-1] if values else None
    return round(v, 4) if isinstance(v, float) else v


def analyze(series: PriceSeries, config: StrategyConfig = StrategyConfig(), strategies=STRATEGIES) -> Analysis | None:
    if len(series) < MIN_BARS:
        return None
    closes = series.closes
    macd_line, macd_signal, macd_hist = ind.macd(closes)
    support, resistance = find_levels(series.highs, series.lows, closes[-1])
    prev_support, prev_resistance = find_levels(series.highs[:-1], series.lows[:-1], closes[-2])
    trades = [t for t in series.trades if t is not None]

    ctx = Context(
        series=series,
        sma20=ind.sma(closes, 20),
        sma50=ind.sma(closes, 50),
        sma200=ind.sma(closes, 200),
        rsi14=ind.rsi(closes, 14),
        macd=macd_line,
        macd_signal=macd_signal,
        ema5=ind.ema(closes, 5),
        ema8=ind.ema(closes, 8),
        ema13=ind.ema(closes, 13),
        # Averages exclude today so a spike is measured against normal days.
        avg_volume20=ind.average(series.volumes, 20, exclude_last=True),
        avg_trades20=ind.average(trades, 20, exclude_last=True) if len(trades) > 20 else None,
        support=support,
        resistance=resistance,
        prev_support=prev_support,
        prev_resistance=prev_resistance,
        forecast=linear_trend(closes),
        config=config,
    )
    atr14 = ind.atr(series.highs, series.lows, closes, 14)
    signals = [signal for strategy in strategies for signal in strategy(ctx)]
    indicators = {
        "close": closes[-1],
        "sma20": _last(ctx.sma20),
        "sma50": _last(ctx.sma50),
        "sma200": _last(ctx.sma200),
        "rsi14": _last(ctx.rsi14),
        "macd": _last(macd_line),
        "macd_signal": _last(macd_signal),
        "macd_hist": _last(macd_hist),
        "ema5": _last(ctx.ema5),
        "ema8": _last(ctx.ema8),
        "ema13": _last(ctx.ema13),
        "atr14": _last(atr14),
        "volume": series.volumes[-1],
        "avg_volume20": ctx.avg_volume20,
        "trades": series.trades[-1],
        "avg_trades20": ctx.avg_trades20,
    }
    return Analysis(
        symbol=series.symbol,
        trading_date=series.dates[-1],
        provisional=series.provisional,
        indicators=indicators,
        support=support,
        resistance=resistance,
        forecast=ctx.forecast,
        signals=signals,
        trade_plan=build_trade_plan(series, support, resistance, ctx.ema5, ctx.ema8, ctx.ema13, atr14),
    )
