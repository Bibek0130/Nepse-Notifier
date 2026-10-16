"""Run everything on one machine with nothing else installed: no Postgres, Redis or Celery worker.

    python manage.py migrate --settings=config.settings.local

Data goes in local.sqlite3, the cache in .cache/, and each step of the pipeline
(fetch, analyse, email) runs inline in the same process. Emails print to the
terminal unless EMAIL_HOST is set, here or in backend/.env (run-local.ps1
-SetupEmail writes it for Gmail). Good for trying the project on a laptop; use
the dev or prod settings with Postgres and Redis for anything long-running.
"""
import os
from pathlib import Path


def _load_env_file(path):
    """Read KEY=VALUE lines into the environment; real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() and not key.strip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(Path(__file__).resolve().parents[2] / ".env")

from .base import *  # noqa: E402,F401,F403
from .base import BASE_DIR, CSRF_TRUSTED_ORIGINS, env_bool  # noqa: E402

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

# The Vite dashboard (port 5173) proxies /admin to this server, so admin forms posted
# there carry Origin localhost:5173 while Django sees Host localhost:8000. Trust it here only.
_VITE_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
CSRF_TRUSTED_ORIGINS = CSRF_TRUSTED_ORIGINS + [o for o in _VITE_ORIGINS if o not in CSRF_TRUSTED_ORIGINS]
