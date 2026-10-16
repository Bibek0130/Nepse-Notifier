from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from modules.analysis.application import quant
from modules.analysis.domain import evaluation as ev
from modules.analysis.domain import indicators as ind
from modules.analysis.domain.engine import analyze
from modules.analysis.domain.entities import Direction, Signal
from modules.analysis.infrastructure.models import AnalysisRun, Prediction, QuantEvaluation, QuantStrategy
from modules.analysis.tests.test_backtest import seed
from modules.analysis.tests.test_strategies import series, signals


def uptrend_with_dip():
    """300 bars rising ~0.3%/day (well above the 240-day average), then a sharp four-day drop."""
    closes = [100 * 1.003 ** i for i in range(300)]
    for k in range(4):
        closes.append(closes[-1] * 0.96)
    return closes


class IndicatorTests(SimpleTestCase):
    def test_zscore(self):
        z = ind.zscore([1.0, 2.0, 3.0, 4.0, 10.0], 5)
        self.assertEqual(z[:4], [None] * 4)
        self.assertAlmostEqual(z[-1], 6 / 10 ** 0.5)  # mean 4, variance 10
        self.assertEqual(ind.zscore([5.0] * 5, 5)[-1], 0.0)


class QuantStrategyTests(SimpleTestCase):
    def test_reversion_buys_a_dip_in_an_uptrend(self):
        closes = uptrend_with_dip()
        fired = [end for end in range(290, len(closes) + 1) if signals(analyze(series(closes[:end])), "quant_reversion")]
        self.assertTrue(fired)
        first = fired[0]
        s = signals(analyze(series(closes[:first])), "quant_reversion")[0]
        close = closes[first - 1]
        self.assertEqual(s.direction, Direction.BULLISH)
        self.assertLess(s.values["stop"], close)
        self.assertGreaterEqual(s.values["stop"], round(close * 0.92, 2))
        self.assertAlmostEqual(s.values["target"], close + 4.5 * (close - s.values["stop"]), delta=0.1)
        # Cooldown: the oversold day right after doesn't fire again.
        self.assertNotIn(first + 1, fired)

    def test_reversion_needs_the_long_term_uptrend(self):
        closes = [400 * 0.997 ** i for i in range(300)]
        for k in range(4):
            closes.append(closes[-1] * 0.96)
        self.assertEqual(signals(analyze(series(closes)), "quant_reversion"), [])

    def test_quiet_without_240_days_of_history(self):
        closes = uptrend_with_dip()[-200:]
        result = analyze(series(closes))
        self.assertEqual(signals(result, "quant_reversion") + signals(result, "quant_momentum"), [])

    def test_momentum_buys_rsi_breakout_above_the_trend(self):
        # Long rise, a pullback that cools RSI, then a strong push back up.
        closes = [100 * 1.002 ** i for i in range(280)]
        closes += [closes[-1] * 0.99 ** (k + 1) for k in range(10)]
        closes += [closes[-1] * 1.02 ** (k + 1) for k in range(8)]
        hits = [(end, s) for end in range(285, len(closes) + 1) for s in signals(analyze(series(closes[:end])), "quant_momentum")]
        self.assertTrue(hits)
        end, s = hits[0]
        close = closes[end - 1]
        self.assertEqual(s.direction, Direction.BULLISH)
        self.assertAlmostEqual(s.values["stop"], close * 0.96, delta=0.01)
        self.assertEqual(len(hits), 1)  # cooldown and the cross-only trigger keep it to one call

    def test_momentum_exit_below_the_trend(self):
        closes = [100.0] * 250 + [101.0] * 20 + [90.0]
        result = signals(analyze(series(closes)), "quant_momentum")
        self.assertEqual([s.direction for s in result], [Direction.BEARISH])


def trade(edge, correct=None, outcome="horizon", target=None, actual=None, day=0, direction="bullish", horizon=10):
    d = date(2026, 1, 1) + timedelta(days=day)
    ret = edge if direction == "bullish" else -edge
    return ev.Trade("A", d, direction, 100.0, target, None, horizon, outcome, d + timedelta(days=5), 100 + ret, 5,
                    ret, edge, edge > 0 if correct is None else correct, actual)


class MetricTests(SimpleTestCase):
    def test_accuracy_returns_and_forecast_error(self):
        replay = ev.Replay(trades=[
            trade(10, outcome="target", target=110, actual=112, day=0),
            trade(-4, outcome="stop", target=110, actual=99, day=1),
            trade(6, day=2), trade(-2, day=3),
        ], open_calls=1, bars=100, analysis_seconds=0.2, strategy_seconds=0.01, baseline={10: [1.0, -1.0, 2.0, -2.0]})
        m = ev.metrics(replay, date(2026, 1, 1), date(2027, 1, 1))
        self.assertEqual((m["calls"], m["settled"], m["open"]), (5, 4, 1))
        self.assertEqual(m["accuracy"]["hit_rate"], 50.0)
        self.assertEqual(m["accuracy"]["chance_hit_rate"], 50.0)
        self.assertEqual(m["accuracy"]["targets_hit_pct"], 25.0)
        self.assertEqual(m["returns"]["profit_factor"], 2.67)  # 16 / 6
        self.assertEqual(m["returns"]["avg_return_pct"], 2.5)
        self.assertEqual(m["returns"]["edge_vs_baseline_pct"], 2.5)
        f = m["forecast_error"]
        # Errors: (112-110)/110 = +1.82%, (99-110)/110 = -10%.
        self.assertEqual((f["samples"], f["target_reached_pct"], f["mae_pct"], f["bias_pct"]), (2, 50.0, 5.91, -4.09))
        self.assertEqual(m["speed"]["analysis_ms_per_bar"], 2.0)
        self.assertLess(m["risk"]["max_drawdown_pct"], 0)
        self.assertEqual(m["risk"]["monte_carlo"]["runs"], ev.MONTE_CARLO_RUNS)

    def test_significance(self):
        self.assertLess(ev.p_value(90, [0.5] * 100), 0.001)
        self.assertGreater(ev.p_value(51, [0.5] * 100), 0.5)
        low, high = ev.wilson_interval(50, 100)
        self.assertTrue(low < 50 < high)

    def test_drawdown(self):
        self.assertEqual(ev.max_drawdown([1.0, 1.2, 0.9, 1.3]), -25.0)

    def test_empty(self):
        m = ev.metrics(ev.Replay(trades=[], baseline={}))
        self.assertEqual((m["settled"], m["accuracy"]["hit_rate"], m["risk"]["monte_carlo"]), (0, None, None))

    def test_replay_scores_calls_like_live_predictions(self):
        closes = [100 + i for i in range(60)]

        def always(ctx):
            return [Signal("always", Direction.BULLISH, 2, "x", {})]

        replay = ev.replay_strategy([series(closes)], "always", always)
        self.assertEqual(replay.bars, 31)
        self.assertEqual(len(replay.trades) + replay.open_calls, 31)
        self.assertEqual(replay.open_calls, 10)  # the last 10 days can't settle at a 10-session horizon
        self.assertTrue(all(t.correct for t in replay.trades))
        self.assertGreater(replay.analysis_seconds, 0)


class QuantAdminTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin", "a@example.com", "pw"))
        seed("CLIMB", [100 + i * 0.8 for i in range(120)], date(2026, 6, 1))

    def test_section_lists_every_strategy(self):
        index = self.client.get("/admin/").content.decode()
        self.assertIn("Quant", index)
        page = self.client.get("/admin/quant/quantstrategy/").content.decode()
        for name in ("quant_momentum", "quant_reversion", "ema_5_8_13", "pairs"):
            self.assertIn(name, page)

    def test_evaluate_from_the_strategy_page(self):
        self.client.get("/admin/quant/quantstrategy/")  # creates the rows
        strategy = QuantStrategy.objects.get(name="forecast")
        url = f"/admin/quant/quantstrategy/{strategy.pk}/change/"
        self.assertContains(self.client.get(url), "Not evaluated yet")
        with mock.patch("modules.analysis.quant.admin.dispatch", side_effect=quant.run_evaluation):
            response = self.client.post(url, {"days": "90", "symbols": ""})
        self.assertEqual(response.status_code, 302)
        evaluation = QuantEvaluation.objects.get()
        self.assertEqual((evaluation.status, evaluation.symbols_tested), ("ok", 1))
        self.assertGreater(evaluation.metrics["settled"], 0)
        self.assertEqual(evaluation.metrics["accuracy"]["hit_rate"], 100.0)
        self.assertGreater(evaluation.metrics["speed"]["bars_evaluated"], 0)
        page = self.client.get(url).content.decode()
        self.assertIn("Hit rate", page)
        self.assertIn("Mean absolute error", page)
        self.assertIn("Analysis time per bar", page)
        listing = self.client.get("/admin/quant/quantstrategy/").content.decode()
        self.assertIn("100%", listing)

    def test_repeated_clicks_start_one_evaluation(self):
        self.client.get("/admin/quant/quantstrategy/")
        url = f"/admin/quant/quantstrategy/{QuantStrategy.objects.get(name='forecast').pk}/change/"
        with mock.patch("modules.analysis.quant.admin.dispatch") as dispatch:
            for _ in range(3):
                self.assertEqual(self.client.post(url, {"days": "90"}).status_code, 302)
        dispatch.assert_called_once()
        self.assertEqual(QuantEvaluation.objects.count(), 1)
        page = self.client.get(url).content.decode()
        self.assertIn("already being evaluated", page)
        self.assertIn("Evaluation running", page)
        self.assertIn('title="An evaluation is already running"', page)

    def test_stale_running_evaluation_does_not_block(self):
        stuck = quant.start_evaluation("forecast", days=90)
        with self.assertRaises(quant.EvaluationRunning):
            quant.start_evaluation("forecast", days=90)
        QuantEvaluation.objects.filter(pk=stuck.pk).update(started_at=stuck.started_at - timedelta(hours=2))
        self.assertNotEqual(quant.start_evaluation("forecast", days=90).pk, stuck.pk)
        stuck.refresh_from_db()
        self.assertEqual(stuck.status, "failed")
        quant.start_evaluation("ema_5_8_13", days=90)  # other strategies aren't blocked

    def test_admin_pages_disable_buttons_while_submitting(self):
        for url in ("/admin/", "/admin/quant/quantstrategy/"):
            self.assertContains(self.client.get(url), "busy-spinner")

    def test_cross_sectional_strategy_uses_live_predictions(self):
        run = AnalysisRun.objects.create(ingestion_run_id=1, timeframe="1D", trading_date=date(2026, 9, 1))
        Prediction.objects.create(run=run, symbol="CLIMB", strategy="pairs", direction="bullish", strength=2,
                                  made_on=date(2026, 9, 1), entry_price=100, horizon=10, outcome="target",
                                  exit_date=date(2026, 9, 3), exit_price=105, sessions=2, return_pct=5.0, correct=True)
        evaluation = quant.run_evaluation(quant.start_evaluation("pairs", days=90, end=date(2026, 9, 30)).pk)
        self.assertEqual(evaluation.metrics, {})
        self.assertEqual((evaluation.live["settled"], evaluation.live["accuracy"]["hit_rate"]), (1, 100.0))


class StrategiesApiTests(TestCase):
    def test_paper_strategies_come_first_with_latest_evaluation(self):
        seed("CLIMB", [100 + i * 0.8 for i in range(120)], date(2026, 6, 1))
        quant.run_evaluation(quant.start_evaluation("forecast", days=90, end=date(2026, 9, 28)).pk)
        body = self.client.get("/api/analysis/strategies").json()
        names = [s["name"] for s in body["strategies"]]
        self.assertEqual(names[:3], ["quant_momentum", "quant_reversion", "pca_leaders"])
        self.assertEqual(len(names), 13)
        forecast = next(s for s in body["strategies"] if s["name"] == "forecast")
        self.assertEqual(forecast["evaluation"]["replay"]["hit_rate"], 100.0)
        self.assertTrue(forecast["enabled"])
        self.assertIsNotNone(forecast["admin_id"])
        self.assertIsNone(body["strategies"][0]["evaluation"])
        self.assertEqual(body["strategies"][0]["today"], {"count": 0, "signals": []})


class HistoryWindowTests(SimpleTestCase):
    def test_loaded_history_covers_the_trend_average(self):
        """Live runs and replays must load enough calendar days for the 240-session trend, or the quant strategies stay silent."""
        from modules.analysis.application import backtest, series as series_module
        from modules.analysis.domain.strategies import StrategyConfig

        cfg = StrategyConfig()
        needed = cfg.quant_trend_period + max(cfg.quant_momentum_cooldown, cfg.quant_reversion_cooldown) + 1
        for days in (series_module.HISTORY_DAYS, backtest.WARMUP_DAYS):
            sessions = days * 5 / 7 - 40 * days / 365  # Sun-Thu trading, minus a generous count of holidays
            self.assertGreaterEqual(sessions, needed, days)
