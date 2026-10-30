import importlib
import os
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

DEMO_MIDDLEWARE = [*settings.MIDDLEWARE, "modules.shared.demo.ReadOnlyDemoMiddleware"]


@override_settings(DEMO_MODE=True, MIDDLEWARE=DEMO_MIDDLEWARE, DEMO_VIEWER_USERNAME="demo", DEMO_VIEWER_PASSWORD="nepse-demo")
class ReadOnlyDemoTests(TestCase):
    def setUp(self):
        call_command("create_demo_viewer", stdout=open(os.devnull, "w"))

    def test_reading_works_and_changing_is_refused(self):
        self.assertEqual(self.client.get("/api/analysis/strategies").status_code, 200)
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)("/api/analysis/strategies")
                self.assertEqual(response.status_code, 403)
                self.assertIn(b"read-only demo", response.content)

    def test_viewer_can_log_in_and_look_but_not_change(self):
        response = self.client.post("/admin/login/", {"username": "demo", "password": "nepse-demo", "next": "/admin/"})
        self.assertRedirects(response, "/admin/")
        page = self.client.get("/admin/quant/quantstrategy/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Read-only demo")
        # Admin actions such as "Evaluate all strategies" and edits are POSTs: all refused.
        self.assertEqual(self.client.post("/admin/quant/quantstrategy/", {"action": "delete_selected"}).status_code, 403)
        self.assertEqual(self.client.post("/admin/auth/user/add/", {"username": "x"}).status_code, 403)
        user = get_user_model().objects.get(username="demo")
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.has_perm("analysis.view_signal"))
        self.assertFalse(any(p.startswith(("add_", "change_", "delete_")) for p in (q.split(".")[1] for q in user.get_all_permissions())))
        self.assertEqual(self.client.post("/admin/logout/").status_code, 200)

    def test_login_page_shows_the_view_only_login(self):
        self.assertContains(self.client.get("/admin/login/"), "nepse-demo")

    def test_running_the_command_again_resets_the_password(self):
        user = get_user_model().objects.get(username="demo")
        user.set_password("changed")
        user.save()
        call_command("create_demo_viewer", stdout=open(os.devnull, "w"))
        self.assertTrue(get_user_model().objects.get(username="demo").check_password("nepse-demo"))


class OutsideDemoTests(TestCase):
    @override_settings(MIDDLEWARE=DEMO_MIDDLEWARE)
    def test_middleware_does_nothing_without_demo_mode(self):
        response = self.client.post("/admin/login/", {"username": "nobody", "password": "x"})
        self.assertEqual(response.status_code, 200)  # the normal "wrong password" page, not a refusal
        self.assertNotEqual(self.client.post("/api/analysis/strategies").status_code, 403)
        self.assertNotContains(self.client.get("/admin/login/"), "Read-only demo")


class DemoSettingsTests(SimpleTestCase):
    def load(self, **env):
        with mock.patch.dict(os.environ, env):
            import config.settings.demo as demo

            return importlib.reload(demo)

    def test_never_emails_and_serves_the_dashboard(self):
        demo = self.load(RENDER_EXTERNAL_HOSTNAME="nepse-demo.onrender.com")
        self.assertEqual(demo.EMAIL_BACKEND, "django.core.mail.backends.locmem.EmailBackend")
        self.assertIn("nepse-demo.onrender.com", demo.ALLOWED_HOSTS)
        self.assertFalse(demo.DEBUG)
        self.assertEqual(demo.MIDDLEWARE[1], "whitenoise.middleware.WhiteNoiseMiddleware")
        self.assertEqual(demo.MIDDLEWARE[-1], "modules.shared.demo.ReadOnlyDemoMiddleware")
        self.assertTrue(demo.WHITENOISE_INDEX_FILE)

    def test_secret_key_comes_from_the_environment_when_set(self):
        self.assertEqual(self.load(DJANGO_SECRET_KEY="from-env").SECRET_KEY, "from-env")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DJANGO_SECRET_KEY", None)
            import config.settings.demo as demo

            self.assertGreaterEqual(len(importlib.reload(demo).SECRET_KEY), 40)
