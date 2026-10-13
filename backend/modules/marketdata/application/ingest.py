"""Use case: run the market data pipeline once.

schedule -> fetch -> land raw -> normalise -> validate -> persist -> cache -> publish
"""
import logging
from datetime import datetime, time
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from modules.shared import calendar, events
from modules.shared.locks import LockNotAcquired, single_flight

from ..domain.entities import Candle, RunKind, Timeframe
from ..domain.ports import SourceError
from ..domain.validation import ValidationContext, validate
from ..events import CandlesIngested
from ..infrastructure import cache, circuit_breaker, raw_store, repositories
from ..infrastructure.models import IngestionRun
from ..infrastructure.sources.registry import snapshot_sources

logger = logging.getLogger(__name__)


class StageLog:
    """Records each stage's outcome on the run so failures are visible in admin and the API."""

    def __init__(self, run):
        self.run = run

    def mark(self, stage, status, **detail):
        self.run.stages[stage] = {"status": status, "at": timezone.now().isoformat(), **detail}
        self.run.save(update_fields=["stages"])

    def finish(self, status, **fields):
        self.run.status = status
        self.run.finished_at = timezone.now()
        for name, value in fields.items():
            setattr(self.run, name, value)
        self.run.save()
        return self.run


def ingest_market(kind=RunKind.INTRADAY, *, sources=None, now=None, force=False):
    """Run the pipeline once and return the IngestionRun.

    ``force`` ignores the trading calendar and the "source unchanged" check, for
    manual runs and testing outside market hours.
    """
    kind = RunKind(kind)
    now = now or timezone.now()
    trading_date = timezone.localdate(now)
    run = IngestionRun.objects.create(kind=kind.value, trading_date=trading_date)
    log = StageLog(run)

    # 1. Schedule: only on trading days, and never two runs at once.
    is_trading_day = calendar.is_trading_day(trading_date)
    if not is_trading_day and not force:
        log.mark("schedule", "skipped", reason="market closed")
        return log.finish(IngestionRun.Status.SKIPPED)
    try:
        with single_flight("marketdata:ingest", settings.MARKETDATA["INGEST_LOCK_SECONDS"]):
            log.mark("schedule", "ok")
            return _run_pipeline(log, kind, now, trading_date, sources, force, is_trading_day or force)
    except LockNotAcquired:
        log.mark("schedule", "skipped", reason="another run in progress")
        return log.finish(IngestionRun.Status.SKIPPED)
    except Exception as exc:
        logger.exception("Ingestion run %s failed", run.pk)
        log.finish(IngestionRun.Status.FAILED, error=str(exc))
        raise


def _run_pipeline(log, kind, now, trading_date, sources, force, is_trading_day):
    run = log.run

    # 2-4. Fetch, land raw, normalise. Falls through sources until one parses.
    sources = sources if sources is not None else snapshot_sources()
    fetched = _fetch(log, sources, now, force)
    if fetched is None:
        return log.finish(IngestionRun.Status.STALE)
    source, quotes = fetched
    run.source, run.fetched = source.name, len(quotes)
    run.save(update_fields=["source", "fetched"])

    snapshot_ts = now.replace(second=0, microsecond=0)
    candles = [Candle.from_quote(q, Timeframe.INTRADAY_3H, snapshot_ts, trading_date) for q in quotes]
    if kind == RunKind.END_OF_DAY:
        day_ts = timezone.make_aware(datetime.combine(trading_date, time.min))
        candles += [Candle.from_quote(q, Timeframe.DAILY, day_ts, trading_date) for q in quotes]

    # 5. Validate.
    cfg = settings.MARKETDATA
    context = ValidationContext(
        trading_date=trading_date,
        is_trading_day=is_trading_day,
        price_band_percent=Decimal(str(cfg["PRICE_BAND_PERCENT"])),
        cross_source_tolerance_percent=Decimal(str(cfg["CROSS_SOURCE_TOLERANCE_PERCENT"])),
        reference_closes=_reference_closes(sources, source) if kind == RunKind.END_OF_DAY else {},
        adjusted_symbols=repositories.symbols_with_corporate_action(trading_date),
        previous_closes=repositories.previous_closes(trading_date),
    )
    result = validate(candles, context)
    log.mark("validate", "ok", accepted=len(result.accepted), quarantined=len(result.quarantined), flagged=len(result.flagged))

    # 6. Persist, and 8. publish once committed.
    with transaction.atomic():
        repositories.upsert_candles(result.accepted, run=run, source=source.name)
        repositories.record_issues(run, result.quarantined + result.flagged)
        for timeframe in sorted({c.timeframe for c in result.accepted}):
            events.publish(
                CandlesIngested(
                    run_id=run.pk,
                    timeframe=timeframe.value,
                    trading_date=trading_date.isoformat(),
                    symbols=sorted({c.symbol for c in result.accepted if c.timeframe == timeframe}),
                )
            )
    log.mark("persist", "ok", rows=len(result.accepted))

    # 7. Cache the latest snapshot for the API.
    cache.store([c for c in result.accepted if c.timeframe == Timeframe.INTRADAY_3H])
    log.mark("cache", "ok")

    status = IngestionRun.Status.PARTIAL if result.quarantined else IngestionRun.Status.OK
    return log.finish(status, accepted=len(result.accepted), quarantined=len(result.quarantined))


def _fetch(log, sources, now, force):
    """Return (source, quotes) from the first healthy source, or None if the data hasn't changed."""
    errors = []
    for source in sources:
        if circuit_breaker.is_open(source.name):
            errors.append(f"{source.name}: circuit open, skipped")
            continue
        try:
            raw = source.fetch_raw()
        except SourceError as exc:
            circuit_breaker.record_failure(source.name)
            errors.append(str(exc))
            continue
        log.mark("fetch", "ok", source=source.name, errors=list(errors))

        unchanged = raw_store.content_hash(raw.body) == raw_store.latest_hash(source.name)
        raw_store.save(raw, log.run, now)
        if unchanged and not force:
            log.mark("land_raw", "stale", source=source.name)
            return None
        log.mark("land_raw", "ok", source=source.name)

        try:
            quotes = source.parse(raw.body)
        except SourceError as exc:
            circuit_breaker.record_failure(source.name)
            errors.append(str(exc))
            log.mark("normalise", "failed", source=source.name, error=str(exc))
            continue
        circuit_breaker.record_success(source.name)
        log.mark("normalise", "ok", source=source.name, quotes=len(quotes))
        return source, quotes

    log.mark("fetch", "failed", errors=errors)
    raise SourceError("All sources failed: " + " | ".join(errors))


def _reference_closes(sources, primary):
    """Closing prices from the next healthy source, for the cross-source check. Best effort."""
    for source in sources:
        if source is primary or circuit_breaker.is_open(source.name):
            continue
        try:
            return {q.symbol: q.ltp for q in source.parse(source.fetch_raw().body)}
        except SourceError as exc:
            logger.info("Cross-check source %s unavailable: %s", source.name, exc)
    return {}
