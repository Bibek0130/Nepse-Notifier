from django.core.management.base import BaseCommand, CommandError

from modules.analysis.application import quant
from modules.analysis.domain.strategies import DESCRIPTIONS
from modules.analysis.infrastructure.models import AnalysisRun, BacktestRun, QuantEvaluation, Signal
from modules.marketdata import public as marketdata


class Command(BaseCommand):
    help = ("Check a seeded demo database shows something on every page: prices, signals, a backtest, and "
            "hit rate, p-value and profit factor for every strategy. Fails (exit 1) listing what is missing.")

    def handle(self, *args, **options):
        problems = []
        quotes = marketdata.get_latest_quotes() or []
        if not quotes:
            problems.append("no latest quotes")
        if not AnalysisRun.objects.filter(status=AnalysisRun.Status.OK, provisional=False).exists():
            problems.append("no finished end-of-day analysis")
        if not Signal.objects.exists():
            problems.append("no signals")
        if not BacktestRun.objects.filter(status=BacktestRun.Status.OK).exists():
            problems.append("no finished backtest")

        for strategy in DESCRIPTIONS:
            ev = QuantEvaluation.objects.filter(strategy=strategy).order_by("-started_at").first()
            if ev is None or ev.status != QuantEvaluation.Status.OK:
                problems.append(f"{strategy}: {'not evaluated' if ev is None else f'evaluation {ev.status}: {ev.error}'}")
                continue
            m = quant.headline(ev)
            if why := quant.missing_metrics(m):
                problems.append(f"{strategy}: {why}")
                continue
            a, r = m["accuracy"], m["returns"]
            self.stdout.write(f"{strategy:22} {m['settled']:>5} settled  hit {a['hit_rate']}%  p {a['p_value']}  PF {r['profit_factor']}")

        if problems:
            raise CommandError("Demo is incomplete:\n  " + "\n  ".join(problems))
        self.stdout.write(self.style.SUCCESS(f"Demo complete: {len(quotes)} stocks, {len(DESCRIPTIONS)} strategies measured."))
