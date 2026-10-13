"""Read-side use cases, served from the Redis cache with Postgres as the fallback."""
from ..infrastructure import cache, repositories
from ..infrastructure.models import IngestionRun, Instrument


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


def pipeline_status():
    """Latest run of each kind, without error details (safe to show publicly)."""
    status = {}
    for kind in IngestionRun.Kind:
        run = IngestionRun.objects.filter(kind=kind).order_by("-started_at").first()
        status[kind.value] = None if run is None else {
            "status": run.status,
            "source": run.source,
            "trading_date": run.trading_date.isoformat() if run.trading_date else None,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "accepted": run.accepted,
            "quarantined": run.quarantined,
        }
    return status
