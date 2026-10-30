import csv
import io
from datetime import date

from ...domain.entities import HistoricalBar
from ...domain.ports import SourceError
from .http import HttpSource
from .parsing import to_decimal

CSV_URL = "https://raw.githubusercontent.com/Aabishkar2/nepse-data/main/data/company-wise/{symbol}.csv"


class NepseDataSource(HttpSource):
    """Daily history from the public Aabishkar2/nepse-data repository, one CSV per company.

    Used to seed the hosted demo, which can't reach sharesansar or merolagani. Prices are
    not adjusted for bonus or rights shares, as NEPSE published them.
    """

    name = "nepse_data"

    def fetch_history(self, symbol, start, end):
        response = self.get(CSV_URL.format(symbol=symbol))
        return [b for b in self.parse_history(response.text) if start <= b.date <= end]

    @staticmethod
    def parse_history(body):
        """Parse published_date,open,high,low,close,per_change,traded_quantity,traded_amount,status rows.

        Rows with a missing or non-positive price are skipped; a date listed twice keeps its last row.
        """
        reader = csv.DictReader(io.StringIO(body))
        missing = {"published_date", "open", "high", "low", "close"} - set(reader.fieldnames or [])
        if missing:
            raise SourceError(f"nepse_data: CSV missing columns {sorted(missing)}")
        by_date = {}
        for row in reader:
            try:
                day = date.fromisoformat(row["published_date"].strip())
            except ValueError:
                continue
            prices = [_positive(row[k]) for k in ("open", "high", "low", "close")]
            if None in prices:
                continue
            volume = _positive(row.get("traded_quantity"))
            by_date[day] = HistoricalBar(day, *prices, volume=int(volume or 0), turnover=_positive(row.get("traded_amount")))
        return [by_date[d] for d in sorted(by_date)]


def _positive(value):
    number = to_decimal(value)
    if number is None or not number.is_finite() or number <= 0:
        return None
    return number
