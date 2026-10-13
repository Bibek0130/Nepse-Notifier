"""Celery entry points. Kept thin: each one calls a use case."""
from celery import shared_task
from django.conf import settings

from .application.backfill import backfill_history as backfill_use_case
from .application.ingest import ingest_market as ingest_use_case
from .domain.ports import SourceError
from .infrastructure import raw_store


@shared_task(bind=True, autoretry_for=(SourceError,), retry_backoff=60, retry_backoff_max=600, max_retries=3)
def ingest_market(self, kind="intraday", force=False):
    return ingest_use_case(kind, force=force).pk


@shared_task
def backfill_history(symbols=None, days=365):
    return backfill_use_case(symbols, days=days).pk


@shared_task
def purge_raw_payloads():
    return raw_store.purge_older_than(settings.MARKETDATA["RAW_RETENTION_DAYS"])
