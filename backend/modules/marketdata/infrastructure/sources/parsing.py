"""HTML/number parsing helpers shared by the scrapers."""
import re
from decimal import Decimal, InvalidOperation

from ...domain.entities import Quote
from ...domain.ports import SourceError


def to_decimal(value):
    """Parse '1,234.50', '-12.3%', '(4.5)' or '' into a Decimal or None."""
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("%", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    if text in {"", "-", "--", "N/A", "NaN"}:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def to_int(value):
    number = to_decimal(value)
    return int(number) if number is not None else None


def normalise_header(text):
    """'Prev. Close' -> 'prevclose', 'Diff %' -> 'diffpct', '% Change' -> 'pctchange'."""
    return re.sub(r"[^a-z0-9]", "", text.lower().replace("%", "pct"))


def find_table(soup, header):
    """First <table> that has a header cell reading ``header`` (case-insensitive)."""
    for table in soup.find_all("table"):
        if any(th.get_text(strip=True).lower() == header for th in table.find_all("th")):
            return table
    return None


def parse_table(table, aliases):
    """Read an HTML <table> into dicts keyed by our field names.

    ``aliases`` maps a field name to the normalised header texts it may appear
    under, so small wording changes on the site don't break parsing.
    """
    header_row = table.find("thead") or table
    headers = [normalise_header(th.get_text()) for th in header_row.find_all("th")]
    if not headers:
        raise SourceError("table has no header row")

    column_for = {}
    for field_name, candidates in aliases.items():
        for candidate in candidates:
            if candidate in headers:
                column_for[field_name] = headers.index(candidate)
                break

    body = table.find("tbody") or table
    rows = []
    for tr in body.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(cells) < len(headers) // 2:
            continue  # header or spacer row
        rows.append({name: cells[idx] for name, idx in column_for.items() if idx < len(cells)})
    return rows, column_for


def quotes_from_rows(rows, source_name):
    quotes = []
    for row in rows:
        ltp = to_decimal(row.get("ltp"))
        symbol = (row.get("symbol") or "").strip().upper()
        if not symbol or ltp is None:
            continue
        quotes.append(
            Quote(
                symbol=symbol,
                ltp=ltp,
                open=to_decimal(row.get("open")),
                high=to_decimal(row.get("high")),
                low=to_decimal(row.get("low")),
                previous_close=to_decimal(row.get("previous_close")),
                change_percent=to_decimal(row.get("change_percent")),
                volume=to_int(row.get("volume")) or 0,
                turnover=to_decimal(row.get("turnover")),
                trades=to_int(row.get("trades")),
            )
        )
    if not quotes:
        raise SourceError(f"{source_name}: table had no rows")
    return quotes
