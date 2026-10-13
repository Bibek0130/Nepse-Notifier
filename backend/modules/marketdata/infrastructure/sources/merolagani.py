from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from ...domain.entities import HistoricalBar
from ...domain.ports import SourceError
from .http import HttpSource
from .parsing import find_table, parse_table, quotes_from_rows, to_decimal, to_int

NPT = ZoneInfo("Asia/Kathmandu")
CHART_URL = "https://merolagani.com/handlers/TechnicalChartHandler.ashx"

ALIASES = {
    "symbol": ["symbol"],
    "ltp": ["ltp"],
    "change_percent": ["pctchange", "changepct"],
    "open": ["open"],
    "high": ["high"],
    "low": ["low"],
    "volume": ["qty", "volume"],
    "previous_close": ["pclose", "prevclose"],
}


class MeroLaganiSource(HttpSource):
    """merolagani.com live market (fallback snapshots) and chart endpoint (history)."""

    name = "merolagani"
    url = "https://merolagani.com/LatestMarket.aspx"

    def parse(self, body):
        soup = BeautifulSoup(body, "html.parser")
        table = soup.find("table", class_="live-trading") or find_table(soup, "symbol")
        if table is None:
            raise SourceError("merolagani: live market table not found")
        rows, columns = parse_table(table, ALIASES)
        if "symbol" not in columns or "ltp" not in columns:
            raise SourceError(f"merolagani: unexpected columns {sorted(columns)}")
        return quotes_from_rows(rows, self.name)

    def fetch_history(self, symbol, start, end):
        params = {
            "type": "get_advanced_chart",
            "symbol": symbol,
            "resolution": "1D",
            "rangeStartDate": _unix(start),
            "rangeEndDate": _unix(end, end_of_day=True),
            "isAdjust": 1,
            "currencyCode": "NPR",
        }
        try:
            payload = self.get(CHART_URL, params=params).json()
        except ValueError as exc:
            raise SourceError(f"merolagani: history for {symbol} was not JSON") from exc
        return self.parse_history(payload)

    @staticmethod
    def parse_history(payload):
        """Parse TradingView-style arrays: {"s": "ok", "t": [...], "o": [...], ...}."""
        if payload.get("s") == "no_data":
            return []
        try:
            columns = zip(payload["t"], payload["o"], payload["h"], payload["l"], payload["c"], payload.get("v") or [])
        except KeyError as exc:
            raise SourceError(f"merolagani: history payload missing {exc}") from exc
        bars = []
        for ts, o, h, l, c, v in columns:
            values = [to_decimal(x) for x in (o, h, l, c)]
            if None in values:
                continue
            # Timestamps are midnight NPT expressed in UTC, so take the date in NPT.
            day = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(NPT).date()
            bars.append(HistoricalBar(day, *values, volume=to_int(v) or 0))
        return bars


def _unix(day: date, end_of_day=False):
    moment = datetime.combine(day, time(23, 59, 59) if end_of_day else time.min, tzinfo=NPT)
    return int(moment.timestamp())
