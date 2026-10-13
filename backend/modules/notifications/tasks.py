"""Celery entry points: build the digest, then send each email on the notify queue."""
from smtplib import SMTPException

from celery import shared_task

from .application import digests


@shared_task
def on_signals_generated(analysis_run_id, trading_date, provisional, signals_count):
    """Subscriber for analysis's SignalsGenerated event."""
    if not signals_count:
        return 0
    delivery_ids = digests.prepare_digest(analysis_run_id)
    for delivery_id in delivery_ids:
        send_delivery.delay(delivery_id)
    return len(delivery_ids)


@shared_task(rate_limit="30/m", autoretry_for=(SMTPException, OSError), retry_backoff=60, retry_backoff_max=900, max_retries=5)
def send_delivery(delivery_id):
    return digests.send_delivery(delivery_id).status
