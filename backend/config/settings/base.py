"""Settings shared by every environment. Environment-specific values come from env vars."""
import os
from pathlib import Path

from celery.schedules import crontab
from kombu import Queue

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return env(name, str(default)).lower() in {"1", "true", "yes", "on"}


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = [h for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
# Origins other than the server's own that may send forms (admin login) to it, e.g. a proxy in front of it.
CSRF_TRUSTED_ORIGINS = [o for o in env("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_celery_beat",
    # Domain modules. Each is a Django app with its own public interface (public.py).
    "modules.shared",
    "modules.marketdata",
    "modules.analysis",
    "modules.analysis.quant",  # admin "Quant" section
    "modules.notifications",
    "modules.accounts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# PostgreSQL is the system of record.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "nepse"),
        "USER": env("POSTGRES_USER", "nepse"),
        "PASSWORD": env("POSTGRES_PASSWORD", "nepse"),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

# Redis: db 0 = Celery broker, db 1 = Celery results, db 2 = app cache and locks.
REDIS_URL = env("REDIS_URL", "redis://localhost:6379")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": f"{REDIS_URL}/2",
        "KEY_PREFIX": "nepse",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kathmandu"  # NEPSE runs on Nepal time.
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 500,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"modules": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")}},
}

# --- Celery ----------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", f"{REDIS_URL}/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", f"{REDIS_URL}/1")
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_QUEUES = [Queue("default"), Queue("ingest"), Queue("analysis"), Queue("notify")]
CELERY_TASK_ROUTES = {
    "modules.marketdata.tasks.*": {"queue": "ingest"},
    "modules.analysis.tasks.*": {"queue": "analysis"},
    "modules.notifications.tasks.*": {"queue": "notify"},
}
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# NEPSE trades Sunday-Thursday, 11:00-15:00 NPT. These entries are copied into the
# database on Beat startup, after which they can be edited in Django admin.
CELERY_BEAT_SCHEDULE = {
    "marketdata-intraday": {
        "task": "modules.marketdata.tasks.ingest_market",
        "schedule": crontab(minute=15, hour="11,14", day_of_week="sun,mon,tue,wed,thu"),
        "kwargs": {"kind": "intraday"},
    },
    "marketdata-end-of-day": {
        "task": "modules.marketdata.tasks.ingest_market",
        "schedule": crontab(minute=15, hour=15, day_of_week="sun,mon,tue,wed,thu"),
        "kwargs": {"kind": "eod"},
    },
    "analysis-weekly-backtest": {
        "task": "modules.analysis.tasks.run_backtest",
        "schedule": crontab(minute=0, hour=3, day_of_week="fri"),  # market closed Friday and Saturday
    },
    "marketdata-purge-raw": {
        "task": "modules.marketdata.tasks.purge_raw_payloads",
        "schedule": crontab(minute=0, hour=2),
    },
}

# --- Market data module -------------------------------------------------------
MARKETDATA = {
    # Snapshot sources, tried in order.
    "SOURCES": [s.strip() for s in env("MARKETDATA_SOURCES", "sharesansar,merolagani").split(",") if s.strip()],
    "HISTORY_SOURCE": "merolagani",
    "HTTP_TIMEOUT": int(env("MARKETDATA_HTTP_TIMEOUT", "30")),
    "USER_AGENT": env(
        "MARKETDATA_USER_AGENT",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36",
    ),
    "CIRCUIT_FAILURE_THRESHOLD": 3,
    "CIRCUIT_OPEN_SECONDS": 15 * 60,
    "RAW_RETENTION_DAYS": 30,
    "CACHE_TTL_SECONDS": 6 * 60 * 60,
    "PRICE_BAND_PERCENT": 10,  # NEPSE daily circuit limit
    "CROSS_SOURCE_TOLERANCE_PERCENT": 0.5,
    "INGEST_LOCK_SECONDS": 10 * 60,
}

# --- Email -------------------------------------------------------------------
# SMTP when EMAIL_HOST is set (e.g. Gmail, SES, Mailgun); otherwise emails print to the console.
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend" if EMAIL_HOST else "django.core.mail.backends.console.EmailBackend",
)
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_TIMEOUT = 30
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "NEPSE Notifier <noreply@localhost>")

# Public base URL, used for unsubscribe links in emails.
SITE_URL = env("SITE_URL", "http://localhost:8000")
