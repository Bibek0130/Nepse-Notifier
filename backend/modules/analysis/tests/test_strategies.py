from datetime import date, timedelta

from django.test import SimpleTestCase

from modules.analysis.domain.engine import analyze
from modules.analysis.domain.entities import Direction, PriceSeries


def series(closes, volumes=None, trades=None, spread=1.0):
    n = len(closes)
    start = date(2025, 1, 1)
    return PriceSeries(
        symbol="TEST",
        dates=[start + timedelta(days=i) for i in range(n)],
        opens=list(closes),
        highs=[c + spread for c in closes],
        lows=[c - spread for c in closes],
        closes=list(closes),
        volumes=volumes or [1000.0] * n,
        trades=trades or [50.0] * n,
    )


def signals(result, strategy):
    return [s for s in result.signals if s.strategy == strategy]


class EngineTests(SimpleTestCase):
    def test_short_history_is_skipped(self):
        self.assertIsNone(analyze(series([100.0] * 10)))

    def test_flat_market_has_no_signals(self):
        result = analyze(series([100.0] * 250))
        self.assertEqual(result.signals, [])
        self.assertEqual(result.indicators["sma200"], 100.0)

    def test_golden_cross(self):
        # Long decline then a sharp rally pulls the 50-day back above the 200-day on the last bar.
        closes = [200 - i * 0.5 for i in range(200)] + [100 + i * 3 for i in range(60)]
        found = None
        for end in range(210, len(closes) + 1):
            hits = signals(analyze(series(closes[:end])), "trend")
            if hits:
                found = hits[0]
                break
        self.assertIsNotNone(found)
        self.assertEqual((found.direction, found.strength), (Direction.BULLISH, 3))

    def test_rsi_overbought(self):
        closes = [100 + i for i in range(60)]
        hit = signals(analyze(series(closes)), "rsi")[0]
        self.assertEqual(hit.direction, Direction.BEARISH)
        self.assertIn("overbought", hit.message)

    def test_volume_and_transaction_spike(self):
        closes = [100.0] * 59 + [101.0]
        volumes = [1000.0] * 59 + [3500.0]
        trades = [50.0] * 59 + [200.0]
        result = analyze(series(closes, volumes, trades))
        vol = signals(result, "volume")[0]
        self.assertEqual(vol.direction, Direction.BULLISH)
        self.assertEqual(vol.values["ratio"], 3.5)
        self.assertEqual(signals(result, "transactions")[0].values["ratio"], 4.0)

    def test_breakout_above_resistance_on_volume(self):
        # Range 95-105 for a while, then a close at 112 on heavy volume.
        base = [95, 98, 101, 104, 105, 104, 101, 98] * 8
        closes = [float(c) for c in base] + [112.0]
        volumes = [1000.0] * (len(closes) - 1) + [2500.0]
        hit = signals(analyze(series(closes, volumes, spread=0.5)), "breakout")[0]
        self.assertEqual((hit.direction, hit.strength), (Direction.BULLISH, 3))
        self.assertAlmostEqual(hit.values["level"], 105.5, delta=1)

    def test_breakdown_on_light_volume_is_weak(self):
        base = [95, 98, 101, 104, 105, 104, 101, 98] * 8
        closes = [float(c) for c in base] + [88.0]
        hit = signals(analyze(series(closes, spread=0.5)), "breakout")[0]
        self.assertEqual((hit.direction, hit.strength), (Direction.BEARISH, 1))

    def test_steady_trend_projection(self):
        closes = [100 * (1.01 ** i) for i in range(60)]
        hit = signals(analyze(series(closes)), "forecast")[0]
        self.assertEqual(hit.direction, Direction.BULLISH)
        self.assertGreater(hit.values["projected_close"], closes[-1])
