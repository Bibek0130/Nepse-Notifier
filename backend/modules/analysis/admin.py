from django.contrib import admin

from .infrastructure.models import AnalysisRun, Signal, SymbolAnalysis


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
