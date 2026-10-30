"""Read-only demo mode (config.settings.demo): nothing a visitor does can change the data or send email."""
from django.conf import settings
from django.http import HttpResponseForbidden

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Logging in and out of the view-only admin account is the only change a visitor can make.
ALLOWED_PATHS = {"/admin/login/", "/admin/logout/"}

REFUSED = """<!doctype html><meta charset="utf-8"><title>Read-only demo</title>
<body style="font-family:system-ui,sans-serif;max-width:36rem;margin:4rem auto;padding:0 1rem;line-height:1.5">
<h1>This is a read-only demo</h1>
<p>Changes, evaluations and email sign-ups are switched off here, so the demo shows the same data to everyone.
Run the project yourself to try them.</p>
<p><a href="javascript:history.back()">Go back</a></p></body>"""


class ReadOnlyDemoMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(settings, "DEMO_MODE", False) and request.method not in SAFE_METHODS and request.path not in ALLOWED_PATHS:
            return HttpResponseForbidden(REFUSED)
        return self.get_response(request)


def demo_context(request):
    """Lets admin templates show the demo banner and the view-only login."""
    if not getattr(settings, "DEMO_MODE", False):
        return {}
    return {"demo_mode": True, "demo_username": settings.DEMO_VIEWER_USERNAME, "demo_password": settings.DEMO_VIEWER_PASSWORD}
