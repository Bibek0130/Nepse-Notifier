from .base import *  # noqa: F401,F403
from .base import CSRF_TRUSTED_ORIGINS, env_bool

DEBUG = env_bool("DJANGO_DEBUG", True)


# The Vite dashboard (port 5173) proxies /admin to this server, so admin forms posted
# there carry Origin localhost:5173 while Django sees Host localhost:8000. Trust it here only.
_VITE_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
CSRF_TRUSTED_ORIGINS = CSRF_TRUSTED_ORIGINS + [o for o in _VITE_ORIGINS if o not in CSRF_TRUSTED_ORIGINS]
