"""Per-stock trade levels: buy, sell and correction zones, stop loss, target and risk-to-reward.

The zones are built from the support and resistance the engine already found, padded by
the stock's typical daily swing (ATR), and from Fibonacci retracements of the latest swing.
They describe where price has reacted before; they are not a prediction. Pure Python.
"""
from dataclasses import dataclass

SWING_LOOKBACK = 60  # bars used to find the latest swing high and low
ZONE_ATR = 0.5  # zone width, in ATRs
STOP_ATR = 1.0  # stop distance below the buy zone, in ATRs
NO_RESISTANCE_TARGET_ATR = 3.0  # target above the price when there is no resistance overhead


@dataclass(frozen=True)
class Zone:
    low: float
    high: float

    def contains(self, price):
        return self.low <= price <= self.high


@dataclass(frozen=True)
class TradePlan:
    ltp: float
    change: float | None  # versus the previous close
    change_pct: float | None
    change_5d_pct: float | None
    movement: str  # "uptrend", "downtrend" or "sideways"
    atr: float
    atr_pct: float
    swing_low: float
    swing_high: float
    swing: str  # "up" when the swing high came after the low, else "down"
    buy_zone: Zone
    sell_zone: Zone
    correction_zone: Zone  # 38.2%-61.8% retracement of the latest swing
    stop_loss: float
    target: float
    risk_reward: float | None  # reward per rupee of risk if bought at the LTP
    position: str  # where the LTP sits: "in buy zone", "in sell zone", "in correction zone" or "between zones"


def _r(x):
    return round(x, 1)


def _pct(now, before):
    return round((now - before) / before * 100, 2) if before else None


def movement(closes, ema5, ema8, ema13):
    """Short-term direction from the 5-8-13 EMA ribbon."""
    if None in (ema5[-1], ema8[-1], ema13[-1]):
        return "sideways"
    close, fast, mid, slow = closes[-1], ema5[-1], ema8[-1], ema13[-1]
    if fast > mid > slow and close > slow:
        return "uptrend"
    if fast < mid < slow and close < slow:
        return "downtrend"
    return "sideways"


def fibonacci_zone(swing_low, swing_high, up_swing):
    """The 38.2%-61.8% retracement band: where a pullback in an up swing (or a bounce in a down swing) usually stalls."""
    span = swing_high - swing_low
    if up_swing:
        return Zone(_r(swing_high - 0.618 * span), _r(swing_high - 0.382 * span))
    return Zone(_r(swing_low + 0.382 * span), _r(swing_low + 0.618 * span))


def build_trade_plan(series, support, resistance, ema5, ema8, ema13, atr_values) -> TradePlan | None:
    closes, highs, lows = series.closes, series.highs, series.lows
    atr = atr_values[-1] if atr_values else None
    if not atr or len(closes) < 2:
        return None
    ltp = closes[-1]

    recent_highs, recent_lows = highs[-SWING_LOOKBACK:], lows[-SWING_LOOKBACK:]
    swing_high, swing_low = max(recent_highs), min(recent_lows)
    up_swing = recent_highs.index(swing_high) >= recent_lows.index(swing_low)
    correction = fibonacci_zone(swing_low, swing_high, up_swing)

    # Buy near support; without one, near the bottom of the swing.
    floor = support.price if support else min(swing_low, ltp)
    buy = Zone(_r(floor), _r(floor + ZONE_ATR * atr))
    stop = _r(max(floor - STOP_ATR * atr, 0.0))

    # Sell near resistance; without one (new highs), a few ATRs above the price.
    if resistance:
        target = resistance.price
    elif swing_high > ltp:
        target = swing_high
    else:
        target = ltp + NO_RESISTANCE_TARGET_ATR * atr
    sell = Zone(_r(target - ZONE_ATR * atr), _r(target))

    risk, reward = ltp - stop, target - ltp
    risk_reward = round(reward / risk, 2) if risk > 0 and reward > 0 else None

    if buy.contains(ltp):
        position = "in buy zone"
    elif sell.contains(ltp):
        position = "in sell zone"
    elif correction.contains(ltp):
        position = "in correction zone"
    else:
        position = "between zones"

    return TradePlan(
        ltp=ltp,
        change=_r(ltp - closes[-2]),
        change_pct=_pct(ltp, closes[-2]),
        change_5d_pct=_pct(ltp, closes[-6]) if len(closes) > 5 else None,
        movement=movement(closes, ema5, ema8, ema13),
        atr=round(atr, 2),
        atr_pct=round(atr / ltp * 100, 2),
        swing_low=_r(swing_low),
        swing_high=_r(swing_high),
        swing="up" if up_swing else "down",
        buy_zone=buy,
        sell_zone=sell,
        correction_zone=correction,
        stop_loss=stop,
        target=_r(target),
        risk_reward=risk_reward,
        position=position,
    )
