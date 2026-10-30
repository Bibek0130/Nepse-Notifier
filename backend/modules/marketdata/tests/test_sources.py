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


class NepseDataTests(SimpleTestCase):
    CSV = (
        "published_date,open,high,low,close,per_change,traded_quantity,traded_amount,status\n"
        "2026-10-28,542.0,547.0,542.0,545.0,0.55,48530.0,26428487.1,1\n"
        "2026-10-27,543.0,545.0,540.0,542.0,-0.18,26465.0,14363999.9,-1\n"  # out of order
        "2026-10-26,nan,545.0,540.0,542.0,nan,100.0,54200.0,0\n"  # missing open
        "2026-10-25,0.0,545.0,540.0,542.0,0,0.0,0.0,0\n"  # no trade
        "not-a-date,1,1,1,1,0,1,1,0\n"
        "2026-10-29,518.0,552.9,518.0,552.0,1.28,72855.0,nan,1\n"
        "2026-10-29,520.0,552.9,518.0,551.0,1.10,72855.0,40132445.7,1\n"  # listed twice: last row wins
    )

    def test_parses_sorts_and_skips_bad_rows(self):
        from modules.marketdata.infrastructure.sources.nepse_data import NepseDataSource

        bars = NepseDataSource.parse_history(self.CSV)
        self.assertEqual([b.date for b in bars], [date(2026, 10, 27), date(2026, 10, 28), date(2026, 10, 29)])
        last = bars[-1]
        self.assertEqual((last.open, last.close, last.volume, last.turnover), (Decimal("520.0"), Decimal("551.0"), 72855, Decimal("40132445.7")))
        self.assertEqual(bars[0].turnover, Decimal("14363999.9"))

    def test_missing_columns_raise(self):
        from modules.marketdata.infrastructure.sources.nepse_data import NepseDataSource

        with self.assertRaises(SourceError):
            NepseDataSource.parse_history("date,price\n2026-10-29,500\n")

    def test_fetch_keeps_only_the_requested_window(self):
        from unittest import mock

        from modules.marketdata.infrastructure.sources.nepse_data import NepseDataSource

        source = NepseDataSource(session=mock.Mock())
        source.session.get.return_value = mock.Mock(text=self.CSV, status_code=200, raise_for_status=lambda: None)
        bars = source.fetch_history("NABIL", date(2026, 10, 28), date(2026, 10, 28))
        self.assertEqual([b.date for b in bars], [date(2026, 10, 28)])
        self.assertIn("/NABIL.csv", source.session.get.call_args.args[0])
