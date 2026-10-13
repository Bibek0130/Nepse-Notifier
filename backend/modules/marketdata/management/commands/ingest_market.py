from django.core.management.base import BaseCommand, CommandError

from modules.marketdata.application.ingest import ingest_market
from modules.marketdata.domain.ports import SourceError


class Command(BaseCommand):
    help = "Run the market data pipeline once, synchronously (no Celery needed)."

    def add_arguments(self, parser):
        parser.add_argument("--kind", choices=["intraday", "eod"], default="intraday")
        parser.add_argument("--force", action="store_true", help="Ignore the trading calendar and the unchanged-source check.")

    def handle(self, *args, kind, force, **options):
        try:
            run = ingest_market(kind, force=force)
        except SourceError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Run #{run.pk}: {run.status} from {run.source or '-'}; "
            f"fetched {run.fetched}, accepted {run.accepted}, quarantined {run.quarantined}."
        )
