from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from modules.marketdata import public
from modules.marketdata.domain.entities import Candle, Timeframe
from modules.marketdata.infrastructure import repositories
from modules.marketdata.infrastructure.models import IngestionRun

NPT = ZoneInfo("Asia/Kathmandu")


def make(symbol, close, prev, ts, timeframe=Timeframe.INTRADAY_3H):
    c = Decimal(close)
    return Candle(symbol, timeframe, ts, ts.date(), c, c, c, c, 100, Decimal(prev), c * 100, 5)


class ApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        ts = datetime(2026, 10, 12, 14, 15, tzinfo=NPT)
        day = datetime(2026, 10, 12, tzinfo=NPT)
        repositories.upsert_candles([make("NABIL", "510", "500", ts), make("UPPER", "190", "200", ts)])
        repositories.upsert_candles([make("NABIL", "510", "500", day, Timeframe.DAILY)])

    def test_latest_quotes_falls_back_to_db_then_caches(self):
        data = self.client.get("/api/market/quotes/latest").json()
        self.assertEqual([r["symbol"] for r in data], ["NABIL", "UPPER"])
        self.assertEqual(data[0]["change_percent"], 2.0)
        self.assertIsNotNone(cache.get("marketdata:latest_quotes"))

    def test_summary(self):
        data = self.client.get("/api/market/summary").json()
        self.assertEqual((data["advancers"], data["decliners"]), (1, 1))
        self.assertEqual(data["top_gainers"][0]["symbol"], "NABIL")

    def test_candles(self):
        data = self.client.get("/api/market/candles", {"symbol": "nabil", "tf": "1D"}).json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["close"], "510.00")
        self.assertEqual(self.client.get("/api/market/candles").status_code, 400)

    def test_instruments(self):
        self.assertEqual([i["symbol"] for i in self.client.get("/api/market/instruments").json()], ["NABIL", "UPPER"])

    def test_runs_are_staff_only(self):
        IngestionRun.objects.create(kind="intraday")
        self.assertEqual(self.client.get("/api/market/runs").status_code, 403)
        self.client.force_authenticate(User.objects.create_user("admin", is_staff=True))
        self.assertEqual(self.client.get("/api/market/runs").json()["count"], 1)

    def test_public_interface_returns_domain_objects(self):
        candles = public.get_candles("NABIL", "1D")
        self.assertIsInstance(candles[0], Candle)
        self.assertEqual(public.list_symbols(), ["NABIL", "UPPER"])
