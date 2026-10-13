from django.urls import path

from . import views

urlpatterns = [
    path("quotes/latest", views.LatestQuotesView.as_view(), name="market-latest-quotes"),
    path("summary", views.MarketSummaryView.as_view(), name="market-summary"),
    path("instruments", views.InstrumentListView.as_view(), name="market-instruments"),
    path("candles", views.CandleListView.as_view(), name="market-candles"),
    path("status", views.PipelineStatusView.as_view(), name="market-status"),
    path("runs", views.IngestionRunListView.as_view(), name="market-runs"),
]
