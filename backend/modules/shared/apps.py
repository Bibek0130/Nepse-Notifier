from django.apps import AppConfig


class SharedConfig(AppConfig):
    """Shared kernel: market calendar, event bus and locking used by every module."""

    name = "modules.shared"
    label = "shared"
