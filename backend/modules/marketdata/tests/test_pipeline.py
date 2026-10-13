from datetime import date, datetime
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.test import TestCase, override_settings

from modules.marketdata.application.backfill import backfill_history
from modules.marketdata.application.ingest import ingest_market
from modules.marketdata.domain.entities import HistoricalBar, Quote
from modules.marketdata.domain.ports import RawResponse, SourceError
from modules.marketdata.infrastructure import circuit_breaker
from modules.marketdata.infrastructure.models import Candle, CandleIssue, IngestionRun, RawPayload
from modules.shared.models import TradingHoliday

NPT = ZoneInfo("Asia/Kathmandu")
MONDAY_1415 = datetime(2026, 10, 12, 14, 15, tzinfo=NPT)
SATURDAY = datetime(2026, 10, 17, 14, 15, tzinfo=NPT)

GOOD = Quote("NABIL", Decimal("510"), Decimal("500"), Decimal("512.5"), Decimal("498"), Decimal("502"), Decimal("1.59"), 1000, Decimal("505000"), 50)
UPPER = Quote("UPPER", Decimal("201.3"), volume=9870, previous_close=Decimal("203"))
BAD = Quote("BROKEN", Decimal("100"), Decimal("100"), Decimal("90"), Decimal("95"))  # high below open


class FakeSource:
    def __init__(self, name, quotes=(), fail=None, body=None):
        self.name = name
        self.quotes = list(quotes)
        self.fail = fail
        self.body = body or f"{name}:" + ",".join(q.symbol for q in self.quotes)
        self.fetches = 0

    def fetch_raw(self):
        self.fetches += 1
        if self.fail == "fetch":
            raise SourceError(f"{self.name}: down")
        return RawResponse(self.name, f"https://{self.name}.test/", self.body)

    def parse(self, body):
        if self.fail == "parse":
            raise SourceError(f"{self.name}: layout changed")
        return self.quotes


class IngestTests(TestCase):
    def setUp(self):
        cache.clear()

    def run_ingest(self, *sources, kind="intraday", now=MONDAY_1415, force=False):
        with mock.patch("celery.current_app.send_task") as send_task, self.captureOnCommitCallbacks(execute=True):
            run = ingest_market(kind, sources=list(sources), now=now, force=force)
        self.send_task = send_task
        return run

    def test_happy_path_runs_every_stage(self):
        run = self.run_ingest(FakeSource("primary", [GOOD, UPPER]))

        self.assertEqual((run.status, run.source, run.fetched, run.accepted), ("ok", "primary", 2, 2))
        self.assertEqual(set(run.stages), {"schedule", "fetch", "land_raw", "normalise", "validate", "persist", "cache"})
        self.assertEqual(Candle.objects.filter(timeframe="3H").count(), 2)
        self.assertFalse(Candle.objects.filter(timeframe="1D").exists())
        self.assertEqual(RawPayload.objects.count(), 1)
        self.assertEqual([r["symbol"] for r in cache.get("marketdata:latest_quotes")], ["NABIL", "UPPER"])
        self.send_task.assert_called_once()
        name, = self.send_task.call_args.args
        self.assertEqual(name, "modules.analysis.tasks.on_candles_ingested")
        self.assertEqual(self.send_task.call_args.kwargs["kwargs"]["symbols"], ["NABIL", "UPPER"])

    def test_end_of_day_writes_daily_bars_and_is_idempotent(self):
        self.run_ingest(FakeSource("primary", [GOOD, UPPER]), kind="eod")
        self.run_ingest(FakeSource("primary", [GOOD, UPPER]), kind="eod", force=True)
        daily = Candle.objects.filter(timeframe="1D")
        self.assertEqual(daily.count(), 2)
        self.assertEqual(daily.get(instrument__symbol="UPPER").open, Decimal("201.3"))
        self.assertEqual(daily.first().trading_date, date(2026, 10, 12))

    def test_bad_candle_is_quarantined_not_fatal(self):
        run = self.run_ingest(FakeSource("primary", [GOOD, BAD]))
        self.assertEqual((run.status, run.accepted, run.quarantined), ("partial", 1, 1))
        issue = CandleIssue.objects.get()
        self.assertEqual((issue.symbol, issue.rule), ("BROKEN", "ohlc_consistent"))
        self.assertFalse(Candle.objects.filter(instrument__symbol="BROKEN").exists())

    def test_falls_back_when_primary_fetch_or_parse_fails(self):
        run = self.run_ingest(FakeSource("down", fail="fetch"), FakeSource("changed", [GOOD], fail="parse"), FakeSource("backup", [GOOD]))
        self.assertEqual((run.status, run.source), ("ok", "backup"))
        self.assertEqual(len(run.stages["fetch"]["errors"]), 2)  # down + layout changed

    def test_all_sources_failing_marks_run_failed(self):
        with self.assertRaises(SourceError):
            self.run_ingest(FakeSource("a", fail="fetch"), FakeSource("b", fail="fetch"))
        run = IngestionRun.objects.get()
        self.assertEqual(run.status, "failed")
        self.assertIn("a: down", run.error)

    def test_unchanged_source_is_stale(self):
        self.run_ingest(FakeSource("primary", [GOOD]))
        run = self.run_ingest(FakeSource("primary", [GOOD]))
        self.assertEqual(run.status, "stale")
        self.assertEqual(Candle.objects.count(), 1)

    def test_market_closed_is_skipped_without_fetching(self):
        source = FakeSource("primary", [GOOD])
        self.assertEqual(self.run_ingest(source, now=SATURDAY).status, "skipped")
        TradingHoliday.objects.create(date=date(2026, 10, 12))
        self.assertEqual(self.run_ingest(source).status, "skipped")
        self.assertEqual(source.fetches, 0)

    def test_force_runs_on_closed_day(self):
        self.assertEqual(self.run_ingest(FakeSource("primary", [GOOD]), now=SATURDAY, force=True).status, "ok")

    def test_concurrent_run_is_skipped(self):
        cache.add("lock:marketdata:ingest", "other-worker", 60)
        run = self.run_ingest(FakeSource("primary", [GOOD]))
        self.assertEqual(run.status, "skipped")
        self.assertEqual(run.stages["schedule"]["reason"], "another run in progress")

    @override_settings(MARKETDATA={"CIRCUIT_FAILURE_THRESHOLD": 2, "CIRCUIT_OPEN_SECONDS": 60, "INGEST_LOCK_SECONDS": 60,
                                   "PRICE_BAND_PERCENT": 10, "CROSS_SOURCE_TOLERANCE_PERCENT": 0.5, "CACHE_TTL_SECONDS": 60})
    def test_circuit_breaker_skips_failing_source(self):
        flaky = FakeSource("flaky", fail="fetch")
        for _ in range(2):
            with self.assertRaises(SourceError):
                self.run_ingest(flaky, force=True)
        self.assertTrue(circuit_breaker.is_open("flaky"))
        with self.assertRaises(SourceError):
            self.run_ingest(flaky, force=True)
        self.assertEqual(flaky.fetches, 2)  # third run never called it

    def test_eod_cross_checks_against_second_source(self):
        lagging = Quote("NABIL", Decimal("480"), volume=10)
        self.run_ingest(FakeSource("primary", [GOOD]), FakeSource("secondary", [lagging]), kind="eod")
        self.assertTrue(CandleIssue.objects.filter(rule="cross_source", severity="flag").exists())


class FakeHistory:
    name = "history"

    def __init__(self, bars):
        self.bars = bars

    def fetch_history(self, symbol, start, end):
        if symbol not in self.bars:
            raise SourceError("unknown symbol")
        return self.bars[symbol]


class BackfillTests(TestCase):
    def test_backfill_loads_and_skips(self):
        bars = {
            "NABIL": [
                HistoricalBar(date(2026, 10, 11), Decimal("500"), Decimal("510"), Decimal("495"), Decimal("505"), 1000),
                HistoricalBar(date(2026, 10, 12), Decimal("505"), Decimal("500"), Decimal("500"), Decimal("512"), 2000),  # bad
            ]
        }
        with mock.patch("celery.current_app.send_task") as send_task, self.captureOnCommitCallbacks(execute=True):
            run = backfill_history(["NABIL", "GHOST"], days=30, source=FakeHistory(bars))

        self.assertEqual((run.status, run.accepted, run.quarantined), ("partial", 1, 1))
        self.assertIn("GHOST", run.error)
        self.assertEqual(Candle.objects.filter(timeframe="1D").count(), 1)
        send_task.assert_called_once()
