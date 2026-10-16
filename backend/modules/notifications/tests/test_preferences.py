from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase, override_settings

from modules.marketdata.domain.entities import Candle, Timeframe
from modules.marketdata.infrastructure import repositories as market_repo
from modules.notifications.domain.digest import DigestContent, WatchItem
from modules.notifications.infrastructure import mailer
from modules.notifications.infrastructure.models import Subscriber

NPT = ZoneInfo("Asia/Kathmandu")


def listed(*symbols):
    d = date(2026, 10, 12)
    p = Decimal("100")
    market_repo.upsert_candles([
        Candle(s, Timeframe.DAILY, datetime.combine(d, time(15), tzinfo=NPT), d, p, p, p, p, 10, None, None, 1) for s in symbols
    ])


@override_settings(SITE_URL="https://nepse.example.com")
class PreferencesPageTests(TestCase):
    def setUp(self):
        listed("NABIL", "NICA", "UPPER")
        self.sub = Subscriber.objects.create(email="me@example.com", watchlist="NABIL")
        self.url = f"/notifications/preferences/{self.sub.unsubscribe_token}"

    def post(self, **overrides):
        data = {"watchlist": "nica upper", "include_intraday": "", "is_active": "on", **overrides}
        return self.client.post(self.url, data)

    def test_shows_current_settings(self):
        page = self.client.get(self.url)
        self.assertContains(page, "me@example.com")
        self.assertContains(page, "NABIL")
        self.assertContains(page, "busy-spinner")  # Save is disabled with a spinner while it sends

    def test_saves_settings(self):
        page = self.post()
        self.assertContains(page, "Saved.")
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.watchlist_symbols, {"NICA", "UPPER"})
        self.assertEqual((self.sub.include_intraday, self.sub.is_active), (False, True))

    def test_rejects_unknown_symbols(self):
        page = self.post(watchlist="NICA, NOTREAL")
        self.assertContains(page, "Not a listed stock: NOTREAL")
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.watchlist, "NABIL")

    def test_resubscribe_after_unsubscribing(self):
        unsubscribed = self.client.get(f"/notifications/unsubscribe/{self.sub.unsubscribe_token}")
        self.assertContains(unsubscribed, self.url)
        self.post(watchlist="")
        self.sub.refresh_from_db()
        self.assertTrue(self.sub.is_active)
        self.assertEqual(self.sub.watchlist, "")

    def test_unknown_token(self):
        self.assertEqual(self.client.get("/notifications/preferences/nope").status_code, 404)

    def test_email_links_to_settings_and_lists_watchlist(self):
        content = DigestContent(trading_date="2026-10-12", provisional=False, watchlist=[WatchItem("NICA", 400.0, 1.5, is_pick=True)])
        text, html = mailer.render(content, self.sub)
        self.assertIn("YOUR WATCHLIST\nNICA: 400.0 (+1.5%), a top pick above", text)
        self.assertIn(f"https://nepse.example.com{self.url}", text)
        self.assertIn("Your watchlist", html)
        self.assertIn(f"https://nepse.example.com{self.url}", html)
