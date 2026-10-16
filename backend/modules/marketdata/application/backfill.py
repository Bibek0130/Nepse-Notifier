"""Use case: load daily history so indicators have data from day one."""
import logging
from datetime import datetime, time, timedelta

from django.db import transaction
from django.utils import timezone

from modules.shared import events

from ..domain.entities import Candle, Timeframe
from ..domain.ports import SourceError
from ..domain.validation import ValidationContext, ohlc_consistent, validate, volume_sane
from ..events import CandlesIngested
from ..infrastructure import repositories
from ..infrastructure.models import IngestionRun, Instrument
from ..infrastructure.sources.registry import history_source

logger = logging.getLogger(__name__)

# History has no previous close or turnover, so only structural rules apply.
HISTORY_RULES = [ohlc_consistent, volume_sane]

# Two years: the quant strategies need a 240-session trend (about a year of NEPSE sessions),
# and replaying them over the past year needs another year before that.
DEFAULT_DAYS = 730


def backfill_history(symbols=None, days=DEFAULT_DAYS, source=None):
    """Load ``days`` of daily bars for ``symbols`` (default: every active instrument).

    A symbol that fails is recorded and skipped, so one bad ticker doesn't stop the run.
    """
    source = source or history_source()
    if symbols is None:
        symbols = list(Instrument.objects.filter(is_active=True).values_list("symbol", flat=True))
    end = timezone.localdate()
    start = end - timedelta(days=days)
    run = IngestionRun.objects.create(kind=IngestionRun.Kind.BACKFILL, source=source.name, trading_date=end)

    loaded, failures, quarantined = [], [], 0
    for symbol in symbols:
        try:
            bars = source.fetch_history(symbol, start, end)
        except SourceError as exc:
            logger.warning("Backfill skipped %s: %s", symbol, exc)
            failures.append(f"{symbol}: {exc}")
            continue
        candles = [
            Candle(
                symbol=symbol,
                timeframe=Timeframe.DAILY,
                ts=timezone.make_aware(datetime.combine(b.date, time.min)),
                trading_date=b.date,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                volume=b.volume,
            )
            for b in bars
        ]
        result = validate(candles, ValidationContext(trading_date=end, is_trading_day=True), rules=HISTORY_RULES)
        with transaction.atomic():
            repositories.upsert_candles(result.accepted, run=run, source=source.name)
            repositories.record_issues(run, result.quarantined)
        quarantined += len(result.quarantined)
        if result.accepted:
            loaded.append(symbol)
        logger.info("Backfilled %d bars for %s", len(result.accepted), symbol)

    run.accepted = repositories.count_for_run(run)
    run.quarantined = quarantined
    run.error = "\n".join(failures)
    run.finished_at = timezone.now()
    if not loaded and symbols:
        run.status = IngestionRun.Status.FAILED
    elif failures or quarantined:
        run.status = IngestionRun.Status.PARTIAL
    else:
        run.status = IngestionRun.Status.OK
    with transaction.atomic():
        run.save()
        if loaded:
            events.publish(CandlesIngested(run_id=run.pk, timeframe=Timeframe.DAILY.value, trading_date=end.isoformat(), symbols=sorted(loaded)))
    return run
