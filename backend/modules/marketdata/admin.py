from django.contrib import admin

from .infrastructure.models import Candle, CandleIssue, CorporateAction, IngestionRun, Instrument, RawPayload


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    list_display = ["symbol", "name", "sector", "instrument_type", "is_active"]
    list_filter = ["is_active", "sector", "instrument_type"]
    search_fields = ["symbol", "name"]


@admin.register(Candle)
class CandleAdmin(admin.ModelAdmin):
    list_display = ["instrument", "timeframe", "ts", "open", "high", "low", "close", "volume", "trades", "source"]
    list_filter = ["timeframe", "source", "trading_date"]
    search_fields = ["instrument__symbol"]
    date_hierarchy = "trading_date"
    raw_id_fields = ["instrument", "run"]


class CandleIssueInline(admin.TabularInline):
    model = CandleIssue
    extra = 0
    fields = ["symbol", "timeframe", "rule", "severity", "message", "resolved"]
    readonly_fields = ["symbol", "timeframe", "rule", "severity", "message"]


@admin.register(IngestionRun)
class IngestionRunAdmin(admin.ModelAdmin):
    list_display = ["id", "kind", "status", "source", "trading_date", "started_at", "fetched", "accepted", "quarantined"]
    list_filter = ["kind", "status", "source"]
    readonly_fields = [f.name for f in IngestionRun._meta.fields]
    inlines = [CandleIssueInline]


@admin.register(CandleIssue)
class CandleIssueAdmin(admin.ModelAdmin):
    list_display = ["symbol", "timeframe", "rule", "severity", "message", "run", "resolved"]
    list_filter = ["rule", "severity", "resolved"]
    search_fields = ["symbol"]
    list_editable = ["resolved"]


@admin.register(RawPayload)
class RawPayloadAdmin(admin.ModelAdmin):
    list_display = ["source", "fetched_at", "content_hash", "run"]
    list_filter = ["source"]
    exclude = ["body_gzip"]


@admin.register(CorporateAction)
class CorporateActionAdmin(admin.ModelAdmin):
    list_display = ["instrument", "action_type", "ratio", "book_close_date"]
    list_filter = ["action_type"]
    search_fields = ["instrument__symbol"]
    raw_id_fields = ["instrument"]
