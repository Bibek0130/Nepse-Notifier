"""Run everything on one machine with nothing else installed: no Postgres, Redis or Celery worker.

    python manage.py migrate --settings=config.settings.local

Data goes in local.sqlite3, the cache in .cache/, and each step of the pipeline
(fetch, analyse, email) runs inline in the same process. Emails print to the
terminal unless EMAIL_HOST is set. Good for trying the project on a laptop; use
the dev or prod settings with Postgres and Redis for anything long-running.
"""
from .base import *  # noqa: F401,F403
from .base import BASE_DIR, env_bool

DEBUG = env_bool("DJANGO_DEBUG", True)

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "local.sqlite3"}}

# File-based so the dashboard's server and the ingest command see the same cache and locks.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.filebased.FileBasedCache", "LOCATION": BASE_DIR / ".cache"}}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"

# Run event subscribers in-process instead of queueing them for a worker.
EVENTS_RUN_INLINE = True
