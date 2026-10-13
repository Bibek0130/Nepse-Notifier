from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    """Subscribers, digests and email dispatch."""

    name = "modules.notifications"
    label = "notifications"

    def ready(self):
        from modules.analysis.public import SignalsGenerated
        from modules.shared.events import subscribe

        subscribe(SignalsGenerated, "modules.notifications.tasks.on_signals_generated")
