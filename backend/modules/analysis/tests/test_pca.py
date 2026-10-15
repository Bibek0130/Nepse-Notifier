import math
import random

from django.test import SimpleTestCase

from modules.analysis.domain import pca

N = pca.LOOKBACK + 1


def sideways_market(seed=3, bank_jump=0.08):
    """BANK and LIFE share a factor and drift down, HYDRO drifts up so the market is flat; BANK jumps on the last day.

    B1 follows the bank factor most closely, B3 least, so B1 should lead the bank sector.
    """
    rng = random.Random(seed)
    factor = [rng.gauss(0, 0.006) for _ in range(N)]
    hydro_factor = [rng.gauss(0, 0.006) for _ in range(N)]
    plan = {
        "B1": (factor, -0.0015, 0.002), "B2": (factor, -0.0015, 0.005), "B3": (factor, -0.0015, 0.012),
        "L1": (factor, -0.0005, 0.004), "L2": (factor, -0.0005, 0.006),
        "H1": (hydro_factor, 0.002, 0.004), "H2": (hydro_factor, 0.002, 0.006),
    }
    closes = {}
    for symbol, (f, drift, noise) in plan.items():
        logs = [math.log(100)]
        for i in range(1, N):
            step = drift + f[i] + rng.gauss(0, noise)
            if i == N - 1 and symbol.startswith("B"):
                step = bank_jump
            logs.append(logs[-1] + step)
        closes[symbol] = [math.exp(x) for x in logs]
    dates = list(range(N))
    groups = {"Banking": ["B1", "B2", "B3"], "Life Insurance": ["L1", "L2"], "Hydropower": ["H1", "H2"]}
    return {s: dates for s in closes}, closes, groups


class ComponentTests(SimpleTestCase):
    def test_correlated_variables_share_the_first_component(self):
        rng = random.Random(1)
        x = [rng.gauss(0, 1) for _ in range(300)]
        comps = pca.principal_components({
            "a": x, "b": [v + rng.gauss(0, 0.05) for v in x], "c": [rng.gauss(0, 1) for _ in range(300)],
        })
        first = comps[0]
        self.assertAlmostEqual(first.explained, 2 / 3, delta=0.05)
        self.assertAlmostEqual(first.loadings["a"], 1 / math.sqrt(2), delta=0.05)
        self.assertLess(abs(first.loadings["c"]), 0.15)
        self.assertAlmostEqual(sum(c.explained for c in comps), 1.0, delta=0.01)

    def test_flat_series_are_left_out(self):
        self.assertEqual(pca.principal_components({"a": [0.0] * 10, "b": [1.0, 2.0] * 5}), [])

    def test_calendar_carries_forward_and_drops_thin_stocks(self):
        dates = {"A": list(range(20)), "B": [d for d in range(20) if d != 15], "C": [0, 19]}
        closes = {s: [float(d) + 1 for d in ds] for s, ds in dates.items()}
        _, out = pca.calendar_closes(dates, closes, ["A", "B", "C"], 10)
        self.assertEqual(set(out), {"A", "B"})
        self.assertEqual(out["B"][5], 15.0)  # day 15 carried from day 14


class ScanTests(SimpleTestCase):
    def test_buys_leaders_of_the_driver_sector_when_it_turns_up(self):
        found = pca.scan(*sideways_market())
        symbols = [s for s, _ in found]
        self.assertEqual(symbols[0], "B1")
        self.assertTrue(set(symbols) <= {"B1", "B2", "B3"})
        signal = found[0][1]
        self.assertEqual((signal.strategy, signal.direction), ("pca_leaders", "bullish"))
        self.assertEqual(signal.values["group"], "Banking")
        self.assertLess(signal.values["sector_change_pct"], 0)
        self.assertLess(abs(signal.values["market_change_pct"]), pca.SIDEWAYS_PCT)
        close = sideways_market()[1]["B1"][-1]
        self.assertLess(signal.values["stop"], close)
        self.assertGreater(signal.values["target"], close)

    def test_quiet_without_the_reversal(self):
        self.assertEqual(pca.scan(*sideways_market(bank_jump=-0.01)), [])

    def test_quiet_when_the_market_is_trending(self):
        dates, closes, groups = sideways_market()
        closes = {s: [c * (1 + i / 100) for i, c in enumerate(v)] for s, v in closes.items()}  # +120% trend
        self.assertEqual(pca.scan(dates, closes, groups), [])

    def test_whole_market_used_when_sectors_are_unknown(self):
        dates, closes, _ = sideways_market()
        banks = {s: v for s, v in closes.items() if s.startswith("B") or s.startswith("H")}
        found = pca.scan({s: dates[s] for s in banks}, banks, {"market": sorted(banks)})
        self.assertTrue(found)
        self.assertEqual(found[0][1].values["group"], "the market")
        self.assertEqual({s for s, _ in found}, {"B1", "B2", "B3"})  # hydro stocks barely load on the bank-driven factor

    def test_short_history_is_skipped(self):
        dates, closes, groups = sideways_market()
        closes = {s: v[-50:] for s, v in closes.items()}
        self.assertEqual(pca.scan({s: list(range(50)) for s in closes}, closes, groups), [])
