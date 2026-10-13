from django.conf import settings

from .merolagani import MeroLaganiSource
from .sharesansar import ShareSansarSource

REGISTRY = {cls.name: cls for cls in (ShareSansarSource, MeroLaganiSource)}


def snapshot_sources():
    """Sources listed in settings.MARKETDATA["SOURCES"], in priority order."""
    names = settings.MARKETDATA["SOURCES"]
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        raise ValueError(f"Unknown market data source(s): {', '.join(unknown)}")
    return [REGISTRY[n]() for n in names]


def history_source():
    return REGISTRY[settings.MARKETDATA["HISTORY_SOURCE"]]()
