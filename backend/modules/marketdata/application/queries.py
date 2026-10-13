"""Read-side use cases, served from the Redis cache with Postgres as the fallback."""
from ..infrastructure import cache, repositories
from ..infrastructure.models import Instrument


def latest_quotes():
    rows = cache.latest_quotes()
    if rows is None:
        rows = cache.store(repositories.latest_snapshot())
    return rows


def market_summary():
    summary = cache.summary()
    if summary is None:
        cache.store(repositories.latest_snapshot())
        summary = cache.summary()
    return summary


def instruments(active_only=True):
    qs = Instrument.objects.all()
    return qs.filter(is_active=True) if active_only else qs


def candles(symbol, timeframe, start=None, end=None):
    return [repositories.to_entity(row) for row in repositories.candles(symbol, timeframe, start, end)]
