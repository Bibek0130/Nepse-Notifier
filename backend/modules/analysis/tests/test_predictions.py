from datetime import date, timedelta

from django.test import SimpleTestCase

from modules.analysis.domain.predictions import draft, score, summarize

D0 = date(2026, 10, 1)


def bars(rows):
    """rows of (high, low, close) on consecutive days after D0."""
    return [(D0 + timedelta(days=i + 1), h, l, c) for i, (h, l, c) in enumerate(rows)]


class DraftTests(SimpleTestCase):
    def test_uses_target_and_stop_from_values(self):
        d = draft({"strategy": "ema_5_8_13", "direction": "bullish", "strength": 2, "values": {"stop": 95, "target": 110}}, 100)
        self.assertEqual((d.entry_price, d.target_price, d.stop_price, d.horizon), (100.0, 110.0, 95.0, 10))

    def test_forecast_horizon_and_bad_levels_dropped(self):
        d = draft({"strategy": "forecast", "direction": "bearish", "strength": 1, "values": {"projected_close": 104}}, 100)
        self.assertEqual((d.target_price, d.horizon), (None, 5))  # a "bearish" target above the price makes no sense

    def test_neutral_signals_are_not_predictions(self):
        self.assertIsNone(draft({"strategy": "volume", "direction": "neutral", "strength": 2, "values": {}}, 100))


class ScoreTests(SimpleTestCase):
    def test_open_until_horizon(self):
        self.assertIsNone(score("bullish", 100, None, None, 3, bars([(101, 99, 100), (102, 99, 101)])))

    def test_settles_at_horizon(self):
        s = score("bullish", 100, None, None, 2, bars([(101, 99, 100), (104, 100, 103), (90, 80, 85)]))
        self.assertEqual((s.outcome, s.exit_price, s.return_pct, s.correct, s.sessions), ("horizon", 103, 3.0, True, 2))

    def test_target_and_stop(self):
        hit = score("bullish", 100, 105, 95, 10, bars([(103, 99, 102), (106, 101, 105)]))
        self.assertEqual((hit.outcome, hit.exit_price, hit.correct, hit.exit_date), ("target", 105, True, D0 + timedelta(days=2)))
        stopped = score("bearish", 100, 90, 104, 10, bars([(105, 99, 103)]))
        self.assertEqual((stopped.outcome, stopped.return_pct, stopped.correct), ("stop", 4.0, False))

    def test_same_bar_counts_as_stop(self):
        self.assertEqual(score("bullish", 100, 105, 95, 10, bars([(106, 94, 100)])).outcome, "stop")


class SummaryTests(SimpleTestCase):
    def test_summarize(self):
        rows = [
            {"strategy": "pairs", "direction": "bullish", "outcome": "target", "return_pct": 4.0, "correct": True},
            {"strategy": "pairs", "direction": "bearish", "outcome": "horizon", "return_pct": 2.0, "correct": False},
            {"strategy": "pairs", "direction": "bullish", "outcome": "", "return_pct": None, "correct": None},
            {"strategy": "rsi", "direction": "bearish", "outcome": "stop", "return_pct": 3.0, "correct": False},
        ]
        pairs, rsi = summarize(rows)
        self.assertEqual(
            (pairs["predictions"], pairs["open"], pairs["settled"], pairs["hit_rate"], pairs["avg_return"], pairs["targets_hit"]),
            (3, 1, 2, 50.0, 1.0, 1),
        )
        self.assertEqual((rsi["hit_rate"], rsi["avg_return"], rsi["stops_hit"]), (0.0, -3.0, 1))
