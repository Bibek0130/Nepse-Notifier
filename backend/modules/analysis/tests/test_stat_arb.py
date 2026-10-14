import math
import random

from django.test import SimpleTestCase

from modules.analysis.domain import stat_arb


def cointegrated_pair(n=150, stretch=3.3, seed=1):
    """B is a random walk; A tracks it with a mean-reverting spread, stretched ``stretch`` sds on the last bar."""
    rng = random.Random(seed)
    log_b, spread = [math.log(100)], [0.0]
    for _ in range(n - 1):
        log_b.append(log_b[-1] + rng.gauss(0, 0.015))
        spread.append(0.6 * spread[-1] + rng.gauss(0, 0.01))
    sd = 0.01 / math.sqrt(1 - 0.36)
    spread[-1] = stretch * sd
    b = [math.exp(x) for x in log_b]
    a = [math.exp(0.2 + x + s) for x, s in zip(log_b, spread)]
    return a, b


def random_walk(n=150, seed=7):
    rng = random.Random(seed)
    out = [100.0]
    for _ in range(n - 1):
        out.append(out[-1] * math.exp(rng.gauss(0, 0.02)))
    return out


class StatsTests(SimpleTestCase):
    def test_ols(self):
        alpha, beta, residuals, _ = stat_arb.ols([1, 2, 3, 4], [3, 5, 7, 9])
        self.assertAlmostEqual(alpha, 1)
        self.assertAlmostEqual(beta, 2)
        self.assertTrue(all(abs(r) < 1e-9 for r in residuals))

    def test_mean_reverting_series_has_short_half_life_and_low_adf(self):
        rng = random.Random(3)
        s = [0.0]
        for _ in range(200):
            s.append(0.5 * s[-1] + rng.gauss(0, 1))
        self.assertLess(stat_arb.adf_t_stat(s), stat_arb.ADF_CRITICAL)
        self.assertLess(stat_arb.half_life(s), 3)

    def test_random_walk_is_not_mean_reverting(self):
        self.assertGreater(stat_arb.adf_t_stat(random_walk(300)), stat_arb.ADF_CRITICAL)


class PairsTests(SimpleTestCase):
    def test_stretched_pair_signals_both_legs(self):
        a, b = cointegrated_pair()
        fit = stat_arb.fit_spread(a, b)
        self.assertTrue(fit.mean_reverting)
        self.assertAlmostEqual(fit.beta, 1.0, delta=0.1)
        found = dict(stat_arb.pair_signals("A", a, "B", b))
        self.assertEqual(found["A"].direction, "bearish")  # A ran ahead of B
        self.assertEqual(found["B"].direction, "bullish")
        self.assertLess(found["A"].values["target"], a[-1])
        self.assertGreater(found["A"].values["stop"], a[-1])
        self.assertGreater(found["B"].values["target"], b[-1])
        self.assertLess(found["B"].values["stop"], b[-1])
        self.assertEqual(found["B"].values["peer"], "A")

    def test_unstretched_or_unrelated_pairs_are_quiet(self):
        a, b = cointegrated_pair(stretch=0.5)
        self.assertEqual(list(stat_arb.pair_signals("A", a, "B", b)), [])
        self.assertEqual(list(stat_arb.pair_signals("A", random_walk(seed=1), "B", random_walk(seed=2))), [])

    def test_short_history_is_skipped(self):
        a, b = cointegrated_pair(n=60)
        self.assertIsNone(stat_arb.fit_spread(a, b))


class ScanTests(SimpleTestCase):
    def test_scan_groups_and_keeps_one_pair_signal_per_stock(self):
        a, b = cointegrated_pair()
        dates = list(range(len(a)))
        closes = {"A": a, "B": b, "C": random_walk(seed=5)}
        found = stat_arb.scan({s: dates for s in closes}, closes, {"banks": ["A", "B", "C"]})
        pairs = [(s, sig.direction) for s, sig in found if sig.strategy == "pairs"]
        self.assertEqual(pairs, [("A", "bearish"), ("B", "bullish")])

    def test_align_uses_common_dates(self):
        aligned = stat_arb.align({"X": [1, 2, 3], "Y": [2, 3, 4]}, {"X": [10, 20, 30], "Y": [200, 300, 400]}, ["X", "Y"])
        self.assertEqual(aligned, {"X": [20, 30], "Y": [200, 300]})

    def test_basket_signal(self):
        a, b = cointegrated_pair(seed=4)
        signal = stat_arb.basket_signal("A", a, b, "banks")
        self.assertIsNotNone(signal)
        self.assertEqual((signal.strategy, signal.direction), ("basket_reversion", "bearish"))
