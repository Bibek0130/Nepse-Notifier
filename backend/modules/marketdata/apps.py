from django.apps import AppConfig


class MarketdataConfig(AppConfig):
    """Instruments, quotes and candles: fetching, validating, storing and serving market data."""

    name = "modules.marketdata"
    label = "marketdata"
