from django.core.management.base import BaseCommand

from modules.marketdata.application.backfill import DEFAULT_DAYS, backfill_history, history_is_short, history_status


class Command(BaseCommand):
    help = "Load daily price history. Run ingest_market first so the instrument list exists."

    def add_arguments(self, parser):
        parser.add_argument("symbols", nargs="*", help="Symbols to load (default: all active instruments).")
        parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
        parser.add_argument("--if-shorter-than", type=int, metavar="SESSIONS",
                            help="Only download when no stock has this many sessions saved and the saved history "
                                 "doesn't reach back --days yet.")

    def handle(self, *args, symbols, days, if_shorter_than, **options):
        if if_shorter_than:
            longest, oldest, _ = history_status(days)
            if not history_is_short(if_shorter_than, days):
                self.stdout.write(f"History is long enough: up to {longest} sessions per stock, back to {oldest}.")
                return
            self.stdout.write(f"Only {longest} sessions saved per stock (need {if_shorter_than}); downloading {days} days of history. This takes a while.")
        run = backfill_history([s.upper() for s in symbols] or None, days=days)
        self.stdout.write(f"Run #{run.pk}: {run.status}; {run.accepted} daily bars, {run.quarantined} quarantined.")
        if run.error:
            self.stderr.write(run.error)
