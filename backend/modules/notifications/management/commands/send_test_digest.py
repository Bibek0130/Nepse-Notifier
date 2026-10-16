from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from modules.analysis import public as analysis
from modules.marketdata import public as marketdata
from modules.notifications.domain.digest import Preferences, build_digest, subject_line
from modules.notifications.infrastructure import mailer
from modules.notifications.infrastructure.models import Subscriber


class Command(BaseCommand):
    help = "Email the digest for the latest analysis run to one address, to check email settings and layout."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--run", type=int, help="Analysis run id (default: latest finished run)")

    def handle(self, *args, email, run, **options):
        run = run or analysis.get_latest_run_id()
        if run is None:
            raise CommandError("No finished analysis run yet. Run ingest_market (and backfill_history) first.")
        report = analysis.get_run_report(run)
        content = build_digest(report, Preferences(), marketdata.get_market_summary(), quant_strategies=analysis.QUANT_STRATEGIES)
        recipient = Subscriber(email=email, unsubscribe_token="test")  # unsaved; only used to render the footer link
        text, html = mailer.render(content, recipient)
        message = EmailMultiAlternatives(subject_line(content), text, settings.DEFAULT_FROM_EMAIL, [email])
        message.attach_alternative(html, "text/html")
        message.send(fail_silently=False)
        self.stdout.write(f"Sent digest for analysis run {run} ({content.stock_count} top picks) to {email}.")
