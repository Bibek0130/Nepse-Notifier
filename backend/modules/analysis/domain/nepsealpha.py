"""NepseAlpha quant strategies, from "Quantitative Strategies for NEPSE: Analysis & Recommendations".

The report ranks strategies by how well they fit NEPSE (long only, thin liquidity, high costs,
a retail market that trends and panics) and recommends, best first:

1. Trend + momentum hybrid (High fit): only buy while the market is above its 240-day average,
   and buy oversold dips there (14-day RSI under 30 and a price z-score of -2 or lower), at most
   four positions. The report folds its RSI mean-reversion idea (Low-Med fit) into this one: an
   RSI buy only works behind a market regime filter.
2. Seasonal timing (Medium fit): NepseAlpha's "buy in Falgun, sell in Shrawan" (mid-February to
   mid-July), combined with trend and momentum as the report advises: during Falgun, buy liquid
   stocks above their 50-day average and up over six months, and hold them about 100 sessions.
3. 12-month momentum (Medium fit): buy the liquid stocks with the best past-year return, once a
   month, and only while the broad market is rising.

Its fifth candidate, fundamental factors (Low fit), needs company financials we don't have.

All three compare stocks with each other and the market, so they run once per run over every
stock (cross-sectional), and only buy the most-traded stocks: the report warns that thin stocks
can't be traded without moving the price. The report publishes no exact stops or targets; the
ones here are ours. Pure Python.
"""
import statistics
from datetime import date

from . import indicators as ind
from .entities import Direction, Signal

STRATEGY_HYBRID = "nepsealpha_hybrid"
STRATEGY_SEASONAL = "nepsealpha_seasonal"
STRATEGY_MOMENTUM = "nepsealpha_momentum"
STRATEGIES = (STRATEGY_HYBRID, STRATEGY_SEASONAL, STRATEGY_MOMENTUM)

WINDOW = 260  # sessions per stock a scan looks at: the 240-day market trend and the 12-month return fit in it
TREND_PERIOD = 240  # market regime filter: equal-weighted market above its 240-day average
# NEPSE stocks move at most 10% a day; a bigger close-to-close jump is a bonus or rights adjustment
# in unadjusted prices, not a real return, and would fake a crash (or a rally) otherwise.
MAX_DAILY_MOVE = 0.105
LIQUID_STOCKS = 100  # only the most-traded stocks (average turnover over 20 sessions) are bought
TURNOVER_SESSIONS = 20

# Trend + momentum hybrid
RSI_OVERSOLD = 30
Z_WINDOW = 15
Z_ENTRY = -2.0
MAX_POSITIONS = 4  # new buys a day, the most oversold first (the report's four-position limit)
COOLDOWN = 3  # sessions: only the first day of a dip is a call
CLEAN_SESSIONS = 30  # no corporate-action jump this recent, or RSI and the z-score are fake
MIN_STOP_PCT, MAX_STOP_PCT = 2.0, 8.0

# Seasonal timing. Falgun 1 falls on 12-14 February, Chaitra 1 on 13-15 March and Shrawan 1 on 16-17 July.
FALGUN_START = (2, 13)
CHAITRA_START = (3, 14)
SEASON_SESSIONS = 100  # Falgun to Shrawan, in NEPSE sessions
SEASONAL_PICKS = 5  # buys a day, strongest six-month return first
SEASONAL_TREND = 50  # a seasonal buy must be above its 50-day average
SEASONAL_RANK_SESSIONS = 120  # ranked by six-month return
SEASONAL_STOP_PCT = 15.0

# 12-month momentum
MOMENTUM_SESSIONS = 240  # one year
MOMENTUM_SKIP = 20  # leave out the latest month, which tends to reverse
MOMENTUM_PICKS = 5
MOMENTUM_HOLD = 20  # sessions, until the next monthly rebalance
MOMENTUM_STOP_PCT = 10.0

HORIZONS = {STRATEGY_HYBRID: 20, STRATEGY_SEASONAL: SEASON_SESSIONS, STRATEGY_MOMENTUM: MOMENTUM_HOLD}
SESSIONS_NEEDED = {STRATEGY_HYBRID: TREND_PERIOD + 1, STRATEGY_SEASONAL: SEASONAL_RANK_SESSIONS + 1,
                   STRATEGY_MOMENTUM: MOMENTUM_SESSIONS + 1}


def clean_returns(closes):
    """Daily returns, with corporate-action jumps (beyond NEPSE's 10% band) counted as no change."""
    out = []
    for a, b in zip(closes[:-1], closes[1:]):
        r = b / a - 1 if a > 0 else 0.0
        out.append(r if abs(r) <= MAX_DAILY_MOVE else 0.0)
    return out


def has_jump(closes):
    return any(a > 0 and abs(b / a - 1) > MAX_DAILY_MOVE for a, b in zip(closes[:-1], closes[1:]))


def growth(closes):
    """Return over ``closes`` in percent, from clean daily returns."""
    level = 1.0
    for r in clean_returns(closes):
        level *= 1 + r
    return (level - 1) * 100


def market_index(series_by_symbol):
    """(dates, levels): the equal-weighted market, each day the average clean return of the stocks that traded."""
    by_day = {}
    for s in series_by_symbol.values():
        for d, r in zip(s.dates[1:], clean_returns(s.closes)):
            by_day.setdefault(d, []).append(r)
    dates, levels, level = sorted(by_day), [], 100.0
    for d in dates:
        level *= 1 + statistics.fmean(by_day[d])
        levels.append(level)
    return dates, levels


def market_trend(series_by_symbol):
    """(market above its 240-day average?, % above it), or (None, None) without enough history."""
    _, levels = market_index(series_by_symbol)
    if len(levels) < TREND_PERIOD:
        return None, None
    average = statistics.fmean(levels[-TREND_PERIOD:])
    return levels[-1] > average, (levels[-1] / average - 1) * 100


def _turnover(s):
    recent = list(zip(s.closes[-TURNOVER_SESSIONS:], s.volumes[-TURNOVER_SESSIONS:]))
    return sum(c * v for c, v in recent) / len(recent) if recent else 0.0


def liquid(series_by_symbol, today, sessions):
    """The most-traded stocks that traded ``today`` and have ``sessions`` bars, most traded first."""
    ok = [s for s in series_by_symbol.values() if len(s) >= sessions and s.dates and s.dates[-1] == today and s.closes[-1] > 0]
    ok.sort(key=lambda s: (-_turnover(s), s.symbol))
    return ok[:LIQUID_STOCKS]


def _calendar(series_by_symbol):
    days = sorted({d for s in series_by_symbol.values() for d in s.dates[-5:]})
    return days[-1] if days else None, days[-2] if len(days) > 1 else None


def first_session_from(month_day, today, previous):
    """True when ``today`` is the first session on or after ``month_day`` (month, day) this year."""
    if today is None or previous is None:
        return False
    boundary = date(today.year, *month_day)
    return previous < boundary <= today


def hybrid(series_by_symbol, today):
    """Trend + momentum hybrid: an oversold dip in a liquid stock while the market is in an uptrend."""
    up, above_pct = market_trend(series_by_symbol)
    if not up:
        return []
    found = []
    for s in liquid(series_by_symbol, today, Z_WINDOW + COOLDOWN + 2):
        closes = s.closes[-100:]
        if has_jump(closes[-CLEAN_SESSIONS:]):
            continue
        rsi, z = ind.rsi(closes), ind.zscore(closes, Z_WINDOW)

        def oversold(k):  # on bar -1-k
            r, zz = rsi[-1 - k], z[-1 - k]
            return r is not None and zz is not None and r < RSI_OVERSOLD and zz <= Z_ENTRY

        if oversold(0) and not any(oversold(k) for k in range(1, COOLDOWN + 1)):
            found.append((z[-1], s, rsi[-1]))
    found.sort(key=lambda x: (x[0], x[1].symbol))
    out = []
    for z, s, rsi in found[:MAX_POSITIONS]:
        close = s.closes[-1]
        target = statistics.fmean(s.closes[-Z_WINDOW:])  # back to its 15-day mean, where the z-score is 0
        risk = min(max((target - close) / 2, close * MIN_STOP_PCT / 100), close * MAX_STOP_PCT / 100)
        stop, target = round(close - risk, 2), round(target, 1)
        out.append((s.symbol, Signal(
            STRATEGY_HYBRID, Direction.BULLISH, 2,
            f"NepseAlpha hybrid: market {above_pct:+.1f}% above its {TREND_PERIOD}-day average and the stock oversold "
            f"(RSI {rsi:.0f}, {z:.1f} standard deviations under its {Z_WINDOW}-day mean); stop {stop:g}, target {target:g}",
            {"rsi14": round(rsi, 1), "zscore": round(z, 2), "market_vs_trend_pct": round(above_pct, 2),
             "stop": stop, "target": target},
        )))
    return out


def in_falgun(day):
    return date(day.year, *FALGUN_START) <= day < date(day.year, *CHAITRA_START)


def _below_trend_all_season(s, today):
    """True when ``s`` closed at or under its 50-day average on every earlier session of this Falgun."""
    start = date(today.year, *FALGUN_START)
    for i in range(len(s) - 2, SEASONAL_TREND - 2, -1):
        if s.dates[i] < start:
            return True
        if s.closes[i] > statistics.fmean(s.closes[i - SEASONAL_TREND + 1:i + 1]):
            return False
    return True


def seasonal(series_by_symbol, today, previous):
    """Seasonal timing: buy in Falgun, to hold until Shrawan. On Falgun's first session, the liquid stocks
    already in an uptrend; on its other sessions, those that just joined one (closed back above the 50-day
    average). Either way the stock must be up over six months, the strongest first."""
    if today is None or not in_falgun(today):
        return []
    opening = first_session_from(FALGUN_START, today, previous)
    ranked = []
    for s in liquid(series_by_symbol, today, SEASONAL_RANK_SESSIONS + 1):
        closes = s.closes
        if closes[-1] <= statistics.fmean(closes[-SEASONAL_TREND:]):
            continue
        if not opening and not _below_trend_all_season(s, today):
            continue  # was in an uptrend earlier this Falgun: bought then (or passed over), not a new entry
        change = growth(closes[-SEASONAL_RANK_SESSIONS - 1:])
        if change > 0:  # momentum too: up over six months, not just a bounce in a downtrend
            ranked.append((change, s))
    ranked.sort(key=lambda x: (-x[0], x[1].symbol))
    how = f"above its {SEASONAL_TREND}-day average" if opening else f"just closed back above its {SEASONAL_TREND}-day average"
    out = []
    for change, s in ranked[:SEASONAL_PICKS]:
        close = s.closes[-1]
        stop = round(close * (1 - SEASONAL_STOP_PCT / 100), 2)
        out.append((s.symbol, Signal(
            STRATEGY_SEASONAL, Direction.BULLISH, 2,
            f"NepseAlpha seasonal: Falgun buy, to hold until Shrawan (mid-July); {how}, "
            f"{change:+.1f}% over six months; stop {stop:g}",
            {"six_month_pct": round(change, 1), "stop": stop},
        )))
    return out


def momentum(series_by_symbol, today, previous):
    """12-month momentum: on the first session of each month, while the market is rising, buy the liquid
    stocks with the best return from a year ago to a month ago."""
    if today is None or previous is None or previous.month == today.month:
        return []
    up, above_pct = market_trend(series_by_symbol)
    if not up:
        return []
    ranked = []
    for s in liquid(series_by_symbol, today, MOMENTUM_SESSIONS + 1):
        change = growth(s.closes[-MOMENTUM_SESSIONS - 1:-MOMENTUM_SKIP])
        if change > 0:
            ranked.append((change, s))
    ranked.sort(key=lambda x: (-x[0], x[1].symbol))
    out = []
    for change, s in ranked[:MOMENTUM_PICKS]:
        close = s.closes[-1]
        stop = round(close * (1 - MOMENTUM_STOP_PCT / 100), 2)
        out.append((s.symbol, Signal(
            STRATEGY_MOMENTUM, Direction.BULLISH, 2,
            f"NepseAlpha 12-month momentum: {change:+.1f}% from a year ago to a month ago, among the strongest "
            f"liquid stocks, with the market {above_pct:+.1f}% above its {TREND_PERIOD}-day average; hold a month, stop {stop:g}",
            {"twelve_month_pct": round(change, 1), "market_vs_trend_pct": round(above_pct, 2), "stop": stop},
        )))
    return out


def scan(series_by_symbol, enabled=STRATEGIES):
    """Calls of the ``enabled`` NepseAlpha strategies for one day's {symbol: PriceSeries}. Returns [(symbol, Signal)]."""
    today, previous = _calendar(series_by_symbol)
    found = []
    if STRATEGY_HYBRID in enabled:
        found += hybrid(series_by_symbol, today)
    if STRATEGY_SEASONAL in enabled:
        found += seasonal(series_by_symbol, today, previous)
    if STRATEGY_MOMENTUM in enabled:
        found += momentum(series_by_symbol, today, previous)
    return found
