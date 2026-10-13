"""Per-source circuit breaker kept in Redis so all workers share it."""
from django.conf import settings
from django.core.cache import cache


def _keys(source):
    return f"circuit:{source}:failures", f"circuit:{source}:open"


def is_open(source):
    """True while the source is being skipped after repeated failures."""
    return cache.get(_keys(source)[1]) is not None


def record_success(source):
    cache.delete_many(_keys(source))


def record_failure(source):
    failures_key, open_key = _keys(source)
    cfg = settings.MARKETDATA
    cache.add(failures_key, 0, cfg["CIRCUIT_OPEN_SECONDS"])
    failures = cache.incr(failures_key)
    if failures >= cfg["CIRCUIT_FAILURE_THRESHOLD"]:
        cache.set(open_key, failures, cfg["CIRCUIT_OPEN_SECONDS"])
        cache.delete(failures_key)
    return failures
