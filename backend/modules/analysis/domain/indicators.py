"""Technical indicators on plain lists of floats (oldest first).

Every function returns a list the same length as its input, with None where
there is not yet enough history, so values line up with candles by index.
"""


def sma(values, period):
    out = [None] * len(values)
    window_sum = 0.0
    for i, v in enumerate(values):
        window_sum += v
        if i >= period:
            window_sum -= values[i - period]
        if i >= period - 1:
            out[i] = window_sum / period
    return out


def ema(values, period):
    """Exponential moving average, seeded with the SMA of the first ``period`` values."""
    out = [None] * len(values)
    if len(values) < period:
        return out
    k = 2 / (period + 1)
    out[period - 1] = sum(values[:period]) / period
    for i in range(period, len(values)):
        out[i] = values[i] * k + out[i - 1] * (1 - k)
    return out


def rsi(closes, period=14):
    """Wilder's Relative Strength Index (0-100)."""
    out = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        gains += max(change, 0)
        losses += max(-change, 0)
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = _rsi_value(avg_gain, avg_loss)
    for i in range(period + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0)) / period
        out[i] = _rsi_value(avg_gain, avg_loss)
    return out


def _rsi_value(avg_gain, avg_loss):
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def macd(closes, fast=12, slow=26, signal=9):
    """Return (macd_line, signal_line, histogram)."""
    fast_ema, slow_ema = ema(closes, fast), ema(closes, slow)
    line = [f - s if f is not None and s is not None else None for f, s in zip(fast_ema, slow_ema)]
    start = next((i for i, v in enumerate(line) if v is not None), len(line))
    signal_tail = ema(line[start:], signal)
    signal_line = [None] * start + signal_tail
    hist = [m - s if m is not None and s is not None else None for m, s in zip(line, signal_line)]
    return line, signal_line, hist


def average(values, period, exclude_last=False):
    """Mean of the last ``period`` values (optionally excluding today's), or None if too short."""
    window = values[-period - 1 : -1] if exclude_last else values[-period:]
    if len(window) < period or any(v is None for v in window):
        return None
    return sum(window) / period


def crossed_above(a, b):
    """True if series ``a`` crossed above ``b`` on the last bar."""
    if len(a) < 2 or None in (a[-1], a[-2], b[-1], b[-2]):
        return False
    return a[-2] <= b[-2] and a[-1] > b[-1]


def crossed_below(a, b):
    return crossed_above(b, a)
