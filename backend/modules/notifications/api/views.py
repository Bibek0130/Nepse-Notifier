from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from ..application import digests
from .forms import PreferencesForm


def unsubscribe(request, token):
    """One-click unsubscribe from the link in every digest."""
    subscriber = digests.unsubscribe(token)
    if subscriber is None:
        raise Http404("Unknown unsubscribe link")
    return render(request, "notifications/unsubscribed.html", {"email": subscriber.email, "token": token})


@require_http_methods(["GET", "POST"])
def preferences(request, token):
    """Let a subscriber edit their own watchlist and alert settings, using the link in their digest."""
    subscriber = digests.subscriber_for_token(token)
    if subscriber is None:
        raise Http404("Unknown link")
    known = digests.known_symbols()
    saved = False
    if request.method == "POST":
        form = PreferencesForm(request.POST, known_symbols=known)
        if form.is_valid():
            digests.update_preferences(subscriber, **form.cleaned_data)
            saved = True
            form = PreferencesForm(initial=_initial(subscriber), known_symbols=known)
    else:
        form = PreferencesForm(initial=_initial(subscriber), known_symbols=known)
    return render(request, "notifications/preferences.html", {"form": form, "email": subscriber.email, "saved": saved})


def _initial(subscriber):
    return {
        "watchlist": ", ".join(sorted(subscriber.watchlist_symbols)),
        "include_intraday": subscriber.include_intraday,
        "is_active": subscriber.is_active,
    }
