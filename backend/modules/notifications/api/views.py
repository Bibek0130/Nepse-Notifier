from django.http import Http404
from django.shortcuts import render

from ..application import digests


def unsubscribe(request, token):
    """One-click unsubscribe from the link in every digest."""
    subscriber = digests.unsubscribe(token)
    if subscriber is None:
        raise Http404("Unknown unsubscribe link")
    return render(request, "notifications/unsubscribed.html", {"email": subscriber.email})
