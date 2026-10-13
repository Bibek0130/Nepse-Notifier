from datetime import date, datetime, timezone
from decimal import Decimal as D

from django.test import SimpleTestCase

from modules.marketdata.domain.entities import Candle, Timeframe
from modules.marketdata.domain.validation import ValidationContext, validate

DAY = date(2026, 10, 12)
TS = datetime(2026, 10, 12, 9, 30, tzinfo=timezone.utc)


def candle(symbol="NABIL", o="500", h="512", l="498", c="510", volume=1000, prev="502", turnover=None, day=DAY):
    return Candle(symbol, Timeframe.INTRADAY_3H, TS, day, D(o), D(h), D(l), D(c), volume, D(prev) if prev else None, D(turnover) if turnover else None)


def ctx(**kwargs):
    return ValidationContext(trading_date=DAY, is_trading_day=True, **kwargs)


class ValidationTests(SimpleTestCase):
    def rules(self, result):
        return {issue.rule for _, issues in result.quarantined + result.flagged for issue in issues}

    def test_good_candle_is_accepted(self):
        result = validate([candle(turnover="505000")], ctx())
        self.assertEqual(len(result.accepted), 1)
        self.assertFalse(result.quarantined or result.flagged)

    def test_ohlc_inconsistent_is_quarantined(self):
        result = validate([candle(h="505")], ctx())  # close 510 above high
        self.assertFalse(result.accepted)
        self.assertEqual(self.rules(result), {"ohlc_consistent"})

    def test_non_positive_price(self):
        self.assertEqual(self.rules(validate([candle(l="0")], ctx())), {"ohlc_positive"})

    def test_turnover_out_of_range(self):
        self.assertEqual(self.rules(validate([candle(turnover="5000")], ctx())), {"turnover_matches"})

    def test_price_band(self):
        result = validate([candle(o="560", h="565", l="555", c="560", prev="500")], ctx())
        self.assertEqual(self.rules(result), {"price_band"})
        self.assertFalse(result.accepted)

    def test_price_band_uses_stored_previous_close(self):
        result = validate([candle(o="560", h="565", l="555", c="560", prev=None)], ctx(previous_closes={"NABIL": D("500")}))
        self.assertEqual(self.rules(result), {"price_band"})

    def test_price_band_flag_only_for_corporate_action(self):
        result = validate([candle(o="400", h="405", l="398", c="400", prev="500")], ctx(adjusted_symbols=frozenset({"NABIL"})))
        self.assertEqual(len(result.accepted), 1)
        self.assertEqual(self.rules(result), {"price_band"})

    def test_non_trading_day_and_future_date(self):
        closed = ValidationContext(trading_date=DAY, is_trading_day=False)
        self.assertEqual(self.rules(validate([candle()], closed)), {"trading_day"})
        self.assertEqual(self.rules(validate([candle(day=date(2026, 10, 13))], ctx())), {"future_date"})

    def test_duplicates_are_quarantined(self):
        result = validate([candle(), candle()], ctx())
        self.assertEqual(len(result.quarantined), 2)
        self.assertEqual(self.rules(result), {"duplicate_symbol"})

    def test_cross_source_disagreement_is_flagged(self):
        result = validate([candle()], ctx(reference_closes={"NABIL": D("520")}))
        self.assertEqual(len(result.accepted), 1)
        self.assertEqual(self.rules(result), {"cross_source"})
