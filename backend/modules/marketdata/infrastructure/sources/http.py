import requests
from django.conf import settings

from ...domain.ports import RawResponse, SourceError


class HttpSource:
    """Base for sources that fetch over HTTP."""

    name = "http"
    url = ""

    def __init__(self, session=None):
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", settings.MARKETDATA["USER_AGENT"])

    def get(self, url, **kwargs):
        kwargs.setdefault("timeout", settings.MARKETDATA["HTTP_TIMEOUT"])
        try:
            response = self.session.get(url, **kwargs)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise SourceError(f"{self.name}: request to {url} failed: {exc}") from exc
        return response

    def fetch_raw(self):
        response = self.get(self.url)
        return RawResponse(
            source=self.name,
            url=self.url,
            body=response.text,
            content_type=response.headers.get("Content-Type", "text/html"),
        )
