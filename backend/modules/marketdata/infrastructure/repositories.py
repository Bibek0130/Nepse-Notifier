"""Postgres access for the market data module. Converts between ORM rows and domain objects."""
from datetime import date, timedelta

from ..domain import entities
from .models import Candle, CandleIssue, CorporateAction, Instrument

CANDLE_UPDATE_FIELDS = ["trading_date", "open", "high", "low", "close", "previous_close", "volume", "turnover", "trades", "source", "run"]


def instruments_by_symbol(symbols):
    """Return {symbol: Instrument}, creating instruments we haven't seen before."""
    symbols = set(symbols)
    existing = {i.symbol: i for i in Instrument.objects.filter(symbol__in=symbols)}
    missing = [Instrument(symbol=s) for s in symbols - existing.keys()]
    if missing:
        Instrument.objects.bulk_create(missing, ignore_conflicts=True)
        existing = {i.symbol: i for i in Instrument.objects.filter(symbol__in=symbols)}
    return existing


def upsert_candles(candles, run=None, source=""):
    """Insert candles, overwriting any existing one with the same instrument, timeframe and ts."""
    candles = list(candles)
    if not candles:
        return 0
    instruments = instruments_by_symbol(c.symbol for c in candles)
    rows = [
        Candle(
            instrument=instruments[c.symbol],
            timeframe=c.timeframe.value,
            ts=c.ts,
            trading_date=c.trading_date,
            open=c.open,
            high=c.high,
            low=c.low,
            close=c.close,
            previous_close=c.previous_close,
            volume=c.volume,
            turnover=c.turnover,
            trades=c.trades,
            source=source,
            run=run,
        )
        for c in candles
    ]
    Candle.objects.bulk_create(
        rows,
        update_conflicts=True,
        unique_fields=["instrument", "timeframe", "ts"],
        update_fields=CANDLE_UPDATE_FIELDS,
    )
    return len(rows)


def record_issues(run, candle_issues):
    CandleIssue.objects.bulk_create(
        CandleIssue(
            run=run,
            symbol=candle.symbol,
            timeframe=candle.timeframe.value,
            rule=issue.rule,
            severity=issue.severity,
            message=issue.message,
            values={k: str(getattr(candle, k)) for k in ("open", "high", "low", "close", "volume", "turnover", "previous_close")},
        )
        for candle, issues in candle_issues
        for issue in issues
    )


def previous_closes(before: date, lookback_days=30):
    """Latest daily close strictly before ``before``, by symbol."""
    rows = (
        Candle.objects.filter(
            timeframe=Candle.Timeframe.DAILY,
            trading_date__lt=before,
            trading_date__gte=before - timedelta(days=lookback_days),
        )
        .order_by("instrument_id", "-trading_date")
        .values_list("instrument__symbol", "close")
    )
    closes = {}
    for symbol, close in rows:
        closes.setdefault(symbol, close)
    return closes


def symbols_with_corporate_action(around: date, days=7):
    return frozenset(
        CorporateAction.objects.filter(book_close_date__range=(around - timedelta(days=days), around + timedelta(days=days))).values_list(
            "instrument__symbol", flat=True
        )
    )


def to_entity(row: Candle) -> entities.Candle:
    return entities.Candle(
        symbol=row.instrument.symbol,
        timeframe=entities.Timeframe(row.timeframe),
        ts=row.ts,
        trading_date=row.trading_date,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        volume=row.volume,
        previous_close=row.previous_close,
        turnover=row.turnover,
        trades=row.trades,
    )


def latest_snapshot():
    """The most recent intraday snapshot (all symbols sharing the newest 3H timestamp)."""
    newest = Candle.objects.filter(timeframe=Candle.Timeframe.INTRADAY_3H).order_by("-ts").values_list("ts", flat=True).first()
    if newest is None:
        return []
    rows = Candle.objects.select_related("instrument").filter(timeframe=Candle.Timeframe.INTRADAY_3H, ts=newest)
    return [to_entity(r) for r in rows]


def candles(symbol, timeframe, start=None, end=None):
    qs = Candle.objects.select_related("instrument").filter(instrument__symbol=symbol.upper(), timeframe=timeframe)
    if start:
        qs = qs.filter(trading_date__gte=start)
    if end:
        qs = qs.filter(trading_date__lte=end)
    return qs.order_by("ts")


def count_for_run(run):
    return Candle.objects.filter(run=run).count()
