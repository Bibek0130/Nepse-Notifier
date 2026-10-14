from django.urls import path

from . import views

urlpatterns = [
    path("signals", views.LatestSignalsView.as_view(), name="analysis-signals"),
    path("scorecard", views.ScorecardView.as_view(), name="analysis-scorecard"),
    path("backtest", views.BacktestView.as_view(), name="analysis-backtest"),
    path("symbols/<str:symbol>", views.SymbolAnalysisView.as_view(), name="analysis-symbol"),
]
