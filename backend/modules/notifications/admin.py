from django.contrib import admin

from .infrastructure.models import Delivery, Digest, Subscriber


@admin.register(Subscriber)
class SubscriberAdmin(admin.ModelAdmin):
    list_display = ["email", "name", "is_active", "min_strength", "include_intraday", "watchlist", "created_at"]
    list_filter = ["is_active", "min_strength", "include_intraday"]
    search_fields = ["email", "name", "watchlist"]


class DeliveryInline(admin.TabularInline):
    model = Delivery
    extra = 0
    fields = ["subscriber", "status", "attempts", "sent_at", "error"]
    readonly_fields = fields


@admin.register(Digest)
class DigestAdmin(admin.ModelAdmin):
    list_display = ["trading_date", "provisional", "signals_count", "analysis_run_id", "created_at"]
    list_filter = ["provisional"]
    inlines = [DeliveryInline]


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = ["subscriber", "digest", "status", "attempts", "sent_at"]
    list_filter = ["status"]
    search_fields = ["subscriber__email"]
    readonly_fields = ["digest", "subscriber", "subject", "body_text", "attempts", "error", "sent_at"]
    exclude = ["body_html"]
