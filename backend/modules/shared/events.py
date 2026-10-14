"""In-process domain event bus that hands events to Celery after the DB commits.

Modules publish events with ``publish(SomeEvent(...))``. Other modules subscribe in
their ``AppConfig.ready()`` with ``subscribe(SomeEvent, "their.celery.task.name")``.
Subscribers are referenced by task *name*, so the publisher never imports the
subscriber: the dependency points only one way.
"""
import dataclasses
import importlib
import logging
from collections import defaultdict

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

_subscribers: dict[str, list[str]] = defaultdict(list)


class DomainEvent:
    """Base for events. Subclasses are frozen dataclasses with JSON-friendly fields."""

    @classmethod
    def event_name(cls):
        return f"{cls.__module__}.{cls.__qualname__}"

    def payload(self):
        return dataclasses.asdict(self)


def subscribe(event_cls, task_name):
    names = _subscribers[event_cls.event_name()]
    if task_name not in names:
        names.append(task_name)


def subscribers(event_cls):
    return list(_subscribers[event_cls.event_name()])


def publish(event):
    """Queue every subscriber task once the surrounding transaction commits.

    With ``EVENTS_RUN_INLINE`` (the local settings) subscribers run right here instead,
    so the whole pipeline works without a broker or worker.
    """

    def dispatch():
        from celery import current_app

        for task_name in _subscribers[event.event_name()]:
            logger.info("Dispatching %s to %s", event.event_name(), task_name)
            if getattr(settings, "EVENTS_RUN_INLINE", False):
                importlib.import_module(task_name.rsplit(".", 1)[0])  # registers the task, as a worker would
                current_app.tasks[task_name].apply(kwargs=event.payload(), throw=True)
            else:
                current_app.send_task(task_name, kwargs=event.payload())

    transaction.on_commit(dispatch)
