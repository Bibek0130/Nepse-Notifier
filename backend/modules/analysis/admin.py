from django.contrib import admin

from .application.strategies import sync_settings
from .infrastructure.models import AnalysisRun, BacktestRun, Prediction, Signal, StrategySetting, SymbolAnalysis


@admin.register(AnalysisRun)
class AnalysisRunAdmin(admin.ModelAdmin):
    list_display = ["id", "trading_date", "timeframe", "provisional", "status", "symbols_total", "symbols_analyzed", "signals_count", "started_at"]
    list_filter = ["status", "timeframe", "provisional"]
    readonly_fields = [f.name for f in AnalysisRun._meta.fields]


@admin.register(Signal)
class SignalAdmin(admin.ModelAdmin):
    list_display = ["symbol", "trading_date", "strategy", "direction", "strength", "message"]
    list_filter = ["strategy", "direction", "strength", "trading_date"]
    search_fields = ["symbol"]


@admin.register(SymbolAnalysis)
class SymbolAnalysisAdmin(admin.ModelAdmin):
    list_display = ["symbol", "trading_date", "provisional", "support", "resistance", "run"]
    list_filter = ["provisional", "trading_date"]
    search_fields = ["symbol"]


@admin.register(BacktestRun)
class BacktestRunAdmin(admin.ModelAdmin):
    list_display = ["id", "start_date", "end_date", "status", "symbols_tested", "signals_evaluated", "finished_at"]
    list_filter = ["status"]
    readonly_fields = [f.name for f in BacktestRun._meta.fields]


@admin.register(StrategySetting)
class StrategySettingAdmin(admin.ModelAdmin):
    list_display = ["name", "enabled", "description"]
    list_editable = ["enabled"]
    readonly_fields = ["name", "description"]

    def get_queryset(self, request):
        sync_settings()  # list every strategy even before the first analysis run
        return super().get_queryset(request)

    def has_add_permission(self, request):
        return False  # rows are created for every known strategy automatically


@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = ["symbol", "made_on", "strategy", "direction", "entry_price", "target_price", "stop_price", "outcome", "return_pct", "correct"]
    list_filter = ["strategy", "direction", "outcome", "correct", "made_on"]
    search_fields = ["symbol"]
    readonly_fields = [f.name for f in Prediction._meta.fields]
