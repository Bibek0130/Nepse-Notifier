"""Turn an analysis report into a subscriber's digest. Pure Python.

The email carries only the best picks: stocks the quant strategies call a buy whose
trade levels offer at least ``MIN_RISK_REWARD`` reward per rupee of risk, top ``TOP_PICKS``.
"""
from dataclasses import dataclass, field

TOP_PICKS = 3
MIN_RISK_REWARD = 2.0  # 1:2 or better, from the stock's trade levels at today's price
STRATEGY_LABELS = {
    "quant_momentum": "Quant momentum", "quant_reversion": "Quant mean reversion", "pca_leaders": "PCA sector leaders",
    "nepsealpha_hybrid": "NepseAlpha hybrid", "nepsealpha_seasonal": "NepseAlpha seasonal",
}


@dataclass(frozen=True)
class Preferences:
    watchlist: frozenset[str] = frozenset()
    include_intraday: bool = True


@dataclass
class StockItem:
    """One top pick and why it was picked."""

    symbol: str
    strategies: list[str]  # the quant strategies calling it a buy
    max_strength: int
    messages: list[str]  # quant calls first, then the stock's other signals
    risk_reward: float
    close: float | None = None
    rsi: float | None = None
    support: float | None = None
    resistance: float | None = None
    projected_close: float | None = None
    plan: dict | None = None  # trade levels: zones, stop, target, risk-to-reward

    @property
    def strategy_labels(self):
        return ", ".join(STRATEGY_LABELS.get(name, name) for name in self.strategies)


@dataclass
class WatchItem:
    """A watched stock's latest price, shown whether or not it is a pick."""

    symbol: str
    close: float | None = None
    change_percent: float | None = None
    is_pick: bool = False
    plan: dict | None = None


@dataclass
class DigestContent:
    trading_date: str
    provisional: bool
    picks: list[StockItem] = field(default_factory=list)
    candidates: int = 0  # quant buy calls before the risk-reward filter and the top-N cut
    market: dict | None = None
    watchlist: list[WatchItem] = field(default_factory=list)
    track_record: list[dict] = field(default_factory=list)  # per-strategy hit rate of settled predictions
    track_record_since: str | None = None
    top_n: int = TOP_PICKS
    min_risk_reward: float = MIN_RISK_REWARD

    @property
    def stock_count(self):
        return len(self.picks)

    @property
    def is_empty(self):
        """Midday updates go out only with picks; the market-close email always goes, saying so when nothing qualified."""
        return self.provisional and not self.picks


def wants_run(prefs: Preferences, provisional: bool) -> bool:
    return prefs.include_intraday or not provisional


def select_picks(report: dict, quant_strategies, top_n=TOP_PICKS, min_risk_reward=MIN_RISK_REWARD):
    """The quant strategies' buy calls with risk:reward of at least ``min_risk_reward``, best first.

    A stock with a quant sell call (e.g. the momentum exit) is skipped. Ranked by how many
    quant strategies agree, then the strongest call, then risk:reward. Returns (picks, candidates).
    """
    quant = set(quant_strategies)
    by_symbol = {}
    for s in report["signals"]:
        by_symbol.setdefault(s["symbol"], []).append(s)

    ranked, candidates = [], 0
    for symbol, signals in by_symbol.items():
        calls = [s for s in signals if s["strategy"] in quant]
        buys = [s for s in calls if s["direction"] == "bullish"]
        if not buys or any(s["direction"] == "bearish" for s in calls):
            continue
        candidates += 1
        analysis = report["analyses"].get(symbol, {})
        plan = analysis.get("trade_plan") or report.get("trade_plans", {}).get(symbol)
        rr = (plan or {}).get("risk_reward")
        if rr is None or rr < min_risk_reward:
            continue
        buys.sort(key=lambda s: -s["strength"])
        others = sorted((s for s in signals if s["strategy"] not in quant), key=lambda s: -s["strength"])
        indicators = analysis.get("indicators", {})
        ranked.append(StockItem(
            symbol=symbol,
            strategies=sorted({s["strategy"] for s in buys}),
            max_strength=buys[0]["strength"],
            messages=[s["message"] for s in buys + others],
            risk_reward=rr,
            close=indicators.get("close"),
            rsi=round(indicators["rsi14"]) if indicators.get("rsi14") is not None else None,
            support=analysis.get("support"),
            resistance=analysis.get("resistance"),
            projected_close=(analysis.get("forecast") or {}).get("projected_close"),
            plan=plan,
        ))
    ranked.sort(key=lambda i: (-len(i.strategies), -i.max_strength, -i.risk_reward, i.symbol))
    return ranked[:top_n], candidates


def watchlist_items(prefs: Preferences, quotes: list[dict] | None, picked: set, plans: dict) -> list[WatchItem]:
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
            is_pick=symbol in picked,
            # Picks show their levels in the picks section.
            plan=None if symbol in picked else plans.get(symbol),
        ))
    return items


def build_digest(
    report: dict, prefs: Preferences, market: dict | None = None, quotes: list[dict] | None = None,
    scorecard: dict | None = None, quant_strategies=(),
) -> DigestContent:
    """The top quant picks for this run, plus the subscriber's watchlist prices and the strategies' track record.

    Picks are chosen across the whole market; the watchlist only adds its own price section.
    """
    picks, candidates = select_picks(report, quant_strategies)
    content = DigestContent(
        trading_date=report["trading_date"], provisional=report["provisional"], market=market,
        picks=picks, candidates=candidates,
    )
    content.watchlist = watchlist_items(prefs, quotes, {p.symbol for p in picks}, report.get("trade_plans", {}))
    if scorecard:
        content.track_record = [r for r in scorecard["strategies"] if r["settled"]]
        content.track_record_since = scorecard["since"]
    return content


def subject_line(content: DigestContent) -> str:
    when = "Midday update" if content.provisional else "Market close"
    if content.picks:
        what = "top pick" + ("s" if len(content.picks) > 1 else "") + " " + ", ".join(p.symbol for p in content.picks)
    else:
        what = f"no quant pick at 1:{content.min_risk_reward:g} or better"
    return f"NEPSE {when} {content.trading_date}: {what}"
