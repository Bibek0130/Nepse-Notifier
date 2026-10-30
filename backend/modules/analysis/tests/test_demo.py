"""The hosted demo's build steps, end to end on the synthetic market: seed, evaluate, backtest, verify."""
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from modules.analysis.application import quant
from modules.analysis.domain.strategies import DESCRIPTIONS
from modules.analysis.infrastructure.models import AnalysisRun, Prediction, QuantEvaluation
from modules.marketdata import public as marketdata
from modules.marketdata.application.demo import seed_demo
from modules.marketdata.domain.entities import HistoricalBar
from modules.marketdata.domain.ports import SourceError
from modules.marketdata.infrastructure.models import Instrument

from . import market


class FakeArchive:
    """Serves the synthetic market as the price archive would, plus one symbol it doesn't have."""

    name = "nepse_data"

    def __init__(self):
        self.data = market.bars()

    def fetch_history(self, symbol, start, end):
        if symbol not in self.data:
            raise SourceError(f"nepse_data: no CSV for {symbol}")
        return [HistoricalBar(c.trading_date, c.open, c.high, c.low, c.close, c.volume) for c in self.data[symbol]]


@override_settings(EVENTS_RUN_INLINE=True)  # as in the demo settings: each session is analysed before the next
class DemoBuildTests(TestCase):
    def setUp(self):
        self.archive = FakeArchive()
        self.end = self.archive.data["BNK1"][-1].trading_date
        self.sectors = {**market.sectors(), "GONE": "Finance"}

    def seed(self, replay_sessions=3, sectors=None):
        with self.captureOnCommitCallbacks(execute=True):
            return seed_demo(sectors or self.sectors, replay_sessions=replay_sessions, source=self.archive)

    def test_seed_loads_prices_snapshot_and_analyses_latest_sessions(self):
        run, replayed = self.seed()

        self.assertEqual(run.status, "partial")  # GONE failed, the rest loaded
        self.assertIn("GONE", run.error)
        self.assertEqual(Instrument.objects.get(symbol="HYD2").sector, "Hydropower")
        self.assertEqual(len(marketdata.get_candles("BNK1")), market.SESSIONS)

        # The dashboard's quotes and summary: the last close with its change from the session before.
        quotes = {q["symbol"]: q for q in marketdata.get_latest_quotes()}
        self.assertEqual(set(quotes), set(market.sectors()))
        bnk1 = self.archive.data["BNK1"]
        self.assertEqual(quotes["BNK1"]["close"], str(bnk1[-1].close))
        self.assertEqual(quotes["BNK1"]["previous_close"], str(bnk1[-2].close))
        self.assertIsNotNone(quotes["BNK1"]["change_percent"])
        self.assertEqual(marketdata.get_market_summary()["symbols"], len(market.sectors()))

        # The latest sessions were analysed in order, as closing (not provisional) runs.
        self.assertEqual(replayed, [c.trading_date for c in bnk1[-3:]])
        runs = list(AnalysisRun.objects.order_by("pk"))
        self.assertEqual([r.trading_date for r in runs], replayed)
        self.assertTrue(all(r.status == "ok" and not r.provisional and r.symbols_analyzed == len(market.sectors()) for r in runs))
        self.assertTrue(Prediction.objects.exists())

    def test_seeding_twice_does_not_duplicate_anything(self):
        self.seed(replay_sessions=1)
        self.seed(replay_sessions=1)
        self.assertEqual(len(marketdata.get_candles("BNK1")), market.SESSIONS)
        self.assertEqual(len(marketdata.get_latest_quotes()), len(market.sectors()))

    def test_nothing_loaded_fails_without_analysing(self):
        run, replayed = self.seed(sectors={"GONE": ""})
        self.assertEqual((run.status, replayed), ("failed", []))
        self.assertFalse(AnalysisRun.objects.exists())

    def test_full_build_leaves_no_blank_metric(self):
        out = StringIO()
        with self.assertRaises(CommandError) as empty:
            call_command("verify_demo", stdout=out)
        self.assertIn("no latest quotes", str(empty.exception))

        self.seed()
        with mock.patch.object(quant, "timezone", wraps=quant.timezone) as tz:
            tz.localdate.return_value = self.end
            call_command("evaluate_strategies", "--days", "730", stdout=out)
        call_command("backtest", "--end", self.end.isoformat(), stdout=out)
        call_command("verify_demo", stdout=out)
        self.assertIn(f"{len(DESCRIPTIONS)} strategies measured", out.getvalue())

        # A strategy whose evaluation found nothing to measure fails the build.
        QuantEvaluation.objects.filter(strategy="macd").update(metrics={"calls": 0}, live={})
        with self.assertRaises(CommandError) as blank:
            call_command("verify_demo", stdout=StringIO())
        self.assertIn("macd: no calls in this period", str(blank.exception))
