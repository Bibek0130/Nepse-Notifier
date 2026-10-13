from django.db import models


class AnalysisRun(models.Model):
    """One analysis pass over the symbols from one ingestion run.

    ``ingestion_run_id`` is a plain integer, not a foreign key: modules never
    join across each other's tables.
    """

    class Status(models.TextChoices):
        RUNNING = "running"
        OK = "ok"
        FAILED = "failed"

    ingestion_run_id = models.IntegerField(db_index=True)
    timeframe = models.CharField(max_length=4)
    trading_date = models.DateField()
    provisional = models.BooleanField(default=False, help_text="Based on an intraday snapshot, not the closing price")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    symbols_total = models.IntegerField(default=0)
    symbols_analyzed = models.IntegerField(default=0)
    signals_count = models.IntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "analysis"
        ordering = ["-started_at"]

    def __str__(self):
        return f"analysis #{self.pk} {self.trading_date} {self.timeframe} {self.status}"


class SymbolAnalysis(models.Model):
    run = models.ForeignKey(AnalysisRun, on_delete=models.CASCADE, related_name="results")
    symbol = models.CharField(max_length=20)
    trading_date = models.DateField()
    provisional = models.BooleanField(default=False)
    indicators = models.JSONField(default=dict)
    support = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    support_touches = models.IntegerField(null=True, blank=True)
    resistance = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    resistance_touches = models.IntegerField(null=True, blank=True)
    forecast = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "analysis"
        ordering = ["symbol"]
        constraints = [models.UniqueConstraint(fields=["run", "symbol"], name="unique_symbol_per_analysis_run")]
        indexes = [models.Index(fields=["symbol", "-trading_date"])]


class Signal(models.Model):
    class Direction(models.TextChoices):
        BULLISH = "bullish"
        BEARISH = "bearish"
        NEUTRAL = "neutral"

    run = models.ForeignKey(AnalysisRun, on_delete=models.CASCADE, related_name="signals")
    analysis = models.ForeignKey(SymbolAnalysis, on_delete=models.CASCADE, related_name="signals")
    symbol = models.CharField(max_length=20)
    trading_date = models.DateField()
    strategy = models.CharField(max_length=30)
    direction = models.CharField(max_length=10, choices=Direction.choices)
    strength = models.PositiveSmallIntegerField()
    message = models.CharField(max_length=300)
    values = models.JSONField(default=dict)

    class Meta:
        app_label = "analysis"
        ordering = ["-strength", "symbol"]
        indexes = [models.Index(fields=["trading_date", "direction"]), models.Index(fields=["symbol", "-trading_date"])]
