from django.test import SimpleTestCase

from modules.notifications.domain.digest import Preferences, build_digest, subject_line, wants_run


def signal(symbol, direction="bullish", strength=2, message="msg"):
    return {"symbol": symbol, "direction": direction, "strength": strength, "message": message, "strategy": "x", "values": {}}


REPORT = {
    "trading_date": "2026-10-12",
    "provisional": False,
    "signals": [
        signal("NABIL", "bullish", 3, "Broke above resistance 512 on 2.1x average volume"),
        signal("NABIL", "bearish", 1, "RSI 72: overbought"),
        signal("NICA", "bullish", 2, "MACD crossed above its signal line"),
        signal("UPPER", "bearish", 2, "Price closed below its 50-day average"),
        signal("HIDCL", "neutral", 2, "Volume 3.0x the 20-day average"),
        signal("SHIVM", "bullish", 1, "RSI 28: oversold"),
    ],
    "analyses": {"NABIL": {"indicators": {"close": 515.0, "rsi14": 71.6}, "support": 480.0, "resistance": 540.0, "forecast": {"projected_close": 530.0}}},
}


class DigestTests(SimpleTestCase):
    def test_sections_and_strength_filter(self):
        content = build_digest(REPORT, Preferences(min_strength=2))
        self.assertEqual([i.symbol for i in content.strong], ["NABIL"])
        self.assertEqual([i.symbol for i in content.bullish], ["NICA"])
        self.assertEqual([i.symbol for i in content.bearish], ["UPPER"])
        self.assertEqual([i.symbol for i in content.activity], ["HIDCL"])
        nabil = content.strong[0]
        self.assertEqual(nabil.messages, ["Broke above resistance 512 on 2.1x average volume"])  # strength-1 RSI note filtered out
        self.assertEqual((nabil.close, nabil.rsi, nabil.support, nabil.resistance), (515.0, 72, 480.0, 540.0))

    def test_everything_at_strength_one(self):
        content = build_digest(REPORT, Preferences(min_strength=1))
        self.assertEqual(content.stock_count, 5)
        self.assertEqual(len(content.strong[0].messages), 2)

    def test_watchlist(self):
        content = build_digest(REPORT, Preferences(min_strength=1, watchlist=frozenset({"UPPER", "NOPE"})))
        self.assertEqual(content.stock_count, 1)
        self.assertEqual(content.bearish[0].symbol, "UPPER")

    def test_empty_and_intraday_preference(self):
        self.assertTrue(build_digest(REPORT, Preferences(min_strength=3, watchlist=frozenset({"NICA"}))).is_empty)
        self.assertFalse(wants_run(Preferences(include_intraday=False), provisional=True))
        self.assertTrue(wants_run(Preferences(include_intraday=False), provisional=False))

    def test_subject(self):
        content = build_digest(REPORT, Preferences(min_strength=2))
        self.assertEqual(subject_line(content), "NEPSE Market close 2026-10-12: 1 strong, 1 bullish, 1 bearish, 1 unusual activity")

    def test_watchlist_prices_listed_even_without_signals(self):
        quotes = [
            {"symbol": "UPPER", "close": "210.50", "change_percent": -1.2},
            {"symbol": "NICA", "close": "400.00", "change_percent": 0.5},
        ]
        prefs = Preferences(min_strength=3, watchlist=frozenset({"UPPER", "NICA", "GONE"}))
        content = build_digest(REPORT, prefs, quotes=quotes)
        self.assertEqual(content.stock_count, 0)
        self.assertFalse(content.is_empty)
        self.assertEqual(
            [(w.symbol, w.close, w.change_percent, w.signal_count) for w in content.watchlist],
            [("GONE", None, None, 0), ("NICA", 400.0, 0.5, 0), ("UPPER", 210.5, -1.2, 0)],
        )
        self.assertEqual(subject_line(content), "NEPSE Market close 2026-10-12: your watchlist")

    def test_watchlist_counts_signals_and_no_watchlist_means_no_section(self):
        quotes = [{"symbol": "UPPER", "close": "210.50", "change_percent": -1.2}]
        content = build_digest(REPORT, Preferences(min_strength=1, watchlist=frozenset({"UPPER"})), quotes=quotes)
        self.assertEqual(content.watchlist[0].signal_count, 1)
        self.assertEqual(build_digest(REPORT, Preferences(min_strength=1), quotes=quotes).watchlist, [])

    def test_track_record_lists_only_settled_strategies(self):
        card = {"since": "2026-04-15", "strategies": [
            {"strategy": "pairs", "settled": 4, "hit_rate": 75.0, "avg_return": 2.1},
            {"strategy": "rsi", "settled": 0, "hit_rate": None, "avg_return": None},
        ]}
        content = build_digest(REPORT, Preferences(min_strength=2), scorecard=card)
        self.assertEqual([r["strategy"] for r in content.track_record], ["pairs"])
        self.assertEqual(content.track_record_since, "2026-04-15")
