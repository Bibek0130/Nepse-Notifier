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
    trade_plan = models.JSONField(null=True, blank=True, help_text="Buy/sell/correction zones, stop, target and risk-to-reward")
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


class BacktestRun(models.Model):
    """One replay of every strategy over past prices, with per-strategy results.

    ``results`` maps a minimum strength ("1", "2", "3") to a list of
    {strategy, direction, signals, horizons: [{horizon, samples, avg_return, hit_rate}]}.
    ``baseline`` is the same horizon list over every day evaluated, signal or not.
    """

    class Status(models.TextChoices):
        RUNNING = "running"
        OK = "ok"
        FAILED = "failed"

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    start_date = models.DateField()
    end_date = models.DateField()
    horizons = models.JSONField(default=list)
    symbols_tested = models.IntegerField(default=0)
    signals_evaluated = models.IntegerField(default=0)
    results = models.JSONField(default=dict)
    baseline = models.JSONField(default=list)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "analysis"
        ordering = ["-started_at"]

    def __str__(self):
        return f"backtest #{self.pk} {self.start_date}..{self.end_date} {self.status}"


class StrategySetting(models.Model):
    """Switch a strategy on or off. Strategies without a row are on."""

    name = models.CharField(max_length=30, unique=True)
    enabled = models.BooleanField(default=True)
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        app_label = "analysis"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({'on' if self.enabled else 'off'})"


class Prediction(models.Model):
    """A signal's claim about where the price goes next, kept so it can be scored later.

    Open until the target or stop is touched or ``horizon`` sessions pass; then the
    outcome fields are filled in from the actual closing prices.
    """

    class Outcome(models.TextChoices):
        TARGET = "target", "Target reached"
        STOP = "stop", "Stop hit"
        HORIZON = "horizon", "Settled at horizon"

    run = models.ForeignKey(AnalysisRun, on_delete=models.CASCADE, related_name="predictions")
    signal = models.OneToOneField(Signal, on_delete=models.SET_NULL, null=True, blank=True, related_name="prediction")
    symbol = models.CharField(max_length=20)
    strategy = models.CharField(max_length=30)
    direction = models.CharField(max_length=10, choices=Signal.Direction.choices)
    strength = models.PositiveSmallIntegerField()
    made_on = models.DateField()
    entry_price = models.DecimalField(max_digits=12, decimal_places=2)
    target_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    stop_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    horizon = models.PositiveSmallIntegerField(help_text="Sessions to wait before settling on the close")
    outcome = models.CharField(max_length=10, choices=Outcome.choices, blank=True)
    exit_date = models.DateField(null=True, blank=True)
    exit_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    sessions = models.PositiveSmallIntegerField(null=True, blank=True)
    return_pct = models.FloatField(null=True, blank=True)
    correct = models.BooleanField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "analysis"
        ordering = ["-made_on", "symbol"]
        constraints = [
            models.UniqueConstraint(fields=["symbol", "strategy", "direction", "made_on"], name="unique_prediction_per_day"),
        ]
        indexes = [models.Index(fields=["outcome", "made_on"]), models.Index(fields=["strategy", "made_on"])]

    def __str__(self):
        return f"{self.symbol} {self.strategy} {self.direction} {self.made_on}"
