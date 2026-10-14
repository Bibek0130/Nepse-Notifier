from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from modules.analysis.application.backtest import run_backtest


class Command(BaseCommand):
    help = "Replay every strategy over past prices and report how often its signals were right."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=365, help="How far back to replay (calendar days, default 365)")
        parser.add_argument("--end", type=date.fromisoformat, help="Last day to take signals from (default today)")
        parser.add_argument("--symbols", nargs="*", help="Only these symbols (default all listed)")
        parser.add_argument("--min-strength", type=int, default=1, choices=[1, 2, 3])

    def handle(self, *args, days, end, symbols, min_strength, **opts):
        end = end or timezone.localdate()
        run = run_backtest(end - timedelta(days=days), end, [s.upper() for s in symbols] if symbols else None)
        if run.status != run.Status.OK:
            self.stderr.write(f"Backtest failed: {run.error}")
            return
        self.stdout.write(f"Backtest #{run.pk}: {run.symbols_tested} symbols, {run.signals_evaluated} signals, {run.start_date} to {run.end_date}\n")
        header = f"{'strategy':<14}{'direction':<10}{'signals':>8}" + "".join(f"{f'{h}d hit':>9}{f'{h}d avg':>9}" for h in run.horizons)
        self.stdout.write(header)
        fmt_pct = lambda v: "-" if v is None else f"{v * 100:.0f}%"  # noqa: E731
        fmt_ret = lambda v: "-" if v is None else f"{v:+.2f}%"  # noqa: E731
        for row in run.results[str(min_strength)]:
            cells = "".join(f"{fmt_pct(h['hit_rate']):>9}{fmt_ret(h['avg_return']):>9}" for h in row["horizons"])
            self.stdout.write(f"{row['strategy']:<14}{row['direction']:<10}{row['signals']:>8}{cells}")
        base = "".join(f"{fmt_pct(h['hit_rate']):>9}{fmt_ret(h['avg_return']):>9}" for h in run.baseline)
        self.stdout.write(f"{'every day':<24}{'':>8}{base}   (hit = share of days the price rose)")
