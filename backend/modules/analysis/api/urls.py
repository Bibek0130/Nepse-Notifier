from django.urls import path

from . import views

urlpatterns = [
    path("strategies", views.StrategiesView.as_view(), name="analysis-strategies"),
    path("signals", views.LatestSignalsView.as_view(), name="analysis-signals"),
    path("scorecard", views.ScorecardView.as_view(), name="analysis-scorecard"),
    path("backtest", views.BacktestView.as_view(), name="analysis-backtest"),
    path("symbols/<str:symbol>", views.SymbolAnalysisView.as_view(), name="analysis-symbol"),
]
