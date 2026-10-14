"""Use cases: start an analysis run, analyse one symbol, finish the run."""
import logging
from datetime import date

from django.db import transaction
from django.utils import timezone

from modules.shared import events

from ..domain.engine import analyze
from ..domain.strategies import selected
from ..events import SignalsGenerated
from ..infrastructure import repositories
from ..infrastructure.models import AnalysisRun, Signal, SymbolAnalysis
from . import predictions
from .cross_section import run_cross_sectional
from .series import load_series
from .strategies import enabled_names, sync_settings

logger = logging.getLogger(__name__)


def start_run(ingestion_run_id, timeframe, trading_date, symbols):
    sync_settings()
    return AnalysisRun.objects.create(
        ingestion_run_id=ingestion_run_id,
        timeframe=timeframe,
        trading_date=date.fromisoformat(trading_date),
        provisional=timeframe != "1D",
        symbols_total=len(symbols),
    )


def analyze_symbol(run_id, symbol):
    """Analyse one symbol for a run. Returns the number of signals, or None if history was too short."""
    run = AnalysisRun.objects.get(pk=run_id)
    series = load_series(symbol, run.trading_date, run.timeframe)
    result = analyze(series, strategies=selected(enabled_names()))
    if result is None:
        logger.info("Run %s: not enough history for %s (%d bars)", run_id, symbol, len(series))
        return None
    repositories.save_analysis(run_id, result)
    return len(result.signals)


def finish_run(run_id):
    try:
        run_cross_sectional(run_id, enabled_names())
    except Exception:
        logger.exception("Run %s: pairs / basket scan failed", run_id)  # per-symbol signals still go out
    run = AnalysisRun.objects.get(pk=run_id)
    if not run.provisional:
        try:
            predictions.record_predictions(run_id)
            predictions.settle_predictions()
        except Exception:
            logger.exception("Run %s: recording or settling predictions failed", run_id)
    run.symbols_analyzed = SymbolAnalysis.objects.filter(run=run).count()
    run.signals_count = Signal.objects.filter(run=run).count()
    run.status = AnalysisRun.Status.OK
    run.finished_at = timezone.now()
    with transaction.atomic():
        run.save()
        events.publish(
            SignalsGenerated(
                analysis_run_id=run.pk,
                trading_date=run.trading_date.isoformat(),
                provisional=run.provisional,
                signals_count=run.signals_count,
            )
        )
    return run
