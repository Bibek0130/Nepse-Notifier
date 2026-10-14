from dataclasses import asdict
from decimal import Decimal

from django.db import transaction

from .models import AnalysisRun, Signal, SymbolAnalysis


def _dec(level):
    return Decimal(str(level.price)) if level else None


@transaction.atomic
def save_analysis(run_id, analysis):
    """Store one symbol's result and its signals, replacing any earlier result in the same run."""
    SymbolAnalysis.objects.filter(run_id=run_id, symbol=analysis.symbol).delete()
    row = SymbolAnalysis.objects.create(
        run_id=run_id,
        symbol=analysis.symbol,
        trading_date=analysis.trading_date,
        provisional=analysis.provisional,
        indicators=analysis.indicators,
        support=_dec(analysis.support),
        support_touches=analysis.support.touches if analysis.support else None,
        resistance=_dec(analysis.resistance),
        resistance_touches=analysis.resistance.touches if analysis.resistance else None,
        forecast=asdict(analysis.forecast) if analysis.forecast else None,
        trade_plan=asdict(analysis.trade_plan) if analysis.trade_plan else None,
    )
    Signal.objects.bulk_create(
        Signal(
            run_id=run_id,
            analysis=row,
            symbol=analysis.symbol,
            trading_date=analysis.trading_date,
            strategy=s.strategy,
            direction=s.direction.value,
            strength=s.strength,
            message=s.message[:300],
            values=s.values,
        )
        for s in analysis.signals
    )
    return row


@transaction.atomic
def add_signals(run_id, found):
    """Attach extra (symbol, Signal) pairs to symbols already analysed in a run."""
    rows = {a.symbol: a for a in SymbolAnalysis.objects.filter(run_id=run_id, symbol__in={sym for sym, _ in found})}
    Signal.objects.bulk_create(
        Signal(
            run_id=run_id,
            analysis=rows[symbol],
            symbol=symbol,
            trading_date=rows[symbol].trading_date,
            strategy=s.strategy,
            direction=s.direction.value,
            strength=s.strength,
            message=s.message[:300],
            values=s.values,
        )
        for symbol, s in found
        if symbol in rows
    )
