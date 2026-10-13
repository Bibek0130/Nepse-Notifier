from django.core.management.base import BaseCommand

from modules.marketdata.application.backfill import backfill_history


class Command(BaseCommand):
    help = "Load daily price history. Run ingest_market first so the instrument list exists."

    def add_arguments(self, parser):
        parser.add_argument("symbols", nargs="*", help="Symbols to load (default: all active instruments).")
        parser.add_argument("--days", type=int, default=365)

    def handle(self, *args, symbols, days, **options):
        run = backfill_history([s.upper() for s in symbols] or None, days=days)
        self.stdout.write(f"Run #{run.pk}: {run.status}; {run.accepted} daily bars, {run.quarantined} quarantined.")
        if run.error:
            self.stderr.write(run.error)
