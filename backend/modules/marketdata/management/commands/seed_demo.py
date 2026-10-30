import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from modules.marketdata.application.demo import seed_demo
from modules.marketdata.infrastructure.models import IngestionRun

DEFAULT_UNIVERSE = Path(settings.BASE_DIR) / "demo" / "universe.csv"


class Command(BaseCommand):
    help = ("Fill the database with real NEPSE history from the public nepse-data archive, for the hosted demo, "
            "then analyse the latest sessions. Run evaluate_strategies and backtest afterwards.")

    def add_arguments(self, parser):
        parser.add_argument("--universe", default=str(DEFAULT_UNIVERSE), help="CSV of symbol,sector (default demo/universe.csv)")
        parser.add_argument("--days", type=int, default=730, help="Calendar days of history to load (default 730)")
        parser.add_argument("--replay-sessions", type=int, default=20,
                            help="Latest sessions to analyse one by one, so predictions have a track record (default 20)")
        parser.add_argument("--limit", type=int, help="Only the first N stocks of the universe (quick tries)")

    def handle(self, *args, universe, days, replay_sessions, limit, **options):
        sectors = read_universe(universe)
        if limit:
            sectors = dict(list(sectors.items())[:limit])
        run, replayed = seed_demo(sectors, days=days, replay_sessions=replay_sessions, progress=self.stdout.write)
        self.stdout.write(f"Backfill #{run.pk}: {run.status}; {run.accepted} daily bars, {run.quarantined} quarantined.")
        if run.error:
            self.stderr.write(run.error)
        if run.status == IngestionRun.Status.FAILED:
            raise CommandError("No history could be loaded.")
        if replayed:
            self.stdout.write(f"Analysed {len(replayed)} sessions, {replayed[0]} to {replayed[-1]}.")


def read_universe(path):
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = [r for r in csv.reader(f) if r and r[0].strip() and not r[0].startswith("#")]
    except OSError as exc:
        raise CommandError(str(exc)) from exc
    if rows and rows[0][0].strip().lower() == "symbol":
        rows = rows[1:]
    sectors = {r[0].strip().upper(): (r[1].strip() if len(r) > 1 else "")[:100] for r in rows}
    if not sectors:
        raise CommandError(f"No symbols in {path}")
    return sectors
