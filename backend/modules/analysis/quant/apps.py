from django.apps import AppConfig


class QuantConfig(AppConfig):
    """The admin "Quant" section. Part of the analysis module; its own app only so admin lists it separately."""

    name = "modules.analysis.quant"
    label = "quant"
    verbose_name = "Quant"
