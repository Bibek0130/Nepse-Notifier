from django.test import SimpleTestCase

from modules.analysis.domain import indicators as ind
from modules.analysis.domain.engine import analyze
from modules.analysis.domain.levels import Level
from modules.analysis.domain.trade_plan import Zone, build_trade_plan, fibonacci_zone, movement

from .test_strategies import series, signals


def plan_for(s, support=None, resistance=None):
    c = s.closes
    return build_trade_plan(s, support, resistance, ind.ema(c, 5), ind.ema(c, 8), ind.ema(c, 13), ind.atr(s.highs, s.lows, c))


class AtrTests(SimpleTestCase):
    def test_constant_range(self):
        s = series([100.0] * 30, spread=2.0)
        values = ind.atr(s.highs, s.lows, s.closes)
        self.assertIsNone(values[13])
        self.assertAlmostEqual(values[-1], 4.0)


class TradePlanTests(SimpleTestCase):
    def test_fibonacci_zone(self):
        self.assertEqual(fibonacci_zone(100, 200, up_swing=True), Zone(138.2, 161.8))
        self.assertEqual(fibonacci_zone(100, 200, up_swing=False), Zone(138.2, 161.8))
        self.assertEqual(fibonacci_zone(100, 300, up_swing=True), Zone(176.4, 223.6))

    def test_zones_from_support_and_resistance(self):
        s = series([100.0] * 40, spread=2.0)  # ATR 4
        plan = plan_for(s, Level(96.0, 3, "support"), Level(110.0, 2, "resistance"))
        self.assertEqual(plan.ltp, 100.0)
        self.assertEqual(plan.buy_zone, Zone(96.0, 98.0))
        self.assertEqual(plan.sell_zone, Zone(108.0, 110.0))
        self.assertEqual((plan.stop_loss, plan.target), (92.0, 110.0))
        self.assertEqual(plan.risk_reward, 1.25)  # 10 up / 8 down
        self.assertEqual((plan.atr, plan.atr_pct), (4.0, 4.0))
        self.assertEqual(plan.movement, "sideways")
        self.assertEqual(plan.position, "in correction zone")  # middle of the 98-102 swing

    def test_uptrend_at_new_highs(self):
        s = series([100.0 + i for i in range(40)])
        plan = plan_for(s)  # no levels: buy at the swing low, target 3 ATRs up
        self.assertEqual(plan.movement, "uptrend")
        self.assertEqual(plan.swing, "up")
        self.assertEqual(plan.change, 1.0)
        self.assertGreater(plan.target, plan.ltp)
        self.assertGreater(plan.risk_reward, 0)
        self.assertEqual(plan.correction_zone.low, round(plan.swing_high - 0.618 * (plan.swing_high - plan.swing_low), 1))

    def test_movement(self):
        down = [200.0 - i for i in range(30)]
        self.assertEqual(movement(down, ind.ema(down, 5), ind.ema(down, 8), ind.ema(down, 13)), "downtrend")

    def test_engine_attaches_plan(self):
        result = analyze(series([100.0] * 60))
        self.assertIsNotNone(result.trade_plan)
        self.assertEqual(result.indicators["atr14"], 2.0)


class EmaRibbonTests(SimpleTestCase):
    def test_bullish_cross(self):
        closes = [100.0 - i * 0.5 for i in range(40)] + [85.0, 90.0]
        found = signals(analyze(series(closes)), "ema_5_8_13")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].direction, "bullish")
        stop, target = found[0].values["stop"], found[0].values["target"]
        self.assertAlmostEqual(target - 90.0, 90.0 - stop, places=1)

    def test_bearish_exit(self):
        closes = [100.0 + i * 0.5 for i in range(40)] + [115.0, 110.0]
        found = signals(analyze(series(closes)), "ema_5_8_13")
        self.assertEqual([s.direction for s in found], ["bearish"])

    def test_no_repeat_while_aligned(self):
        closes = [100.0 + i for i in range(40)]
        self.assertEqual(signals(analyze(series(closes)), "ema_5_8_13"), [])
