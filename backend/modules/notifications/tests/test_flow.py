from datetime import date, datetime, time, timedelta
from decimal import Decimal
from smtplib import SMTPException
from unittest import mock
from zoneinfo import ZoneInfo

from celery import current_app
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings

import modules.notifications.tasks  # noqa: F401  (registers the subscriber task, as a worker would)
from modules.analysis.tasks import on_candles_ingested
from modules.marketdata.domain.entities import Candle, Timeframe
from modules.marketdata.infrastructure import repositories as market_repo
from modules.notifications.application import digests
from modules.notifications.infrastructure.models import Delivery, Digest, Subscriber

NPT = ZoneInfo("Asia/Kathmandu")
TODAY = date(2026, 10, 12)


def seed(symbol, closes, volumes):
    start = TODAY - timedelta(days=len(closes) - 1)
    bars = []
    for i, (c, v) in enumerate(zip(closes, volumes)):
        d = start + timedelta(days=i)
        p = Decimal(str(c))
        bars.append(Candle(symbol, Timeframe.DAILY, datetime.combine(d, time.min, tzinfo=NPT), d, p, p + 1, p - 1, p, v, None, None, 20))
    market_repo.upsert_candles(bars)


def run_events_inline(name, kwargs):
    """Stand-in for send_task: run the subscriber task eagerly, as a worker would."""
    return current_app.tasks[name].apply(kwargs=kwargs)


@override_settings(SITE_URL="https://nepse.example.com")
class DigestFlowTests(TestCase):
    def setUp(self):
        cache.clear()  # the latest-quotes snapshot is cached; don't read one left by another test
        seed("SPIKE", [100] * 59 + [101], [1000] * 59 + [5000])  # volume spike (strength 2)
        seed("FLAT", [100] * 60, [1000] * 60)  # no signals
        closing = datetime.combine(TODAY, time(15), tzinfo=NPT)  # the snapshot the quotes cache serves
        market_repo.upsert_candles([
            Candle(s, Timeframe.INTRADAY_3H, closing, TODAY, p, p, p, p, 1000, None, None, 20) for s, p in (("SPIKE", Decimal("101")), ("FLAT", Decimal("100")))
        ])
        self.everyone = Subscriber.objects.create(email="all@example.com", min_strength=1)
        self.strong_only = Subscriber.objects.create(email="strong@example.com", min_strength=3)
        self.watchlist = Subscriber.objects.create(email="flat@example.com", min_strength=1, watchlist="flat")
        Subscriber.objects.create(email="gone@example.com", is_active=False)

    def run_pipeline(self, timeframe="1D"):
        with mock.patch("celery.current_app.send_task", side_effect=run_events_inline), self.captureOnCommitCallbacks(execute=True):
            on_candles_ingested.delay(1, timeframe, TODAY.isoformat(), ["FLAT", "SPIKE"])

    def test_candles_to_inbox(self):
        self.run_pipeline()

        # flat@ has no signals but watches FLAT, so gets its price at market close.
        self.assertEqual(sorted(m.to for m in mail.outbox), [["all@example.com"], ["flat@example.com"]])
        watch_only = next(m for m in mail.outbox if m.to == ["flat@example.com"])
        self.assertIn("YOUR WATCHLIST\nFLAT: 100", watch_only.body)
        self.assertNotIn("SPIKE", watch_only.body)
        self.assertIn("Buy zone", watch_only.body)  # watched stocks get trade levels even without signals
        message = next(m for m in mail.outbox if m.to == ["all@example.com"])
        self.assertTrue(message.subject.startswith("NEPSE Market close 2026-10-12"))
        self.assertIn("SPIKE", message.body)
        self.assertIn("Volume 5.0x the 20-day average", message.body)
        self.assertIn("LTP 101", message.body)
        self.assertIn("Stop loss", message.body)
        self.assertIn("https://nepse.example.com/notifications/unsubscribe/", message.body)
        html = message.alternatives[0].content
        self.assertIn("<strong>SPIKE</strong>", html)
        self.assertIn("Correction zone", html)
        self.assertIn("Risk : reward", html)
        self.assertEqual(message.extra_headers["List-Unsubscribe"], f"<https://nepse.example.com/notifications/unsubscribe/{self.everyone.unsubscribe_token}>")
        self.assertEqual(Delivery.objects.get(subscriber=self.everyone).status, "sent")

    def test_rerun_does_not_email_twice(self):
        self.run_pipeline()
        run_id = Digest.objects.get().analysis_run_id
        self.assertEqual(digests.prepare_digest(run_id), [])
        self.assertEqual(len(mail.outbox), 2)

    def test_intraday_opt_out(self):
        self.everyone.include_intraday = False
        self.everyone.save()
        p = Decimal("101")
        market_repo.upsert_candles([Candle("SPIKE", Timeframe.INTRADAY_3H, datetime(2026, 10, 13, 14, 15, tzinfo=NPT), date(2026, 10, 13), p, p, p, p, 6000, Decimal("100"))])
        with mock.patch("celery.current_app.send_task", side_effect=run_events_inline), self.captureOnCommitCallbacks(execute=True):
            on_candles_ingested.delay(2, "3H", "2026-10-13", ["SPIKE"])
        self.assertEqual(mail.outbox, [])

    def test_failed_send_is_recorded_and_retry_succeeds(self):
        with mock.patch("modules.notifications.infrastructure.mailer.send", side_effect=SMTPException("server busy")):
            with self.assertRaises(Exception):
                self.run_pipeline()
        delivery = Delivery.objects.get(subscriber=self.everyone)
        self.assertEqual((delivery.status, delivery.error), ("failed", "server busy"))
        self.assertGreaterEqual(delivery.attempts, 1)

        digests.send_delivery(delivery.pk)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, "sent")
        self.assertEqual([m.to for m in mail.outbox], [["all@example.com"]])

    def test_unsubscribe_link(self):
        response = self.client.get(f"/notifications/unsubscribe/{self.everyone.unsubscribe_token}")
        self.assertContains(response, "all@example.com will no longer receive")
        self.everyone.refresh_from_db()
        self.assertFalse(self.everyone.is_active)
        self.assertEqual(self.client.get("/notifications/unsubscribe/bogus").status_code, 404)
        self.run_pipeline()
        self.assertNotIn(["all@example.com"], [m.to for m in mail.outbox])

    def test_send_test_digest_command(self):
        self.run_pipeline()
        mail.outbox.clear()
        call_command("send_test_digest", "me@example.com", stdout=mock.MagicMock())
        self.assertEqual(mail.outbox[0].to, ["me@example.com"])
        self.assertIn("SPIKE", mail.outbox[0].body)
