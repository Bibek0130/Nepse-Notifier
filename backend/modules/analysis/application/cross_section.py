"""Use case: run the strategies that compare stocks with each other (pairs, basket) over a whole run."""
import logging

from modules.marketdata import public as marketdata

from ..domain import stat_arb
from ..infrastructure import repositories
from ..infrastructure.models import AnalysisRun, SymbolAnalysis
from .series import load_series

logger = logging.getLogger(__name__)

MARKET_GROUP_SIZE = 60  # most-traded stocks compared with each other when sectors are unknown


def _turnover(series):
    recent = list(zip(series.closes[-20:], series.volumes[-20:]))
    return sum(c * v for c, v in recent) / len(recent) if recent else 0


def groups_for(series_by_symbol, sectors):
    """Sector groups where sectors are known; the most-traded unknown-sector stocks form one "market" group."""
    groups, unknown = {}, []
    for symbol in series_by_symbol:
        sector = (sectors.get(symbol) or "").strip()
        if sector:
            groups.setdefault(sector, []).append(symbol)
        else:
            unknown.append(symbol)
    unknown.sort(key=lambda s: -_turnover(series_by_symbol[s]))
    if unknown:
        groups["market"] = unknown[:MARKET_GROUP_SIZE]
    return groups


def run_cross_sectional(run_id, enabled):
    """Add pairs / basket signals to a run's analysed symbols. Returns how many were added."""
    if not enabled & {stat_arb.STRATEGY_PAIRS, stat_arb.STRATEGY_BASKET}:
        return 0
    run = AnalysisRun.objects.get(pk=run_id)
    symbols = list(SymbolAnalysis.objects.filter(run=run).values_list("symbol", flat=True))
    series = {s: load_series(s, run.trading_date, run.timeframe) for s in symbols}
    series = {s: v for s, v in series.items() if len(v) >= stat_arb.LOOKBACK}
    groups = groups_for(series, marketdata.get_sectors())
    found = stat_arb.scan(
        {s: v.dates for s, v in series.items()}, {s: v.closes for s, v in series.items()}, groups,
    )
    found = [(symbol, signal) for symbol, signal in found if signal.strategy in enabled]
    repositories.add_signals(run_id, found)
    logger.info("Run %s: %d cross-sectional signals over %d groups", run_id, len(found), len(groups))
    return len(found)
