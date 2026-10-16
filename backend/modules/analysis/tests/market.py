"""A synthetic NEPSE-like market for checking that every strategy can be evaluated.

Three sectors of related stocks over about two and a half years of Sunday-Thursday sessions:
a long sideways stretch (where pairs, baskets and PCA leaders trade), then a steady uptrend with
sharp dips and rallies (where the trend-following and quant strategies trade). Random but seeded,
so every strategy makes winning and losing calls.
"""
import math
import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from modules.marketdata.domain.entities import Candle, Timeframe

NPT = ZoneInfo("Asia/Kathmandu")
SESSIONS = 620
SIDEWAYS = 330  # sessions before the uptrend starts
SECTORS = {"Banking": ["BNK1", "BNK2", "BNK3", "BNK4"], "Hydropower": ["HYD1", "HYD2", "HYD3"], "Insurance": ["INS1", "INS2", "INS3"]}


def trading_days(first, n):
    days, d = [], first
    while len(days) < n:
        if d.weekday() not in (4, 5):  # NEPSE is shut on Friday and Saturday
            days.append(d)
        d += timedelta(days=1)
    return days


def bars(seed=11, first=date(2024, 1, 1), sessions=SESSIONS):
    """{symbol: [Candle]} for every stock in ``SECTORS``."""
    rng = random.Random(seed)
    days = trading_days(first, sessions)
    market = [rng.gauss(0, 0.008) for _ in days]
    out = {}
    for s_index, members in enumerate(SECTORS.values()):
        sector = [rng.gauss(0, 0.01) for _ in days]
        for m_index, symbol in enumerate(members):
            base, level, ou, jumps, candles = math.log(300.0 + 80 * m_index), 0.0, 0.0, 0.0, []
            beta = 0.8 + 0.15 * m_index
            price = math.exp(base)
            for i, d in enumerate(days):
                level += (0.0 if i < SIDEWAYS else 0.0022) + beta * (market[i] + sector[i])
                ou = 0.88 * ou + rng.gauss(0, 0.012)  # stock-specific and mean reverting: pairs and baskets trade it
                jumps += -0.07 if rng.random() < 0.012 else 0.06 if rng.random() < 0.012 else 0.0  # dips and rallies
                swing = 0.08 * math.sin(i / (25 + 7 * s_index) + s_index)  # sectors take turns leading
                open_ = price
                price = max(math.exp(base + level + ou + jumps + swing), 5.0)
                high = max(open_, price) * (1 + abs(rng.gauss(0, 0.006)))
                low = min(open_, price) * (1 - abs(rng.gauss(0, 0.006)))
                volume = int(2000 * (1 + abs(rng.gauss(0, 0.5))) * (3 if rng.random() < 0.03 else 1))
                candles.append(Candle(
                    symbol, Timeframe.DAILY, datetime.combine(d, time(15), tzinfo=NPT), d,
                    _p(open_), _p(high), _p(low), _p(price), volume, None, None, max(volume // 50, 1),
                ))
            out[symbol] = candles
    return out


def sectors():
    return {symbol: name for name, members in SECTORS.items() for symbol in members}


def _p(x):
    return Decimal(str(round(x, 2)))
