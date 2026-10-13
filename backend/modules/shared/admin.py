from django.contrib import admin

from .models import TradingHoliday


@admin.register(TradingHoliday)
class TradingHolidayAdmin(admin.ModelAdmin):
    list_display = ["date", "description"]
    date_hierarchy = "date"
