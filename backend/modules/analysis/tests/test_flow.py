from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import TestCase
from rest_framework.test import APIClient

from modules.analysis import public
from modules.analysis.application import predictions
from modules.analysis.infrastructure.models import AnalysisRun, Prediction, Signal, StrategySetting
from modules.analysis.tasks import on_candles_ingested
from modules.marketdata.domain.entities import Candle, Timeframe
from modules.marketdata.infrastructure import repositories as market_repo

NPT = ZoneInfo("Asia/Kathmandu")
TODAY = date(2026, 10, 12)


def daily(symbol, closes, volumes):
    start = TODAY - timedelta(days=len(closes) - 1)
    out = []
    for i, (c, v) in enumerate(zip(closes, volumes)):
        d = start + timedelta(days=i)
        price = Decimal(str(round(c, 2)))
        out.append(Candle(symbol, Timeframe.DAILY, datetime.combine(d, time.min, tzinfo=NPT), d,
                          price, price + 1, price - 1, price, int(v), None, None, 20))
    return out


class AnalysisFlowTests(TestCase):
    def setUp(self):
        # SPIKE: flat then a volume spike today. FLAT: nothing happening. NEW: too little history.
        market_repo.upsert_candles(daily("SPIKE", [100.0] * 59 + [101.0], [1000] * 59 + [5000]))
        market_repo.upsert_candles(daily("FLAT", [100.0] * 60, [1000] * 60))
        market_repo.upsert_candles(daily("NEW", [100.0] * 5, [1000] * 5))

    def run_analysis(self, timeframe="1D"):
        with mock.patch("modules.analysis.application.run.events.publish") as publish:
            run_id = on_candles_ingested.delay(7, timeframe, TODAY.isoformat(), ["FLAT", "NEW", "SPIKE"]).get()
        return AnalysisRun.objects.get(pk=run_id), publish

    def test_end_to_end_from_event_to_signals(self):
        run, publish = self.run_analysis()

        self.assertEqual((run.status, run.symbols_total, run.symbols_analyzed), ("ok", 3, 2))
        self.assertFalse(run.provisional)
        self.assertEqual(set(Signal.objects.values_list("symbol", flat=True)), {"SPIKE"})
        self.assertTrue(Signal.objects.filter(symbol="SPIKE", strategy="volume").exists())
        publish.assert_called_once()
        event = publish.call_args.args[0]
        self.assertEqual((event.analysis_run_id, event.signals_count), (run.pk, run.signals_count))

        report = public.get_run_report(run.pk)
        self.assertEqual(list(report["analyses"]), ["SPIKE"])
        self.assertEqual(report["signals"][0]["symbol"], "SPIKE")

    def test_intraday_run_uses_snapshot_as_provisional_bar(self):
        snapshot_ts = datetime(2026, 10, 13, 14, 15, tzinfo=NPT)
        p = Decimal("130")
        market_repo.upsert_candles([Candle("FLAT", Timeframe.INTRADAY_3H, snapshot_ts, date(2026, 10, 13), p, p, p, p, 900, Decimal("100"))])
        with mock.patch("modules.analysis.application.run.events.publish"):
            run_id = on_candles_ingested.delay(8, "3H", "2026-10-13", ["FLAT"]).get()
        latest = public.get_latest_analysis("FLAT")
        self.assertTrue(AnalysisRun.objects.get(pk=run_id).provisional)
        self.assertTrue(latest["provisional"])
        self.assertEqual(latest["indicators"]["close"], 130.0)

    def test_one_failing_symbol_does_not_block_the_run(self):
        with mock.patch("modules.analysis.application.run.load_series", side_effect=RuntimeError("boom")):
            run, _ = self.run_analysis()
        self.assertEqual((run.status, run.symbols_analyzed), ("ok", 0))

    def test_api(self):
        run, _ = self.run_analysis()
        client = APIClient()
        data = client.get("/api/analysis/signals").json()
        self.assertEqual(data["run_id"], run.pk)
        self.assertTrue(all(s["symbol"] == "SPIKE" for s in data["signals"]))
        bearish = client.get("/api/analysis/signals", {"direction": "bearish"}).json()["signals"]
        self.assertTrue(bearish and all(s["direction"] == "bearish" for s in bearish))  # RSI pinned at 100 reads overbought
        self.assertEqual(client.get("/api/analysis/signals", {"direction": "neutral"}).json()["signals"], [])
        self.assertEqual(client.get("/api/analysis/symbols/spike").json()["symbol"], "SPIKE")
        self.assertEqual(client.get("/api/analysis/symbols/NOPE").status_code, 404)


class StrategySelectionAndPredictionTests(TestCase):
    def setUp(self):
        market_repo.upsert_candles(daily("SPIKE", [100.0] * 59 + [101.0], [1000] * 59 + [5000]))

    def run_analysis(self, timeframe="1D"):
        with mock.patch("modules.analysis.application.run.events.publish"):
            return on_candles_ingested.delay(7, timeframe, TODAY.isoformat(), ["SPIKE"]).get()

    def test_disabled_strategy_does_not_run(self):
        self.run_analysis()
        self.assertTrue(StrategySetting.objects.filter(name="pairs", enabled=True).exists())  # rows created on first run
        StrategySetting.objects.filter(name="volume").update(enabled=False)
        Signal.objects.all().delete()
        self.run_analysis()
        self.assertFalse(Signal.objects.filter(strategy="volume").exists())

    def test_prediction_recorded_then_settled_against_later_prices(self):
        self.run_analysis()
        p = Prediction.objects.get(strategy="volume")
        self.assertEqual((p.symbol, p.direction, p.entry_price, p.made_on, p.outcome), ("SPIKE", "bullish", Decimal("101.00"), TODAY, ""))
        self.run_analysis()  # re-running the same day does not duplicate it
        self.assertEqual(Prediction.objects.filter(strategy="volume").count(), 1)

        later = [TODAY + timedelta(days=i) for i in range(1, 11)]
        market_repo.upsert_candles([
            Candle("SPIKE", Timeframe.DAILY, datetime.combine(d, time.min, tzinfo=NPT), d, Decimal(p_), Decimal(p_) + 1, Decimal(p_) - 1, Decimal(p_), 1000, None, None, 20)
            for d, p_ in zip(later, range(102, 112))
        ])
        self.assertGreaterEqual(predictions.settle_predictions(), 1)
        p.refresh_from_db()
        self.assertEqual((p.outcome, p.exit_price, p.correct, p.sessions), ("horizon", Decimal("111.00"), True, 10))

        card = APIClient().get("/api/analysis/scorecard", {"days": 3650}).json()
        volume = next(r for r in card["strategies"] if r["strategy"] == "volume")
        self.assertEqual((volume["settled"], volume["hit_rate"]), (1, 100.0))

    def test_intraday_runs_make_no_predictions(self):
        self.run_analysis("3H")
        self.assertFalse(Prediction.objects.exists())


class PairsFlowTests(TestCase):
    def test_pairs_signal_from_full_run(self):
        from .test_stat_arb import cointegrated_pair

        a, b = cointegrated_pair()
        market_repo.upsert_candles(daily("PAIRA", a, [1000] * len(a)))
        market_repo.upsert_candles(daily("PAIRB", b, [1000] * len(b)))
        with mock.patch("modules.analysis.application.run.events.publish"):
            on_candles_ingested.delay(8, "1D", TODAY.isoformat(), ["PAIRA", "PAIRB"]).get()
        pairs = dict(Signal.objects.filter(strategy="pairs").values_list("symbol", "direction"))
        self.assertEqual(pairs, {"PAIRA": "bearish", "PAIRB": "bullish"})
        self.assertTrue(Prediction.objects.filter(strategy="pairs", symbol="PAIRB", target_price__isnull=False).exists())


class StrategyAdminTests(TestCase):
    def test_switches_listed_before_any_run(self):
        from django.contrib.auth.models import User

        self.client.force_login(User.objects.create_superuser("admin", "a@example.com", "pw"))
        response = self.client.get("/admin/analysis/strategysetting/")
        self.assertContains(response, "pairs")
        self.assertContains(response, "ema_5_8_13")
        self.assertEqual(StrategySetting.objects.count(), 10)
