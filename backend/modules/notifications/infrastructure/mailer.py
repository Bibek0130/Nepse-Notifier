"""Render and send digest emails with Django's email backend (SMTP in production)."""
import re

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse


def unsubscribe_url(subscriber):
    path = reverse("notifications-unsubscribe", args=[subscriber.unsubscribe_token])
    return settings.SITE_URL.rstrip("/") + path


def render(content, subscriber):
    context = {"digest": content, "subscriber": subscriber, "unsubscribe_url": unsubscribe_url(subscriber), "site_url": settings.SITE_URL}
    text = re.sub(r"\n{3,}", "\n\n", render_to_string("notifications/digest.txt", context)).strip() + "\n"
    return text, render_to_string("notifications/digest.html", context)


def send(delivery):
    message = EmailMultiAlternatives(
        subject=delivery.subject,
        body=delivery.body_text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[delivery.subscriber.email],
        headers={"List-Unsubscribe": f"<{unsubscribe_url(delivery.subscriber)}>"},
    )
    message.attach_alternative(delivery.body_html, "text/html")
    message.send(fail_silently=False)
