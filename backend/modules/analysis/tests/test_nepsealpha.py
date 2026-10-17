import random
from datetime import date

from django.test import SimpleTestCase, TestCase

from modules.analysis.domain import nepsealpha as na
from modules.analysis.domain.entities import Direction, PriceSeries
from modules.analysis.domain.predictions import draft

from .market import trading_days


def make(symbol, closes, days, volume=1000):
    volumes = volume if isinstance(volume, list) else [volume] * len(closes)
    return PriceSeries(symbol, list(days[-len(closes):]), closes, [c * 1.01 for c in closes], [c * 0.99 for c in closes],
                       closes, volumes, [10] * len(closes))


def walk(n, drift, seed, noise=0.004, start=100.0):
    rng, out, price = random.Random(seed), [], start
    for _ in range(n):
        price *= 1 + drift + rng.gauss(0, noise)
        out.append(price)
    return out


def market(n=300, drift=0.001, stocks=8, end=date(2026, 9, 10), volume=1000):
    """``stocks`` stocks drifting ``drift`` a day, ending on ``end``: {symbol: PriceSeries}, trading days."""
    days = [d for d in trading_days(date(2024, 1, 1), 1200) if d <= end][-n:]
    return {f"S{k}": make(f"S{k}", walk(n, drift, seed=k), days, volume) for k in range(stocks)}, days


def dip(closes, drops=(-0.03, -0.07)):
    out = list(closes[:-len(drops)])
    for d in drops:
        out.append(out[-1] * (1 + d))
    return out


def upto(series_by_symbol, day):
    """Every series as it looked at the close of ``day``."""
    out = {}
    for s, v in series_by_symbol.items():
        i = max(k for k, d in enumerate(v.dates) if d <= day)
        out[s] = PriceSeries(v.symbol, v.dates[:i + 1], v.opens[:i + 1], v.highs[:i + 1], v.lows[:i + 1],
                             v.closes[:i + 1], v.volumes[:i + 1], v.trades[:i + 1])
    return out


class MarketIndexTests(SimpleTestCase):
    def test_corporate_action_jumps_do_not_move_the_market(self):
        stocks, days = market(n=50, drift=0.0, stocks=3)
        _, before = na.market_index(stocks)
        bonus = list(stocks["S0"].closes)
        bonus[30:] = [c * 0.6 for c in bonus[30:]]  # a 40% bonus share adjustment in unadjusted prices
        stocks["S0"] = make("S0", bonus, days)
        _, after = na.market_index(stocks)
        # Only that one day's return (now counted as 0) differs; uncleaned, the index would drop about 13%.
        self.assertLess(abs(after[-1] / before[-1] - 1), 0.01)
        self.assertEqual(na.clean_returns([100, 60, 63])[0], 0.0)
        self.assertAlmostEqual(na.growth([100, 60, 63]), 5.0)

    def test_trend_needs_240_sessions(self):
        stocks, _ = market(n=200)
        self.assertEqual(na.market_trend(stocks), (None, None))
        stocks, _ = market(n=260)
        up, pct = na.market_trend(stocks)
        self.assertTrue(up)
        self.assertGreater(pct, 0)


class HybridTests(SimpleTestCase):
    def setUp(self):
        self.stocks, self.days = market()
        self.stocks["DIP"] = make("DIP", dip(walk(300, 0.001, seed=99)), self.days)

    def test_oversold_dip_in_a_rising_market_is_a_buy_with_sane_levels(self):
        found = na.scan(self.stocks, {na.STRATEGY_HYBRID})
        self.assertEqual([s for s, _ in found], ["DIP"])
        signal = found[0][1]
        close = self.stocks["DIP"].closes[-1]
        self.assertEqual(signal.direction, Direction.BULLISH)
        self.assertLess(signal.values["rsi14"], 30)
        self.assertLessEqual(signal.values["zscore"], -2)
        self.assertLess(signal.values["stop"], close)
        self.assertGreater(signal.values["target"], close)
        self.assertLessEqual(1 - signal.values["stop"] / close, na.MAX_STOP_PCT / 100 + 1e-9)
        d = draft(signal, close)
        self.assertEqual((d.horizon, d.stop_price, d.target_price), (20, signal.values["stop"], signal.values["target"]))

    def test_only_the_first_day_of_a_dip(self):
        self.stocks["DIP"] = make("DIP", dip(walk(300, 0.001, seed=99), (-0.03, -0.07, -0.04)), self.days)
        yesterday = upto(self.stocks, self.days[-2])
        self.assertEqual([s for s, _ in na.scan(yesterday, {na.STRATEGY_HYBRID})], ["DIP"])
        self.assertEqual(na.scan(self.stocks, {na.STRATEGY_HYBRID}), [])

    def test_falling_market_is_silent(self):
        stocks, days = market(drift=-0.001)
        stocks["DIP"] = make("DIP", dip(walk(300, 0.001, seed=99)), days)
        self.assertEqual(na.scan(stocks, {na.STRATEGY_HYBRID}), [])

    def test_bonus_share_adjustment_is_not_a_dip(self):
        closes = walk(300, 0.001, seed=99)
        closes[-1] = closes[-2] * 0.7  # unadjusted 1:0.43 bonus: a 30% "drop" NEPSE's band can't produce
        self.stocks["DIP"] = make("DIP", closes, self.days)
        self.assertEqual(na.scan(self.stocks, {na.STRATEGY_HYBRID}), [])

    def test_at_most_four_buys_a_day_most_oversold_first(self):
        for k, depth in enumerate((-0.07, -0.075, -0.08, -0.085, -0.09)):
            self.stocks[f"D{k}"] = make(f"D{k}", dip(walk(300, 0.001, seed=50 + k), (-0.02, depth)), self.days)
        found = na.scan(self.stocks, {na.STRATEGY_HYBRID})
        self.assertEqual(len(found), na.MAX_POSITIONS)
        zs = [s.values["zscore"] for _, s in found]
        self.assertEqual(zs, sorted(zs))

    def test_illiquid_or_stale_stocks_are_not_bought(self):
        stocks, days = market(stocks=na.LIQUID_STOCKS, volume=5000)
        stocks["DIP"] = make("DIP", dip(walk(300, 0.001, seed=99)), days, volume=10)  # not among the 100 most traded
        self.assertEqual(na.scan(stocks, {na.STRATEGY_HYBRID}), [])
        self.stocks["DIP"] = make("DIP", dip(walk(300, 0.001, seed=99))[:-1], self.days[:-1])  # didn't trade today
        self.assertEqual(na.scan(self.stocks, {na.STRATEGY_HYBRID}), [])


class SeasonalTests(SimpleTestCase):
    def setUp(self):
        # 2026-02-13 is a Friday, so the first Falgun session is Sunday 15 February.
        self.stocks, self.days = market(n=200, end=date(2026, 3, 20), drift=0.002, stocks=8)

    def scan(self, day, stocks=None):
        return na.scan(upto(stocks or self.stocks, day), {na.STRATEGY_SEASONAL})

    def test_first_falgun_session_buys_the_five_strongest_uptrends(self):
        self.assertEqual(self.scan(date(2026, 2, 12)), [])
        found = self.scan(date(2026, 2, 15))
        self.assertEqual(len(found), na.SEASONAL_PICKS)
        changes = [s.values["six_month_pct"] for _, s in found]
        self.assertEqual(changes, sorted(changes, reverse=True))
        self.assertEqual(draft(found[0][1], 100).horizon, na.SEASON_SESSIONS)
        self.assertIsNone(draft(found[0][1], 100).target_price)
        self.assertEqual(self.scan(date(2026, 2, 16)), [])  # still in their uptrends: no new entries

    def test_stocks_joining_an_uptrend_during_falgun_and_only_once(self):
        days = self.days
        closes = [100.0] * len(days)
        i = days.index(date(2026, 2, 18))
        for k in range(i, len(days)):
            closes[k] = 101.0 + (k - i)  # crosses above its 50-day average on 18 February
        j = days.index(date(2026, 2, 24))
        closes[j] = 95  # falls back under its 50-day average, then recovers the next day
        self.stocks["LATE"] = make("LATE", closes, days, volume=10_000)
        self.assertNotIn("LATE", [s for s, _ in self.scan(date(2026, 2, 15))])
        self.assertIn("LATE", [s for s, _ in self.scan(date(2026, 2, 18))])
        self.assertNotIn("LATE", [s for s, _ in self.scan(date(2026, 2, 25))])

    def test_outside_falgun_is_silent(self):
        for day in (date(2025, 12, 1), date(2026, 3, 15), date(2026, 3, 19)):
            if day in self.days:
                self.assertEqual(self.scan(day), [], day)

    def test_downtrends_are_not_bought(self):
        stocks, days = market(n=200, end=date(2026, 3, 20), drift=-0.002)
        # A bounce above the 50-day average is not enough while the stock is still down over six months.
        bounce = walk(200, -0.002, seed=3, noise=0.0)
        i = days.index(date(2026, 2, 15))
        for k in range(i - 9, len(bounce)):
            bounce[k] = bounce[k - 1] * 1.02
        stocks["BOUNCE"] = make("BOUNCE", bounce, days)
        self.assertGreater(bounce[i], sum(bounce[i - 49:i + 1]) / 50)
        self.assertEqual(self.scan(date(2026, 2, 15), stocks), [])


class MomentumTests(SimpleTestCase):
    def test_first_session_of_the_month_buys_the_best_year_skipping_the_last_month(self):
        stocks, days = market(n=300, end=date(2026, 9, 1))
        self.assertEqual(days[-1], date(2026, 9, 1))
        strong = walk(300, 0.003, seed=7)
        strong[-10:] = [strong[-11] * 0.97 ** k for k in range(1, 11)]  # fell over the last two weeks
        stocks["STAR"] = make("STAR", strong, days)
        stocks["LOSER"] = make("LOSER", walk(300, -0.002, seed=8), days)
        found = na.scan(stocks, {na.STRATEGY_MOMENTUM})
        symbols = [s for s, _ in found]
        self.assertEqual(len(found), na.MOMENTUM_PICKS)
        self.assertEqual(symbols[0], "STAR")
        self.assertNotIn("LOSER", symbols)
        self.assertEqual(draft(found[0][1], strong[-1]).horizon, 20)
        self.assertEqual(na.scan(upto(stocks, days[-2]), {na.STRATEGY_MOMENTUM}), [])  # 31 August: mid-month

    def test_bonus_adjustment_does_not_hide_a_winner(self):
        stocks, days = market(n=300, end=date(2026, 9, 1))
        strong = walk(300, 0.003, seed=7)
        strong[100:] = [c * 0.6 for c in strong[100:]]  # bonus shares, unadjusted
        stocks["STAR"] = make("STAR", strong, days)
        self.assertEqual(na.scan(stocks, {na.STRATEGY_MOMENTUM})[0][0], "STAR")

    def test_falling_market_or_short_history_is_silent(self):
        stocks, _ = market(n=300, drift=-0.001, end=date(2026, 9, 1))
        self.assertEqual(na.scan(stocks, {na.STRATEGY_MOMENTUM}), [])
        stocks, _ = market(n=230, end=date(2026, 9, 1))
        self.assertEqual(na.scan(stocks, {na.STRATEGY_MOMENTUM}), [])


class LiveRunTests(TestCase):
    def test_full_run_stores_nepsealpha_calls_as_predictions(self):
        from datetime import datetime, time
        from decimal import Decimal
        from unittest import mock
        from zoneinfo import ZoneInfo

        from modules.analysis.infrastructure.models import Prediction, Signal
        from modules.analysis.tasks import on_candles_ingested
        from modules.marketdata.domain.entities import Candle, Timeframe
        from modules.marketdata.infrastructure import repositories as market_repo

        stocks, days = market(n=300, end=date(2026, 9, 1))
        stocks["DIP"] = make("DIP", dip(walk(300, 0.001, seed=99)), days)
        npt = ZoneInfo("Asia/Kathmandu")
        for s in stocks.values():
            market_repo.upsert_candles([
                Candle(s.symbol, Timeframe.DAILY, datetime.combine(d, time(15), tzinfo=npt), d, Decimal(f"{c:.2f}"),
                       Decimal(f"{c * 1.01:.2f}"), Decimal(f"{c * 0.99:.2f}"), Decimal(f"{c:.2f}"), 1000, None, None, 10)
                for d, c in zip(s.dates, s.closes)
            ])
        with mock.patch("modules.analysis.application.run.events.publish"):
            on_candles_ingested.delay(5, "1D", days[-1].isoformat(), sorted(stocks)).get()
        calls = set(Signal.objects.filter(strategy__startswith="nepsealpha").values_list("strategy", "symbol"))
        self.assertIn(("nepsealpha_hybrid", "DIP"), calls)
        self.assertTrue(any(name == "nepsealpha_momentum" for name, _ in calls))  # 1 September: rebalance day
        p = Prediction.objects.get(strategy="nepsealpha_hybrid", symbol="DIP")
        self.assertEqual(p.horizon, 20)
        self.assertIsNotNone(p.stop_price)
        self.assertIsNotNone(p.target_price)
