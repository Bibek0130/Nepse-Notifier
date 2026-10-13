from django.test import SimpleTestCase

from modules.analysis.domain import indicators as ind
from modules.analysis.domain.forecast import linear_trend
from modules.analysis.domain.levels import cluster, find_levels


class IndicatorTests(SimpleTestCase):
    def test_sma(self):
        self.assertEqual(ind.sma([1, 2, 3, 4, 5], 3), [None, None, 2.0, 3.0, 4.0])

    def test_ema_seeded_with_sma(self):
        out = ind.ema([1, 2, 3, 4, 5], 3)
        self.assertEqual(out[:3], [None, None, 2.0])
        self.assertAlmostEqual(out[3], 3.0)  # 4*0.5 + 2*0.5
        self.assertAlmostEqual(out[4], 4.0)

    def test_rsi_extremes_and_known_value(self):
        self.assertEqual(ind.rsi(list(range(1, 20)), 14)[-1], 100.0)
        self.assertEqual(ind.rsi(list(range(20, 1, -1)), 14)[-1], 0.0)
        # Wilder's textbook example (New Concepts in Technical Trading Systems): first RSI ~ 70.53.
        closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
        self.assertAlmostEqual(ind.rsi(closes, 14)[-1], 70.53, delta=0.1)  # published inputs are rounded

    def test_macd_lines_up_with_input(self):
        closes = [float(x) for x in range(1, 61)]
        line, signal, hist = ind.macd(closes)
        self.assertEqual(len(line), 60)
        self.assertIsNone(line[24])
        self.assertIsNotNone(line[25])
        self.assertIsNone(signal[32])
        self.assertIsNotNone(signal[33])
        self.assertAlmostEqual(hist[-1], line[-1] - signal[-1])
        self.assertGreater(line[-1], 0)  # steady uptrend: fast EMA above slow

    def test_crosses(self):
        self.assertTrue(ind.crossed_above([1, 3], [2, 2]))
        self.assertFalse(ind.crossed_above([3, 4], [2, 2]))
        self.assertTrue(ind.crossed_below([3, 1], [2, 2]))
        self.assertFalse(ind.crossed_above([None, 3], [2, 2]))

    def test_average_excluding_today(self):
        self.assertEqual(ind.average([1, 1, 1, 10], 3, exclude_last=True), 1)
        self.assertIsNone(ind.average([1, 2], 3))


class LevelTests(SimpleTestCase):
    def test_cluster(self):
        self.assertEqual(cluster([100, 101, 120], 1.5)[0], (100.5, 2))

    def test_finds_nearest_support_and_resistance(self):
        # Oscillates between ~90 and ~110, now at 100.
        highs, lows = [], []
        for cycle in range(6):
            for v in [95, 100, 105, 110, 105, 100, 95, 90]:
                highs.append(v + 1)
                lows.append(v - 1)
        support, resistance = find_levels(highs, lows, 100)
        self.assertAlmostEqual(support.price, 89, delta=1)
        self.assertAlmostEqual(resistance.price, 111, delta=1)
        self.assertGreaterEqual(resistance.touches, 4)


class ForecastTests(SimpleTestCase):
    def test_perfect_line(self):
        f = linear_trend([100 + 2 * i for i in range(20)], lookback=20, horizon=5)
        self.assertEqual((f.slope_per_day, f.r_squared), (2.0, 1.0))
        self.assertEqual(f.projected_close, 100 + 2 * 24)

    def test_too_short(self):
        self.assertIsNone(linear_trend([1, 2, 3]))
