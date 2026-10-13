import secrets

from django.db import models


def _token():
    return secrets.token_urlsafe(24)


class Subscriber(models.Model):
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    min_strength = models.PositiveSmallIntegerField(
        default=2, choices=[(1, "1 - everything"), (2, "2 - moderate and strong"), (3, "3 - strong only")]
    )
    watchlist = models.CharField(max_length=1000, blank=True, help_text="Comma-separated symbols. Leave blank for all stocks.")
    include_intraday = models.BooleanField(default=True, help_text="Also send the midday updates, not only the market-close digest")
    unsubscribe_token = models.CharField(max_length=64, unique=True, default=_token, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "notifications"
        ordering = ["email"]

    def __str__(self):
        return self.email

    @property
    def watchlist_symbols(self):
        return frozenset(s.strip().upper() for s in self.watchlist.split(",") if s.strip())


class Digest(models.Model):
    """One digest per analysis run; deliveries hold each subscriber's personalised copy."""

    analysis_run_id = models.IntegerField(unique=True)  # analysis module's run, not a foreign key
    trading_date = models.DateField()
    provisional = models.BooleanField(default=False)
    signals_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "notifications"
        ordering = ["-created_at"]

    def __str__(self):
        return f"digest {self.trading_date} ({'midday' if self.provisional else 'close'})"


class Delivery(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued"
        SENT = "sent"
        FAILED = "failed"

    digest = models.ForeignKey(Digest, on_delete=models.CASCADE, related_name="deliveries")
    subscriber = models.ForeignKey(Subscriber, on_delete=models.CASCADE, related_name="deliveries")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    subject = models.CharField(max_length=200)
    body_text = models.TextField()
    body_html = models.TextField()
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "notifications"
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["digest", "subscriber"], name="one_delivery_per_subscriber")]
