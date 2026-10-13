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
        parser.add_argument("--min-strength", type=int, default=1, choices=[1, 2, 3])

    def handle(self, *args, email, run, min_strength, **options):
        run = run or analysis.get_latest_run_id()
        if run is None:
            raise CommandError("No finished analysis run yet. Run ingest_market (and backfill_history) first.")
        content = build_digest(analysis.get_run_report(run), Preferences(min_strength=min_strength), marketdata.get_market_summary())
        if content.is_empty:
            raise CommandError(f"Analysis run {run} has no signals at strength {min_strength} or above.")
        recipient = Subscriber(email=email, unsubscribe_token="test")  # unsaved; only used to render the footer link
        text, html = mailer.render(content, recipient)
        message = EmailMultiAlternatives(subject_line(content), text, settings.DEFAULT_FROM_EMAIL, [email])
        message.attach_alternative(html, "text/html")
        message.send(fail_silently=False)
        self.stdout.write(f"Sent digest for analysis run {run} ({content.stock_count} stocks) to {email}.")
