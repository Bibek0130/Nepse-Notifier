from ..infrastructure.models import AnalysisRun, BacktestRun, Signal, SymbolAnalysis


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
