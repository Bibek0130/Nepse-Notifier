"""Use case: fill an empty database with real NEPSE history for the hosted demo.

The demo's host can't reach sharesansar or merolagani, so prices come from a public
CSV archive instead. After loading, the last ``replay_sessions`` closes are announced
one day at a time, oldest first, exactly as the end-of-day fetch would have announced
them, so the analysis, predictions and their scoring all run through the normal path.
"""
import logging
from datetime import datetime, time

from django.db import transaction
from django.utils import timezone

from modules.shared import events

from ..domain.entities import Candle, Timeframe
from ..events import CandlesIngested
from ..infrastructure import cache, repositories
from ..infrastructure.models import Candle as CandleRow
from ..infrastructure.models import IngestionRun, Instrument
from ..infrastructure.sources.nepse_data import NepseDataSource
from .backfill import backfill_history

logger = logging.getLogger(__name__)

SNAPSHOT_TIME = time(15, 0)  # market close, NPT


def seed_demo(sectors, days=730, replay_sessions=20, source=None, progress=None):
    """Load ``days`` of history for each symbol in ``sectors`` ({symbol: sector}) and analyse the latest sessions.

    Returns (backfill run, list of trading dates announced).
    """
    report = progress or (lambda message: None)
    for symbol, sector in sectors.items():
        Instrument.objects.update_or_create(symbol=symbol, defaults={"sector": sector, "is_active": True})

    report(f"Downloading {days} days of history for {len(sectors)} stocks")
    run = backfill_history(sorted(sectors), days=days, source=source or NepseDataSource(), publish=False)
    if run.status == IngestionRun.Status.FAILED:
        return run, []

    daily = CandleRow.objects.filter(timeframe=Timeframe.DAILY.value, instrument__symbol__in=sectors)
    dates = sorted(set(daily.values_list("trading_date", flat=True)))
    if not dates:
        return run, []
    _store_closing_snapshot(daily, dates, run)

    replay = dates[-replay_sessions:] if replay_sessions > 0 else []
    for n, day in enumerate(replay, 1):
        symbols = sorted(daily.filter(trading_date=day).values_list("instrument__symbol", flat=True))
        report(f"Analysing {day} ({n}/{len(replay)}, {len(symbols)} stocks)")
        events.publish(CandlesIngested(run_id=run.pk, timeframe=Timeframe.DAILY.value, trading_date=day.isoformat(), symbols=symbols))
    return run, replay


def _store_closing_snapshot(daily, dates, run):
    """Save the last session's close as the latest snapshot, which the dashboard's quotes and summary read."""
    last = dates[-1]
    previous = dates[-2] if len(dates) > 1 else None
    previous_close = dict(daily.filter(trading_date=previous).values_list("instrument__symbol", "close")) if previous else {}
    ts = timezone.make_aware(datetime.combine(last, SNAPSHOT_TIME))
    snapshot = [
        Candle(
            symbol=row.instrument.symbol, timeframe=Timeframe.INTRADAY_3H, ts=ts, trading_date=last,
            open=row.open, high=row.high, low=row.low, close=row.close, volume=row.volume,
            previous_close=previous_close.get(row.instrument.symbol), turnover=row.turnover,
        )
        for row in daily.filter(trading_date=last).select_related("instrument")
    ]
    with transaction.atomic():
        repositories.upsert_candles(snapshot, run=run, source=run.source)
    cache.store(snapshot)
