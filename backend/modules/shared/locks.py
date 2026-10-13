"""Distributed locks on the Django cache (Redis SET NX in production)."""
import uuid
from contextlib import contextmanager

from django.core.cache import cache


class LockNotAcquired(Exception):
    pass


@contextmanager
def single_flight(name, timeout):
    """Run the block only if no other worker holds ``name``; raise LockNotAcquired otherwise."""
    key = f"lock:{name}"
    token = uuid.uuid4().hex
    if not cache.add(key, token, timeout):
        raise LockNotAcquired(name)
    try:
        yield
    finally:
        if cache.get(key) == token:
            cache.delete(key)
