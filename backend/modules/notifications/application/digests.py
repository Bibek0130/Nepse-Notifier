"""Use cases: build a digest for an analysis run, and send one delivery."""
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from modules.analysis import public as analysis
from modules.marketdata import public as marketdata

from ..domain.digest import Preferences, build_digest, subject_line, wants_run
from ..infrastructure import mailer
from ..infrastructure.models import Delivery, Digest, Subscriber

logger = logging.getLogger(__name__)


def preferences_for(subscriber: Subscriber) -> Preferences:
    return Preferences(
        min_strength=subscriber.min_strength,
        watchlist=subscriber.watchlist_symbols,
        include_intraday=subscriber.include_intraday,
    )


def prepare_digest(analysis_run_id):
    """Create the digest and one queued delivery per interested subscriber.

    Idempotent: re-running for the same analysis run reuses the digest and skips
    subscribers who already have a delivery. Returns the ids of deliveries to send.
    """
    report = analysis.get_run_report(analysis_run_id)
    market = marketdata.get_market_summary()
    quotes = marketdata.get_latest_quotes()
    # The strategies' track record goes in the closing email only, not every midday update.
    scorecard = None if report["provisional"] else analysis.get_strategy_scorecard()
    digest, _ = Digest.objects.get_or_create(
        analysis_run_id=analysis_run_id,
        defaults={"trading_date": report["trading_date"], "provisional": report["provisional"], "signals_count": len(report["signals"])},
    )

    queued = []
    for subscriber in Subscriber.objects.filter(is_active=True):
        prefs = preferences_for(subscriber)
        if not wants_run(prefs, digest.provisional):
            continue
        content = build_digest(report, prefs, market, quotes, scorecard)
        if content.is_empty:
            continue
        text, html = mailer.render(content, subscriber)
        try:
            with transaction.atomic():
                delivery = Delivery.objects.create(
                    digest=digest, subscriber=subscriber, subject=subject_line(content)[:200], body_text=text, body_html=html
                )
        except IntegrityError:
            continue  # already prepared on an earlier attempt
        queued.append(delivery.pk)
    logger.info("Digest %s: %d deliveries queued", digest.pk, len(queued))
    return queued


def send_delivery(delivery_id):
    """Send one email. Safe to retry: an already-sent delivery is left alone."""
    delivery = Delivery.objects.select_related("subscriber").get(pk=delivery_id)
    if delivery.status == Delivery.Status.SENT or not delivery.subscriber.is_active:
        return delivery
    delivery.attempts += 1
    try:
        mailer.send(delivery)
    except Exception as exc:
        delivery.status = Delivery.Status.FAILED
        delivery.error = str(exc)
        delivery.save(update_fields=["status", "error", "attempts"])
        raise
    delivery.status = Delivery.Status.SENT
    delivery.sent_at = timezone.now()
    delivery.error = ""
    delivery.save(update_fields=["status", "sent_at", "error", "attempts"])
    return delivery


def unsubscribe(token):
    """Deactivate the subscriber with this token. Returns the subscriber or None."""
    subscriber = Subscriber.objects.filter(unsubscribe_token=token).first()
    if subscriber and subscriber.is_active:
        subscriber.is_active = False
        subscriber.save(update_fields=["is_active"])
    return subscriber


def subscriber_for_token(token):
    return Subscriber.objects.filter(unsubscribe_token=token).first()


def known_symbols():
    return set(marketdata.list_symbols())


def update_preferences(subscriber, *, watchlist, min_strength, include_intraday, is_active):
    """Save a subscriber's own settings from the link in their digest."""
    subscriber.watchlist = ", ".join(sorted(watchlist))
    subscriber.min_strength = min_strength
    subscriber.include_intraday = include_intraday
    subscriber.is_active = is_active
    subscriber.save(update_fields=["watchlist", "min_strength", "include_intraday", "is_active"])
    return subscriber
