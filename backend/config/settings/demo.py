"""Hosted, read-only demo: one container, no Postgres, Redis or Celery worker.

The database is a SQLite file filled at image build time (manage.py seed_demo) with real
NEPSE history, so the demo needs nothing else running and starts in seconds. Every
request that would change something is refused (modules.shared.demo), emails are never
sent, and the built React dashboard is served by Django itself at /.
"""
import os

from django.core.management.utils import get_random_secret_key

from .base import *  # noqa: F401,F403
from .base import BASE_DIR, MIDDLEWARE, env, env_bool

DEMO_MODE = True
DEBUG = False
# Without DJANGO_SECRET_KEY each start gets a fresh key: logins then end on a restart, which a demo can live with.
SECRET_KEY = env("DJANGO_SECRET_KEY") or get_random_secret_key()

# Render sets RENDER_EXTERNAL_HOSTNAME; other hosts pass DJANGO_ALLOWED_HOSTS.
ALLOWED_HOSTS = [h for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(os.environ["RENDER_EXTERNAL_HOSTNAME"])

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": env("DEMO_DB_PATH", str(BASE_DIR / "demo.sqlite3"))}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# Seeding runs the whole pipeline in-process; at runtime nothing is queued at all.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
EVENTS_RUN_INLINE = True

# Never email anyone from the demo, whatever is configured.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Behind the host's HTTPS proxy.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", True)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE

# Django serves the built dashboard (frontend/dist, copied to WHITENOISE_ROOT) and the admin's static files.
MIDDLEWARE = [
    MIDDLEWARE[0],
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[1:],
    "modules.shared.demo.ReadOnlyDemoMiddleware",
]
WHITENOISE_ROOT = env("DEMO_FRONTEND_DIR", str(BASE_DIR / "frontend_dist"))
WHITENOISE_INDEX_FILE = True

# A view-only admin login, shown on the login page so anyone given the link can look around the admin.
DEMO_VIEWER_USERNAME = env("DEMO_VIEWER_USERNAME", "demo")
DEMO_VIEWER_PASSWORD = env("DEMO_VIEWER_PASSWORD", "nepse-demo")
