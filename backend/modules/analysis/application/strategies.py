"""Which strategies are switched on. Toggled in Django admin under Strategy settings."""
from ..domain.strategies import DESCRIPTIONS
from ..infrastructure.models import StrategySetting


def sync_settings():
    """Make sure every known strategy has an admin row (new strategies start switched on)."""
    StrategySetting.objects.bulk_create(
        [StrategySetting(name=name, description=text[:200]) for name, text in DESCRIPTIONS.items()], ignore_conflicts=True
    )


def enabled_names() -> set[str]:
    disabled = set(StrategySetting.objects.filter(enabled=False).values_list("name", flat=True))
    return set(DESCRIPTIONS) - disabled
