from dataclasses import dataclass
from datetime import date
from unittest import mock

from django.test import TestCase

from modules.shared import events
from modules.shared.calendar import is_trading_day, previous_trading_day
from modules.shared.locks import LockNotAcquired, single_flight
from modules.shared.models import TradingHoliday


class CalendarTests(TestCase):
    def test_weekdays(self):
        self.assertTrue(is_trading_day(date(2026, 10, 11)))  # Sunday
        self.assertTrue(is_trading_day(date(2026, 10, 15)))  # Thursday
        self.assertFalse(is_trading_day(date(2026, 10, 16)))  # Friday
        self.assertFalse(is_trading_day(date(2026, 10, 17)))  # Saturday

    def test_holiday(self):
        TradingHoliday.objects.create(date=date(2026, 10, 13), description="Holiday")
        self.assertFalse(is_trading_day(date(2026, 10, 13)))
        self.assertEqual(previous_trading_day(date(2026, 10, 14)), date(2026, 10, 12))

    def test_previous_trading_day_skips_weekend(self):
        self.assertEqual(previous_trading_day(date(2026, 10, 18)), date(2026, 10, 15))


class LockTests(TestCase):
    def test_second_holder_is_rejected(self):
        with single_flight("job", 60):
            with self.assertRaises(LockNotAcquired):
                with single_flight("job", 60):
                    pass
        with single_flight("job", 60):  # released after the block
            pass


@dataclass(frozen=True)
class SampleEvent(events.DomainEvent):
    run_id: int


class EventBusTests(TestCase):
    def test_publish_dispatches_after_commit(self):
        events.subscribe(SampleEvent, "some.task")
        with mock.patch("celery.current_app.send_task") as send_task:
            with self.captureOnCommitCallbacks(execute=True):
                events.publish(SampleEvent(run_id=7))
                send_task.assert_not_called()
        send_task.assert_called_once_with("some.task", kwargs={"run_id": 7})
