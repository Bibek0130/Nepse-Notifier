from datetime import date
from decimal import Decimal
from pathlib import Path

from django.test import SimpleTestCase

from modules.marketdata.domain.ports import SourceError
from modules.marketdata.infrastructure.sources.merolagani import MeroLaganiSource
from modules.marketdata.infrastructure.sources.parsing import normalise_header, to_decimal
from modules.marketdata.infrastructure.sources.sharesansar import ShareSansarSource

FIXTURES = Path(__file__).parent / "fixtures"


class HelperTests(SimpleTestCase):
    def test_to_decimal(self):
        self.assertEqual(to_decimal("1,234.50"), Decimal("1234.50"))
        self.assertEqual(to_decimal("-3.52%"), Decimal("-3.52"))
        self.assertEqual(to_decimal("(4.5)"), Decimal("-4.5"))
        self.assertIsNone(to_decimal("-"))
        self.assertIsNone(to_decimal("abc"))

    def test_normalise_header_keeps_percent_distinct(self):
        self.assertEqual(normalise_header("Diff"), "diff")
        self.assertEqual(normalise_header("Diff %"), "diffpct")
        self.assertEqual(normalise_header("% Change"), "pctchange")
        self.assertEqual(normalise_header("Prev. Close"), "prevclose")


class ShareSansarTests(SimpleTestCase):
    def test_parses_rows_and_skips_untraded(self):
        quotes = ShareSansarSource().parse((FIXTURES / "sharesansar.html").read_text())
        self.assertEqual([q.symbol for q in quotes], ["NABIL", "NICA"])
        nabil = quotes[0]
        self.assertEqual((nabil.ltp, nabil.open, nabil.previous_close), (Decimal("510.00"), Decimal("500.00"), Decimal("502.00")))
        self.assertEqual(nabil.change_percent, Decimal("1.59"))  # "Diff %", not "Diff"
        self.assertEqual((nabil.volume, nabil.trades), (123456, 1234))
        self.assertEqual(nabil.turnover, Decimal("62345678.90"))

    def test_missing_table_raises(self):
        with self.assertRaises(SourceError):
            ShareSansarSource().parse("<html><body>maintenance</body></html>")


class MeroLaganiTests(SimpleTestCase):
    def test_parses_live_table(self):
        quotes = MeroLaganiSource().parse((FIXTURES / "merolagani.html").read_text())
        self.assertEqual([q.symbol for q in quotes], ["NABIL", "UPPER"])
        self.assertEqual(quotes[1].change_percent, Decimal("-0.84"))
        self.assertEqual(quotes[1].volume, 9870)
        self.assertIsNone(quotes[1].turnover)

    def test_parses_history_payload(self):
        # 2025-10-11 and 2025-10-12 00:00 NPT as UTC epoch seconds.
        payload = {"s": "ok", "t": [1760120100, 1760206500], "o": [500, 505], "h": [510, 515], "l": [495, 500], "c": [505, 512.5], "v": [1000, 2000]}
        bars = MeroLaganiSource.parse_history(payload)
        self.assertEqual([b.date for b in bars], [date(2025, 10, 11), date(2025, 10, 12)])
        self.assertEqual((bars[1].close, bars[1].volume), (Decimal("512.5"), 2000))

    def test_no_data_and_bad_payload(self):
        self.assertEqual(MeroLaganiSource.parse_history({"s": "no_data"}), [])
        with self.assertRaises(SourceError):
            MeroLaganiSource.parse_history({"s": "ok", "t": [1]})
