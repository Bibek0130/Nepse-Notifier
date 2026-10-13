"""NEPSE trading calendar."""
from datetime import date, time, timedelta

from django.utils import timezone

from .models import TradingHoliday

# Python weekday(): Monday=0 ... Sunday=6. NEPSE trades Sunday to Thursday.
TRADING_WEEKDAYS = {6, 0, 1, 2, 3}
MARKET_OPEN = time(11, 0)
MARKET_CLOSE = time(15, 0)


def is_trading_day(day: date) -> bool:
    return day.weekday() in TRADING_WEEKDAYS and not TradingHoliday.objects.filter(date=day).exists()


def today() -> date:
    return timezone.localdate()


def previous_trading_day(day: date) -> date:
    candidate = day - timedelta(days=1)
    while not is_trading_day(candidate):
        candidate -= timedelta(days=1)
    return candidate
