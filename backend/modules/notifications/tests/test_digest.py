from django.test import SimpleTestCase

from modules.notifications.domain.digest import Preferences, build_digest, subject_line, wants_run

QUANT = ("quant_momentum", "quant_reversion", "pca_leaders")


def signal(symbol, strategy, direction="bullish", strength=2, message="msg"):
    return {"symbol": symbol, "direction": direction, "strength": strength, "message": message, "strategy": strategy, "values": {}}


def analysis(close, rr):
    return {"indicators": {"close": close, "rsi14": 61.4}, "support": close * 0.9, "resistance": close * 1.2,
            "trade_plan": {"ltp": close, "risk_reward": rr}}


REPORT = {
    "trading_date": "2026-10-12",
    "provisional": False,
    "signals": [
        signal("NABIL", "quant_momentum", message="Quant momentum: RSI broke above 60"),
        signal("NABIL", "pca_leaders", strength=3, message="PCA leader"),
        signal("NABIL", "volume", "neutral", message="Volume 3.0x the 20-day average"),
        signal("NICA", "quant_reversion", message="Quant mean reversion"),
        signal("ADBL", "pca_leaders", strength=3, message="PCA leader"),
        signal("SHIVM", "quant_momentum", message="Quant momentum"),
        signal("UPPER", "quant_reversion", message="Quant mean reversion"),  # risk:reward too low
        signal("HIDCL", "pca_leaders"),  # but the momentum exit fired too
        signal("HIDCL", "quant_momentum", "bearish", message="Quant exit"),
        signal("NTC", "breakout", strength=3, message="Broke above resistance"),  # not a quant strategy
        signal("GONE", "quant_momentum"),  # no trade levels
    ],
    "analyses": {
        "NABIL": analysis(515.0, 2.1),
        "NICA": analysis(400.0, 3.5),
        "ADBL": analysis(300.0, 2.0),
        "SHIVM": analysis(600.0, 2.4),
        "UPPER": analysis(210.0, 1.9),
        "HIDCL": analysis(200.0, 5.0),
        "NTC": analysis(900.0, 6.0),
    },
    "trade_plans": {"FLAT": {"ltp": 100.0, "risk_reward": 1.2}},
}


def picks(report=REPORT, **kwargs):
    return build_digest(report, Preferences(**kwargs), quant_strategies=QUANT)


class TopPicksTests(SimpleTestCase):
    def test_top_three_quant_picks_at_one_to_two_or_better(self):
        content = picks()
        # NABIL has two quant strategies agreeing; ADBL's call is strength 3; then the best risk:reward.
        self.assertEqual([p.symbol for p in content.picks], ["NABIL", "ADBL", "NICA"])
        self.assertEqual(content.candidates, 6)  # every quant buy call, before the filter and the cut
        nabil = content.picks[0]
        self.assertEqual(nabil.strategies, ["pca_leaders", "quant_momentum"])
        self.assertEqual(nabil.strategy_labels, "PCA sector leaders, Quant momentum")
        self.assertEqual(nabil.messages, ["PCA leader", "Quant momentum: RSI broke above 60", "Volume 3.0x the 20-day average"])
        self.assertEqual((nabil.close, nabil.rsi, nabil.risk_reward), (515.0, 61, 2.1))

    def test_filters(self):
        symbols = {p.symbol for p in build_digest(REPORT, Preferences(), quant_strategies=QUANT).picks}
        self.assertNotIn("UPPER", symbols)  # 1:1.9
        self.assertNotIn("HIDCL", symbols)  # quant sell call
        self.assertNotIn("NTC", symbols)  # not picked by a quant strategy
        self.assertNotIn("GONE", symbols)  # no trade levels
        self.assertEqual(build_digest(REPORT, Preferences()).picks, [])  # no quant strategies, no picks

    def test_fewer_than_three_qualify(self):
        report = {**REPORT, "signals": [s for s in REPORT["signals"] if s["symbol"] in ("NICA", "UPPER")]}
        content = picks(report)
        self.assertEqual([p.symbol for p in content.picks], ["NICA"])
        self.assertEqual(subject_line(content), "NEPSE Market close 2026-10-12: top pick NICA")

    def test_no_picks_at_close_still_sends_but_midday_does_not(self):
        report = {**REPORT, "signals": [s for s in REPORT["signals"] if s["symbol"] == "UPPER"]}
        closing = picks(report)
        self.assertEqual((closing.picks, closing.candidates), ([], 1))
        self.assertFalse(closing.is_empty)
        self.assertEqual(subject_line(closing), "NEPSE Market close 2026-10-12: no quant pick at 1:2 or better")
        self.assertTrue(picks({**report, "provisional": True}).is_empty)
        self.assertFalse(picks({**REPORT, "provisional": True}).is_empty)

    def test_subject(self):
        self.assertEqual(subject_line(picks()), "NEPSE Market close 2026-10-12: top picks NABIL, ADBL, NICA")

    def test_intraday_preference(self):
        self.assertFalse(wants_run(Preferences(include_intraday=False), provisional=True))
        self.assertTrue(wants_run(Preferences(include_intraday=False), provisional=False))

    def test_watchlist_does_not_limit_picks_and_lists_prices(self):
        quotes = [{"symbol": "FLAT", "close": "100.00", "change_percent": 0.5}, {"symbol": "NICA", "close": "400.00", "change_percent": 1.0}]
        content = picks(watchlist=frozenset({"FLAT", "NICA", "GONE"}))
        self.assertEqual(len(content.picks), 3)
        self.assertEqual(content.watchlist, [])  # no quotes, no section
        content = build_digest(REPORT, Preferences(watchlist=frozenset({"FLAT", "NICA", "GONE"})), quotes=quotes, quant_strategies=QUANT)
        self.assertEqual(
            [(w.symbol, w.close, w.is_pick, w.plan) for w in content.watchlist],
            [("FLAT", 100.0, False, {"ltp": 100.0, "risk_reward": 1.2}), ("GONE", None, False, None), ("NICA", 400.0, True, None)],
        )

    def test_track_record_lists_only_settled_strategies(self):
        card = {"since": "2026-04-15", "strategies": [
            {"strategy": "pairs", "settled": 4, "hit_rate": 75.0, "avg_return": 2.1},
            {"strategy": "rsi", "settled": 0, "hit_rate": None, "avg_return": None},
        ]}
        content = build_digest(REPORT, Preferences(), scorecard=card, quant_strategies=QUANT)
        self.assertEqual([r["strategy"] for r in content.track_record], ["pairs"])
        self.assertEqual(content.track_record_since, "2026-04-15")
