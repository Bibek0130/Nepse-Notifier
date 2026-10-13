from bs4 import BeautifulSoup

from ...domain.ports import SourceError
from .http import HttpSource
from .parsing import find_table, parse_table, quotes_from_rows

ALIASES = {
    "symbol": ["symbol"],
    "open": ["open"],
    "high": ["high"],
    "low": ["low"],
    "ltp": ["close", "ltp"],
    "previous_close": ["prevclose", "previousclose"],
    "volume": ["vol", "volume"],
    "turnover": ["turnover"],
    "trades": ["trans", "transactions", "notrans"],
    "change_percent": ["diffpct", "pctchange", "changepct"],
}


class ShareSansarSource(HttpSource):
    """sharesansar.com "Today's share price": OHLC, volume, turnover and transactions in one table."""

    name = "sharesansar"
    url = "https://www.sharesansar.com/today-share-price"

    def parse(self, body):
        soup = BeautifulSoup(body, "html.parser")
        table = soup.find("table", id="headFixed") or find_table(soup, "symbol")
        if table is None:
            raise SourceError("sharesansar: price table not found")
        rows, columns = parse_table(table, ALIASES)
        if "symbol" not in columns or "ltp" not in columns:
            raise SourceError(f"sharesansar: unexpected columns {sorted(columns)}")
        return quotes_from_rows(rows, self.name)
