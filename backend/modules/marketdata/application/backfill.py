"""Use case: load daily history so indicators have data from day one."""
import logging
from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import Count, Min
from django.utils import timezone

from modules.shared import events

from ..domain.entities import Candle, Timeframe
from ..domain.ports import SourceError
from ..domain.validation import ValidationContext, ohlc_consistent, validate, volume_sane
from ..events import CandlesIngested
from ..infrastructure import repositories
from ..infrastructure.models import Candle as CandleRow
from ..infrastructure.models import IngestionRun, Instrument
from ..infrastructure.sources.registry import history_source

logger = logging.getLogger(__name__)

# History has no previous close or turnover, so only structural rules apply.
HISTORY_RULES = [ohlc_consistent, volume_sane]

# Two years: the quant strategies need a 240-session trend (about a year of NEPSE sessions),
# and replaying them over the past year needs another year before that.
DEFAULT_DAYS = 730
# Saved history reaching this close to the start of the requested window counts as the whole window.
COVERAGE_SLACK_DAYS = 45


def history_status(days=DEFAULT_DAYS):
    """(longest sessions saved for any stock, oldest saved date, whether that already covers ``days``)."""
    daily = CandleRow.objects.filter(timeframe=Timeframe.DAILY.value)
    longest = daily.values("instrument").annotate(n=Count("id")).order_by("-n").values_list("n", flat=True).first() or 0
    oldest = daily.aggregate(oldest=Min("trading_date"))["oldest"]
    covered = oldest is not None and oldest <= timezone.localdate() - timedelta(days=days - COVERAGE_SLACK_DAYS)
    return longest, oldest, covered


def history_is_short(min_sessions, days=DEFAULT_DAYS):
    """True when no stock has ``min_sessions`` saved and the saved history doesn't reach back ``days`` yet.

    Once it reaches back that far there is nothing more to download, so a source with less history
    doesn't make every run download it all again.
    """
    longest, _, covered = history_status(days)
    return longest < min_sessions and not covered


def backfill_history(symbols=None, days=DEFAULT_DAYS, source=None, publish=True):
    """Load ``days`` of daily bars for ``symbols`` (default: every active instrument).

    A symbol that fails is recorded and skipped, so one bad ticker doesn't stop the run.
    With ``publish=False`` no CandlesIngested event is sent, so nothing is analysed yet.
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
                turnover=b.turnover,
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
        if loaded and publish:
            events.publish(CandlesIngested(run_id=run.pk, timeframe=Timeframe.DAILY.value, trading_date=end.isoformat(), symbols=sorted(loaded)))
    return run
