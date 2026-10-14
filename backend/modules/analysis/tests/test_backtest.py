from datetime import date, datetime, time, timedelta
from decimal import Decimal
from io import StringIO
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from modules.analysis.application.backtest import run_backtest
from modules.analysis.domain import backtest as bt
from modules.analysis.domain.entities import Direction, PriceSeries, Signal
from modules.marketdata.domain.entities import Candle, Timeframe
from modules.marketdata.infrastructure import repositories as market_repo

NPT = ZoneInfo("Asia/Kathmandu")
START = date(2026, 1, 1)


def series(closes, symbol="TEST"):
    n = len(closes)
    return PriceSeries(
        symbol=symbol,
        dates=[START + timedelta(days=i) for i in range(n)],
        opens=list(closes), highs=[c + 1 for c in closes], lows=[c - 1 for c in closes], closes=list(closes),
        volumes=[1000.0] * n, trades=[10.0] * n,
    )


def every_day(direction):
    """A strategy that fires every day and records the last date it was shown."""
    seen = []

    def strategy(ctx):
        seen.append(ctx.series.dates[-1])
        return [Signal("always", direction, 2, "x", {"bars": len(ctx.series)})]

    return strategy, seen


class ReplayTests(SimpleTestCase):
    def test_walk_forward_never_sees_the_future(self):
        s = series([100 + i for i in range(60)])
        strategy, seen = every_day(Direction.BULLISH)
        outcomes = bt.replay(s, strategies=[strategy], horizons=(5,))
        self.assertEqual(seen, s.dates[29:])  # one call per day, from the 30th bar, each seeing only up to that day
        self.assertEqual([o.trading_date for o in outcomes], s.dates[29:])

    def test_forward_returns_and_unknown_future(self):
        closes = [100.0] * 30 + [110.0, 121.0]
        self.assertEqual(bt.forward_returns(closes, 29, (1, 2, 5)), {1: 10.0, 2: 21.0, 5: None})

    def test_window_limits_bars(self):
        s = series([float(i) for i in range(1, 301)])
        w = bt.window(s, 299)
        self.assertEqual((len(w), w.closes[0], w.closes[-1]), (bt.WINDOW, 41.0, 300.0))

    def test_date_range(self):
        s = series([100.0] * 60)
        strategy, seen = every_day(Direction.BULLISH)
        bt.replay(s, start_date=s.dates[40], end_date=s.dates[44], strategies=[strategy], horizons=(5,))
        self.assertEqual(seen, s.dates[40:45])

    def test_summary_hit_rates_follow_direction(self):
        up = bt.Outcome("A", START, "x", "bullish", 2, {5: 2.0})
        down = bt.Outcome("A", START, "x", "bullish", 1, {5: -1.0})
        bear = bt.Outcome("A", START, "x", "bearish", 3, {5: -4.0})
        pending = bt.Outcome("A", START, "x", "bullish", 2, {5: None})
        rows = {(r.strategy, r.direction): r for r in bt.summarize([up, down, bear, pending], (5,))}
        bull = rows[("x", "bullish")]
        self.assertEqual((bull.signals, bull.horizons[0].samples, bull.horizons[0].avg_return, bull.horizons[0].hit_rate), (3, 2, 0.5, 0.5))
        self.assertEqual(rows[("x", "bearish")].horizons[0].hit_rate, 1.0)
        strong = bt.summarize([up, down, bear], (5,), min_strength=2)
        self.assertEqual([(r.direction, r.signals) for r in strong], [("bearish", 1), ("bullish", 1)])

    def test_neutral_has_no_hit_rate(self):
        n = bt.Outcome("A", START, "volume", "neutral", 2, {5: 3.0})
        self.assertIsNone(bt.summarize([n], (5,))[0].horizons[0].hit_rate)


def seed(symbol, closes, first_day):
    bars = []
    for i, c in enumerate(closes):
        d = first_day + timedelta(days=i)
        p = Decimal(str(c))
        bars.append(Candle(symbol, Timeframe.DAILY, datetime.combine(d, time(15), tzinfo=NPT), d, p, p + 1, p - 1, p, 1000, None, None, 10))
    market_repo.upsert_candles(bars)


class BacktestRunTests(TestCase):
    def setUp(self):
        # A steady climb: the forecast strategy calls it a bullish trend, and it keeps rising.
        seed("CLIMB", [100 + i * 0.8 for i in range(120)], date(2026, 6, 1))

    def test_run_stores_results_and_api_serves_them(self):
        self.assertEqual(self.client.get("/api/analysis/backtest").status_code, 404)
        run = run_backtest(date(2026, 7, 15), date(2026, 9, 1))
        self.assertEqual((run.status, run.symbols_tested), ("ok", 1))
        forecast = next(r for r in run.results["1"] if r["strategy"] == "forecast")
        self.assertEqual(forecast["direction"], "bullish")
        five_day = forecast["horizons"][0]
        self.assertEqual((five_day["horizon"], five_day["hit_rate"]), (5, 1.0))
        self.assertGreater(five_day["avg_return"], 0)
        self.assertEqual(run.baseline[0]["hit_rate"], 1.0)

        body = self.client.get("/api/analysis/backtest").json()
        self.assertEqual((body["id"], body["horizons"], body["symbols_tested"]), (run.pk, [5, 10, 20], 1))

    def test_signals_after_end_date_are_not_taken(self):
        run = run_backtest(date(2026, 7, 15), date(2026, 7, 20))
        taken = sum(r["signals"] for r in run.results["1"])
        self.assertLessEqual(taken, 6 * 7)  # at most 6 days x 7 strategies

    def test_command_prints_table(self):
        out = StringIO()
        call_command("backtest", "--days", "40", "--end", "2026-09-01", stdout=out)
        text = out.getvalue()
        self.assertIn("forecast", text)
        self.assertIn("every day", text)
