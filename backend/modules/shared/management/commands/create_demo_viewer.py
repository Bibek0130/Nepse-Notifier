from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create (or reset) the demo's admin login, which can view every admin page but change nothing."

    def handle(self, *args, **options):
        username = getattr(settings, "DEMO_VIEWER_USERNAME", "demo")
        password = getattr(settings, "DEMO_VIEWER_PASSWORD", "nepse-demo")
        user, _ = get_user_model().objects.update_or_create(
            username=username, defaults={"is_staff": True, "is_superuser": False, "is_active": True}
        )
        user.set_password(password)
        user.save()
        user.user_permissions.set(Permission.objects.filter(codename__startswith="view_"))
        self.stdout.write(f"Demo admin login: {username} (view only, {user.user_permissions.count()} view permissions).")
