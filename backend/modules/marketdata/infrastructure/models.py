from django.db import models


class Instrument(models.Model):
    symbol = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=255, blank=True)
    sector = models.CharField(max_length=100, blank=True)
    instrument_type = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "marketdata"
        ordering = ["symbol"]

    def __str__(self):
        return self.symbol


class IngestionRun(models.Model):
    """One pipeline run, with the outcome of each stage in ``stages``."""

    class Kind(models.TextChoices):
        INTRADAY = "intraday"
        END_OF_DAY = "eod"
        BACKFILL = "backfill"

    class Status(models.TextChoices):
        RUNNING = "running"
        OK = "ok"
        PARTIAL = "partial"  # finished, but some candles were quarantined or symbols failed
        STALE = "stale"  # source hadn't changed since the last fetch
        SKIPPED = "skipped"  # market closed or another run in progress
        FAILED = "failed"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    source = models.CharField(max_length=30, blank=True)
    trading_date = models.DateField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    stages = models.JSONField(default=dict, blank=True)
    fetched = models.IntegerField(default=0)
    accepted = models.IntegerField(default=0)
    quarantined = models.IntegerField(default=0)
    error = models.TextField(blank=True)

    class Meta:
        app_label = "marketdata"
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.kind} #{self.pk} {self.status}"


class RawPayload(models.Model):
    """Untouched source response, kept for audit and re-parsing."""

    run = models.ForeignKey(IngestionRun, on_delete=models.SET_NULL, null=True, related_name="raw_payloads")
    source = models.CharField(max_length=30)
    url = models.URLField(max_length=500)
    fetched_at = models.DateTimeField()
    content_type = models.CharField(max_length=100, blank=True)
    content_hash = models.CharField(max_length=64, db_index=True)
    body_gzip = models.BinaryField()

    class Meta:
        app_label = "marketdata"
        ordering = ["-fetched_at"]
        indexes = [models.Index(fields=["source", "-fetched_at"])]


class Candle(models.Model):
    class Timeframe(models.TextChoices):
        INTRADAY_3H = "3H"
        DAILY = "1D"

    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="candles")
    timeframe = models.CharField(max_length=4, choices=Timeframe.choices)
    ts = models.DateTimeField()
    trading_date = models.DateField()
    open = models.DecimalField(max_digits=12, decimal_places=2)
    high = models.DecimalField(max_digits=12, decimal_places=2)
    low = models.DecimalField(max_digits=12, decimal_places=2)
    close = models.DecimalField(max_digits=12, decimal_places=2)
    previous_close = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    volume = models.BigIntegerField(default=0)
    turnover = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    trades = models.IntegerField(null=True, blank=True)
    source = models.CharField(max_length=30, blank=True)
    run = models.ForeignKey(IngestionRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="candles")

    class Meta:
        app_label = "marketdata"
        ordering = ["instrument", "timeframe", "ts"]
        constraints = [models.UniqueConstraint(fields=["instrument", "timeframe", "ts"], name="unique_candle")]
        indexes = [
            models.Index(fields=["timeframe", "ts"]),
            models.Index(fields=["timeframe", "trading_date"]),
        ]

    def __str__(self):
        return f"{self.instrument} {self.timeframe} {self.ts:%Y-%m-%d %H:%M} {self.close}"


class CandleIssue(models.Model):
    """A candle that failed (reject) or tripped (flag) a validation rule."""

    run = models.ForeignKey(IngestionRun, on_delete=models.CASCADE, related_name="issues")
    symbol = models.CharField(max_length=20)
    timeframe = models.CharField(max_length=4)
    rule = models.CharField(max_length=50)
    severity = models.CharField(max_length=10)
    message = models.TextField()
    values = models.JSONField(default=dict)
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "marketdata"
        ordering = ["-created_at"]


class CorporateAction(models.Model):
    class Type(models.TextChoices):
        BONUS = "bonus"
        RIGHTS = "rights"
        SPLIT = "split"
        CASH_DIVIDEND = "cash_dividend"

    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="corporate_actions")
    action_type = models.CharField(max_length=20, choices=Type.choices)
    ratio = models.DecimalField(max_digits=10, decimal_places=4, help_text="e.g. 0.10 for a 10% bonus")
    book_close_date = models.DateField()
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        app_label = "marketdata"
        ordering = ["-book_close_date"]
