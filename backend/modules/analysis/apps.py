from django.apps import AppConfig


class AnalysisConfig(AppConfig):
    """Indicators, strategies and signals. Built in step 2; for now it only subscribes to new candles."""

    name = "modules.analysis"
    label = "analysis"

    def ready(self):
        from modules.marketdata.public import CandlesIngested
        from modules.shared.events import subscribe

        subscribe(CandlesIngested, "modules.analysis.tasks.on_candles_ingested")
