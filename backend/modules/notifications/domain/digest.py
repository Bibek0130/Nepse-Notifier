"""Turn an analysis report into a subscriber's digest. Pure Python."""
from dataclasses import dataclass, field

DIRECTION_ORDER = {"bullish": 0, "bearish": 1, "neutral": 2}


@dataclass(frozen=True)
class Preferences:
    min_strength: int = 2
    watchlist: frozenset[str] = frozenset()  # empty means every symbol
    include_intraday: bool = True


@dataclass
class StockItem:
    """Everything the digest says about one symbol."""

    symbol: str
    direction: str  # net direction of its signals
    max_strength: int
    messages: list[str]
    close: float | None = None
    rsi: float | None = None
    support: float | None = None
    resistance: float | None = None
    projected_close: float | None = None


@dataclass
class WatchItem:
    """A watched stock's latest price, shown whether or not it has signals."""

    symbol: str
    close: float | None = None
    change_percent: float | None = None
    signal_count: int = 0


@dataclass
class DigestContent:
    trading_date: str
    provisional: bool
    strong: list[StockItem] = field(default_factory=list)
    bullish: list[StockItem] = field(default_factory=list)
    bearish: list[StockItem] = field(default_factory=list)
    activity: list[StockItem] = field(default_factory=list)
    market: dict | None = None
    watchlist: list[WatchItem] = field(default_factory=list)

    @property
    def stock_count(self):
        return len(self.strong) + len(self.bullish) + len(self.bearish) + len(self.activity)

    @property
    def is_empty(self):
        """Nothing worth an email. A watchlist alone justifies one only at market close, not midday."""
        return self.stock_count == 0 and (self.provisional or not self.watchlist)


def wants_run(prefs: Preferences, provisional: bool) -> bool:
    return prefs.include_intraday or not provisional


def select_signals(signals, prefs: Preferences):
    return [
        s for s in signals
        if s["strength"] >= prefs.min_strength and (not prefs.watchlist or s["symbol"] in prefs.watchlist)
    ]


def _net_direction(signals):
    score = sum(1 if s["direction"] == "bullish" else -1 if s["direction"] == "bearish" else 0 for s in signals)
    return "bullish" if score > 0 else "bearish" if score < 0 else "neutral"


def watchlist_items(prefs: Preferences, quotes: list[dict] | None, by_symbol: dict) -> list[WatchItem]:
    if not prefs.watchlist or quotes is None:
        return []
    latest = {q["symbol"]: q for q in quotes}
    items = []
    for symbol in sorted(prefs.watchlist):
        q = latest.get(symbol, {})
        close = q.get("close")
        items.append(WatchItem(
            symbol=symbol,
            close=float(close) if close is not None else None,
            change_percent=q.get("change_percent"),
            signal_count=len(by_symbol.get(symbol, [])),
        ))
    return items


def build_digest(report: dict, prefs: Preferences, market: dict | None = None, quotes: list[dict] | None = None) -> DigestContent:
    """Group the report's signals by symbol and sort them into digest sections.

    Symbols with any strength-3 signal go under "strong"; the rest by net direction.
    With a watchlist and ``quotes``, every watched stock's latest price is listed too.
    """
    content = DigestContent(trading_date=report["trading_date"], provisional=report["provisional"], market=market)
    by_symbol = {}
    for signal in select_signals(report["signals"], prefs):
        by_symbol.setdefault(signal["symbol"], []).append(signal)

    for symbol, signals in by_symbol.items():
        signals.sort(key=lambda s: -s["strength"])
        analysis = report["analyses"].get(symbol, {})
        indicators = analysis.get("indicators", {})
        item = StockItem(
            symbol=symbol,
            direction=_net_direction(signals),
            max_strength=max(s["strength"] for s in signals),
            messages=[s["message"] for s in signals],
            close=indicators.get("close"),
            rsi=round(indicators["rsi14"]) if indicators.get("rsi14") is not None else None,
            support=analysis.get("support"),
            resistance=analysis.get("resistance"),
            projected_close=(analysis.get("forecast") or {}).get("projected_close"),
        )
        if item.max_strength >= 3:
            content.strong.append(item)
        elif item.direction == "bullish":
            content.bullish.append(item)
        elif item.direction == "bearish":
            content.bearish.append(item)
        else:
            content.activity.append(item)

    for section in (content.strong, content.bullish, content.bearish, content.activity):
        section.sort(key=lambda i: (-i.max_strength, DIRECTION_ORDER[i.direction], i.symbol))
    content.watchlist = watchlist_items(prefs, quotes, by_symbol)
    return content


def subject_line(content: DigestContent) -> str:
    when = "Midday update" if content.provisional else "Market close"
    parts = []
    if content.strong:
        parts.append(f"{len(content.strong)} strong")
    if content.bullish:
        parts.append(f"{len(content.bullish)} bullish")
    if content.bearish:
        parts.append(f"{len(content.bearish)} bearish")
    if content.activity:
        parts.append(f"{len(content.activity)} unusual activity")
    if not parts:
        parts.append("your watchlist")
    return f"NEPSE {when} {content.trading_date}: " + ", ".join(parts)
