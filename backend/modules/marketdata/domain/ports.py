"""Interfaces the application layer depends on; infrastructure implements them."""
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from .entities import HistoricalBar, Quote


class SourceError(Exception):
    """A source was unreachable or returned something we could not parse."""


@dataclass(frozen=True)
class RawResponse:
    source: str
    url: str
    body: str
    content_type: str = "text/html"


class MarketDataSource(Protocol):
    name: str

    def fetch_raw(self) -> RawResponse: ...

    def parse(self, body: str) -> list[Quote]: ...


class HistorySource(Protocol):
    name: str

    def fetch_history(self, symbol: str, start: date, end: date) -> list[HistoricalBar]: ...
