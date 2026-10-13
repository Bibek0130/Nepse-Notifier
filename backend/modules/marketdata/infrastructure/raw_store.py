import gzip
import hashlib
from datetime import timedelta

from django.utils import timezone

from .models import RawPayload


def content_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def latest_hash(source: str):
    return RawPayload.objects.filter(source=source).values_list("content_hash", flat=True).first()


def save(raw, run, fetched_at):
    return RawPayload.objects.create(
        run=run,
        source=raw.source,
        url=raw.url,
        fetched_at=fetched_at,
        content_type=raw.content_type[:100],
        content_hash=content_hash(raw.body),
        body_gzip=gzip.compress(raw.body.encode("utf-8")),
    )


def read_body(payload: RawPayload) -> str:
    return gzip.decompress(bytes(payload.body_gzip)).decode("utf-8")


def purge_older_than(days: int) -> int:
    deleted, _ = RawPayload.objects.filter(fetched_at__lt=timezone.now() - timedelta(days=days)).delete()
    return deleted
