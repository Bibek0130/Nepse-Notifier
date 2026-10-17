from datetime import timedelta

from django.utils import timezone

from ..domain.predictions import summarize
from ..domain.strategies import DESCRIPTIONS
from ..infrastructure.models import (
    AnalysisRun, BacktestRun, Prediction, QuantEvaluation, Signal, StrategySetting, SymbolAnalysis,
)
from .quant import can_replay
from .strategies import sync_settings


def signal_dict(s: Signal):
    return {
        "symbol": s.symbol,
        "trading_date": s.trading_date.isoformat(),
        "strategy": s.strategy,
        "direction": s.direction,
        "strength": s.strength,
        "message": s.message,
        "values": s.values,
    }


def analysis_dict(a: SymbolAnalysis):
    return {
        "symbol": a.symbol,
        "trading_date": a.trading_date.isoformat(),
        "provisional": a.provisional,
        "indicators": a.indicators,
        "support": float(a.support) if a.support is not None else None,
        "support_touches": a.support_touches,
        "resistance": float(a.resistance) if a.resistance is not None else None,
        "resistance_touches": a.resistance_touches,
        "forecast": a.forecast,
        "trade_plan": a.trade_plan,
        "signals": [signal_dict(s) for s in a.signals.all()],
    }


def run_report(run_id):
    run = AnalysisRun.objects.get(pk=run_id)
    signals = list(Signal.objects.filter(run=run).order_by("-strength", "symbol"))
    symbols_with_signals = {s.symbol for s in signals}
    analyses = SymbolAnalysis.objects.filter(run=run, symbol__in=symbols_with_signals).prefetch_related("signals")
    return {
        "run_id": run.pk,
        "trading_date": run.trading_date.isoformat(),
        "provisional": run.provisional,
        "symbols_analyzed": run.symbols_analyzed,
        "signals": [signal_dict(s) for s in signals],
        "analyses": {a.symbol: analysis_dict(a) for a in analyses},
        # Every analysed symbol's levels, so watchlist stocks without signals get them too.
        "trade_plans": dict(SymbolAnalysis.objects.filter(run=run, trade_plan__isnull=False).values_list("symbol", "trade_plan")),
    }


def latest_for_symbol(symbol):
    a = SymbolAnalysis.objects.filter(symbol=symbol.upper()).prefetch_related("signals").order_by("-trading_date", "-created_at").first()
    return analysis_dict(a) if a else None


def latest_run():
    return AnalysisRun.objects.filter(status=AnalysisRun.Status.OK).order_by("-finished_at").first()


def latest_backtest():
    run = BacktestRun.objects.filter(status=BacktestRun.Status.OK).order_by("-finished_at").first()
    if run is None:
        return None
    return {
        "id": run.pk,
        "start_date": run.start_date.isoformat(),
        "end_date": run.end_date.isoformat(),
        "finished_at": run.finished_at.isoformat(),
        "horizons": run.horizons,
        "symbols_tested": run.symbols_tested,
        "signals_evaluated": run.signals_evaluated,
        "results": run.results,
        "baseline": run.baseline,
    }


def scorecard(days=180):
    """Live track record per strategy: predictions made in the last ``days`` and how the settled ones did."""
    since = timezone.localdate() - timedelta(days=days)
    rows = Prediction.objects.filter(made_on__gte=since).values("strategy", "direction", "outcome", "return_pct", "correct")
    return {"days": days, "since": since.isoformat(), "strategies": summarize(rows)}


# Shown first on the dashboard, and the pool the email's top picks come from: the NEPSE research strategies
# (the paper, the PCA study, then the two the NepseAlpha report ranks highest), then the rest.
FEATURED = ("quant_momentum", "quant_reversion", "pca_leaders", "nepsealpha_hybrid", "nepsealpha_seasonal")


def _evaluation_summary(m):
    if not m or not m.get("settled"):
        return None
    a, r, k, s = m["accuracy"], m["returns"], m["risk"], m["speed"]
    return {
        "settled": m["settled"],
        "hit_rate": a["hit_rate"],
        "hit_rate_ci95": a["hit_rate_ci95"],
        "chance_hit_rate": a["chance_hit_rate"],
        "p_value": a["p_value"],
        "avg_return_pct": r["avg_return_pct"],
        "random_avg_return_pct": r.get("random_avg_return_pct"),
        "profit_factor": r["profit_factor"],
        "sharpe": r["sharpe"],
        "max_drawdown_pct": k["max_drawdown_pct"],
        "mae_pct": m["forecast_error"]["mae_pct"],
        "ms_per_bar": s.get("analysis_ms_per_bar"),
        "sessions_to_resolve": s.get("avg_sessions_to_resolve"),
    }


def strategies_overview(days=180):
    """Every strategy with its switch, latest Quant evaluation, live track record and today's calls."""
    sync_settings()
    settings = {s.name: s for s in StrategySetting.objects.all()}
    latest = {}
    for ev in QuantEvaluation.objects.filter(status=QuantEvaluation.Status.OK).order_by("-finished_at"):
        latest.setdefault(ev.strategy, ev)
    live = {row["strategy"]: row for row in scorecard(days)["strategies"]}
    run = latest_run()
    todays = {}
    if run:
        for s in Signal.objects.filter(run=run).order_by("-strength", "symbol"):
            todays.setdefault(s.strategy, []).append(signal_dict(s))

    names = [*FEATURED, *(n for n in DESCRIPTIONS if n not in FEATURED)]
    rows = []
    for name in names:
        setting, ev = settings.get(name), latest.get(name)
        calls = todays.get(name, []) + (todays.get("transactions", []) if name == "volume" else [])
        rows.append({
            "name": name,
            "description": DESCRIPTIONS[name],
            "featured": name in FEATURED,
            "enabled": setting.enabled if setting else True,
            "admin_id": setting.pk if setting else None,
            "can_replay": can_replay(name),
            "evaluation": {
                "id": ev.pk,
                "start_date": ev.start_date.isoformat(),
                "end_date": ev.end_date.isoformat(),
                "finished_at": ev.finished_at.isoformat(),
                "symbols_tested": ev.symbols_tested,
                "replay": _evaluation_summary(ev.metrics),
                "live": _evaluation_summary(ev.live),
            } if ev else None,
            "live": live.get(name),
            "today": {"count": len(calls), "signals": calls[:5]},
        })
    return {
        "trading_date": run.trading_date.isoformat() if run else None,
        "provisional": run.provisional if run else None,
        "days": days,
        "strategies": rows,
    }
