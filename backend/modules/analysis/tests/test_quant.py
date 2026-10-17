from dataclasses import replace
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from modules.analysis.application import quant
from modules.analysis.domain import evaluation as ev
from modules.analysis.domain import indicators as ind
from modules.analysis.domain.engine import analyze
from modules.analysis.domain.entities import Direction, Signal
from modules.analysis.domain.strategies import DESCRIPTIONS
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
        self.assertEqual((m["risk"]["max_drawdown_pct"], m["risk"]["total_return_pct"]), (None, None))  # not a flat 0%
        self.assertEqual(quant.missing_metrics(m), "no calls in this period")
        m["history"] = {"longest_sessions": 120, "sessions_needed": 241}
        self.assertEqual(quant.missing_metrics(m), "no calls: needs 241 sessions of history, the longest saved is 120")
        self.assertEqual(quant.missing_metrics(ev.metrics(ev.Replay(trades=[], open_calls=3, baseline={}))), "3 calls, none settled yet")
        self.assertEqual(quant.missing_metrics({}), "not measured")

    def test_all_losses_give_a_profit_factor_of_zero(self):
        m = ev.metrics(ev.Replay(trades=[trade(-3, day=0), trade(-1, day=1), trade(-2, day=2)], baseline={10: [1.0, -1.0]}))
        self.assertEqual((m["accuracy"]["hit_rate"], m["returns"]["profit_factor"]), (0.0, 0.0))
        self.assertIsNotNone(m["accuracy"]["p_value"])
        self.assertEqual(quant.missing_metrics(m), "")

    def test_all_wins_explain_the_missing_profit_factor(self):
        m = ev.metrics(ev.Replay(trades=[trade(3, day=0), trade(1, day=1)], baseline={10: [1.0, -1.0]}))
        self.assertEqual((m["accuracy"]["hit_rate"], m["returns"]["profit_factor"]), (100.0, None))
        self.assertEqual(quant.missing_metrics(m), "no losing calls, so profit factor is unbounded")

    def test_p_value_when_history_only_ever_rose(self):
        """A baseline that rose every day used to make chance a certainty and the p-value blank."""
        m = ev.metrics(ev.Replay(trades=[trade(3, day=0), trade(-1, day=1), trade(2, day=2)], baseline={10: [1.0] * 50}))
        self.assertIsNotNone(m["accuracy"]["p_value"])
        self.assertLess(m["accuracy"]["chance_hit_rate"], 100.0)

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

    def test_cross_sectional_replay_trades_a_stretched_pair(self):
        from modules.analysis.domain import stat_arb
        from modules.analysis.tests.test_stat_arb import cointegrated_pair

        a, b = cointegrated_pair(n=150, stretch=3.3)
        a, b = a + [a[-1]] * 20, b + [b[-1]] * 20  # the stretch on bar 150, then 20 quiet bars to settle it
        pair = {"A": replace(series(a), symbol="A"), "B": replace(series(b), symbol="B")}

        def scan(windows):
            return stat_arb.scan({s: v.dates for s, v in windows.items()}, {s: v.closes for s, v in windows.items()}, {"g": list(windows)})

        day = pair["A"].dates[149]
        replay = ev.replay_cross_section(pair, "pairs", scan, start=day, end=day)
        self.assertEqual(replay.bars, 2)  # both stocks traded that day
        self.assertEqual(sorted((t.symbol, t.direction) for t in replay.trades), [("A", "bearish"), ("B", "bullish")])
        self.assertTrue(all(t.made_on == day for t in replay.trades))
        self.assertEqual(ev.replay_cross_section(pair, "basket_reversion", scan, start=day, end=day).trades, [])


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
        # One stock has no pair to trade, so the replay makes no calls and the list headlines the live record.
        self.assertEqual(evaluation.metrics["calls"], 0)
        self.assertEqual((evaluation.live["settled"], evaluation.live["accuracy"]["hit_rate"]), (1, 100.0))
        self.assertIs(quant.headline(evaluation), evaluation.live)
        listing = self.client.get("/admin/quant/quantstrategy/").content.decode()
        self.assertIn("history replay + live", listing)


class QuantListReasonTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin", "a@example.com", "pw"))

    def row(self, page, name):
        start = page.index(f"<strong>{name}</strong>")
        return page[start:page.index("</tr>", start)]

    def test_blank_metrics_say_why(self):
        seed("SHORT", [100 + i * 0.5 for i in range(120)], date(2026, 6, 1))
        end = date(2026, 9, 28)
        quant.run_evaluation(quant.start_evaluation("quant_momentum", days=90, end=end).pk)
        failed = quant.start_evaluation("macd", days=90, end=end)
        QuantEvaluation.objects.filter(pk=failed.pk).update(status="failed", error="database is locked")
        quant.start_evaluation("rsi", days=90, end=end)  # still running
        page = self.client.get("/admin/quant/quantstrategy/").content.decode()
        self.assertIn("needs 241 sessions of history, the longest saved is 120", self.row(page, "quant_momentum"))
        self.assertIn("last evaluation failed: database is locked", self.row(page, "macd"))
        self.assertIn("evaluating…", self.row(page, "rsi"))
        self.assertIn("not evaluated yet", self.row(page, "trend"))
        self.assertIn("Evaluate all strategies", page)

    def test_evaluate_all(self):
        quant.start_evaluation("rsi")  # already running: not started twice
        with mock.patch("modules.analysis.quant.admin.dispatch_many") as dispatch_many:
            response = self.client.post("/admin/quant/quantstrategy/evaluate-all/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(dispatch_many.call_args.args[0]), len(DESCRIPTIONS) - 1)
        self.assertEqual(QuantEvaluation.objects.filter(strategy="rsi").count(), 1)

    def test_stale_only_redoes_evaluations_that_measured_nothing(self):
        seed("CLIMB", [100 + i * 0.8 for i in range(120)], date(2026, 6, 1))
        quant.run_evaluation(quant.start_evaluation("forecast", days=365).pk)  # settled calls: fresh
        quant.run_evaluation(quant.start_evaluation("quant_momentum", days=365).pk)  # too little history: redo
        names = {ev.strategy for ev in quant.start_all(only_stale_days=7)}
        self.assertNotIn("forecast", names)
        self.assertIn("quant_momentum", names)
        self.assertEqual(len(names), len(DESCRIPTIONS) - 1)


class EveryStrategyIsEvaluatedTests(TestCase):
    """The rule for adding a strategy: it must be measurable. Each one has to make calls on a realistic
    market, have them settled, and get a hit rate, p-value and profit factor out of its evaluation.

    If this fails for a new strategy, make it replayable in ``application.quant`` (per-symbol strategies
    go in ``REGISTRY``, cross-sectional ones in ``CROSS_SECTIONAL`` with a scanner) and check that the
    synthetic market in ``tests/market.py`` gives it the conditions it trades on.
    """

    def test_every_strategy_produces_hit_rate_p_value_and_profit_factor(self):
        from io import StringIO

        from django.core.management import call_command

        from modules.marketdata.infrastructure import repositories as market_repo
        from modules.marketdata.infrastructure.models import Instrument

        from . import market

        data = market.bars()
        for candles in data.values():
            market_repo.upsert_candles(candles)
        for symbol, sector in market.sectors().items():
            Instrument.objects.filter(symbol=symbol).update(sector=sector)
        end = data["BNK1"][-1].trading_date
        with mock.patch.object(quant, "timezone", wraps=quant.timezone) as tz:
            tz.localdate.return_value = end
            out = StringIO()
            call_command("evaluate_strategies", "--days", "730", stdout=out)
        evaluations = {e.strategy: e for e in QuantEvaluation.objects.all()}
        self.assertEqual(set(evaluations), set(DESCRIPTIONS))
        for name, evaluation in evaluations.items():
            with self.subTest(strategy=name):
                self.assertEqual(evaluation.status, "ok", evaluation.error)
                m = evaluation.metrics
                self.assertGreaterEqual(m["settled"], 3, f"{name} made too few settled calls to measure")
                self.assertIsNotNone(m["accuracy"]["hit_rate"])
                self.assertIsNotNone(m["accuracy"]["p_value"])
                self.assertIsNotNone(m["returns"]["profit_factor"], f"{name}: {quant.missing_metrics(m)}")
                self.assertEqual(quant.missing_metrics(m), "")
                self.assertIn(name, out.getvalue())


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


class StoppedEvaluationTests(TestCase):
    """bibek stopped a long evaluate_strategies run with Ctrl+C during pairs: the run must say it stopped and
    leave nothing "running", or admin refuses to evaluate those strategies again for an hour."""

    def setUp(self):
        seed("CLIMB", [100 + i * 0.8 for i in range(150)], date(2026, 5, 1))

    def test_ctrl_c_frees_the_current_and_pending_evaluations(self):
        from io import StringIO

        from django.core.management import call_command

        real = quant.run_evaluation

        def run(pk, progress=None):
            if QuantEvaluation.objects.get(pk=pk).strategy == "pairs":
                with mock.patch.object(evaluation_module(), "replay_cross_section", side_effect=KeyboardInterrupt):
                    return real(pk, progress)
            return real(pk, progress)

        out, err = StringIO(), StringIO()
        with mock.patch.object(quant, "run_evaluation", side_effect=run):
            call_command("evaluate_strategies", "--days", "60", stdout=out, stderr=err)
        self.assertFalse(QuantEvaluation.objects.filter(status="running").exists())
        self.assertEqual(QuantEvaluation.objects.get(strategy="pairs").error, "Stopped before it finished")
        self.assertEqual(QuantEvaluation.objects.get(strategy="forecast").status, "ok")
        self.assertIn("Stopped. Not measured: pairs, basket_reversion, pca_leaders", err.getvalue())
        quant.start_evaluation("pairs")  # admin can start it again straight away

    def test_progress_is_reported_up_to_done(self):
        for name in ("forecast", "pairs"):
            seen = []
            quant.run_evaluation(quant.start_evaluation(name, days=60, end=date(2026, 9, 27)).pk,
                                 progress=lambda done, total: seen.append(done / total))
            with self.subTest(strategy=name):
                self.assertEqual(seen, sorted(seen))
                self.assertEqual(seen[-1], 1.0)


def evaluation_module():
    from modules.analysis.domain import evaluation

    return evaluation
