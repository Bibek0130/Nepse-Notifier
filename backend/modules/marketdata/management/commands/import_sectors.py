import csv

from django.core.management.base import BaseCommand, CommandError

from modules.marketdata.infrastructure.models import Instrument


class Command(BaseCommand):
    help = "Set instrument sectors from a CSV with symbol and sector columns (e.g. NABIL,Commercial Banks)."

    def add_arguments(self, parser):
        parser.add_argument("path")

    def handle(self, *args, path, **options):
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                rows = [r for r in csv.reader(f) if len(r) >= 2 and r[0].strip()]
        except OSError as exc:
            raise CommandError(str(exc)) from exc
        if rows and rows[0][0].strip().lower() == "symbol":
            rows = rows[1:]
        sectors = {r[0].strip().upper(): r[1].strip() for r in rows}
        instruments = list(Instrument.objects.filter(symbol__in=sectors))
        for instrument in instruments:
            instrument.sector = sectors[instrument.symbol][:100]
        Instrument.objects.bulk_update(instruments, ["sector"])
        unknown = sorted(set(sectors) - {i.symbol for i in instruments})
        self.stdout.write(f"Set the sector of {len(instruments)} stocks.")
        if unknown:
            self.stdout.write(f"{len(unknown)} symbols are not in the database yet: {', '.join(unknown[:20])}")
