"""Redis cache of the latest quotes and market summary, read by the API and dashboard."""
from django.conf import settings
from django.core.cache import cache

LATEST_KEY = "marketdata:latest_quotes"
SUMMARY_KEY = "marketdata:summary"


def _row(c):
    change = None
    if c.previous_close:
        change = round(float((c.close - c.previous_close) / c.previous_close * 100), 2)
    return {
        "symbol": c.symbol,
        "ts": c.ts.isoformat(),
        "open": str(c.open),
        "high": str(c.high),
        "low": str(c.low),
        "close": str(c.close),
        "previous_close": str(c.previous_close) if c.previous_close is not None else None,
        "change_percent": change,
        "volume": c.volume,
        "turnover": str(c.turnover) if c.turnover is not None else None,
        "trades": c.trades,
    }


def build_summary(rows, top=10):
    with_change = [r for r in rows if r["change_percent"] is not None]
    by_turnover = [r for r in rows if r["turnover"] is not None]
    return {
        "as_of": max((r["ts"] for r in rows), default=None),
        "symbols": len(rows),
        "advancers": sum(1 for r in with_change if r["change_percent"] > 0),
        "decliners": sum(1 for r in with_change if r["change_percent"] < 0),
        "unchanged": sum(1 for r in with_change if r["change_percent"] == 0),
        "total_turnover": str(sum(float(r["turnover"]) for r in by_turnover)),
        "top_gainers": sorted(with_change, key=lambda r: r["change_percent"], reverse=True)[:top],
        "top_losers": sorted(with_change, key=lambda r: r["change_percent"])[:top],
        "top_turnover": sorted(by_turnover, key=lambda r: float(r["turnover"]), reverse=True)[:top],
    }


def store(candles):
    rows = sorted((_row(c) for c in candles), key=lambda r: r["symbol"])
    ttl = settings.MARKETDATA["CACHE_TTL_SECONDS"]
    cache.set_many({LATEST_KEY: rows, SUMMARY_KEY: build_summary(rows)}, ttl)
    return rows


def latest_quotes():
    return cache.get(LATEST_KEY)


def summary():
    return cache.get(SUMMARY_KEY)
