"""Fast, self-contained test settings: no Postgres or Redis needed.

Set TEST_WITH_POSTGRES=1 to run the suite against the real Postgres from base settings.
"""
from .base import *  # noqa: F401,F403
from .base import BASE_DIR, env_bool

if not env_bool("TEST_WITH_POSTGRES"):
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "test.sqlite3"}}

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
