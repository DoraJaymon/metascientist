"""Shared conference-paper spider primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from metasci_universe.schemas.conferences import ConferencePapersRequest


@dataclass
class ConferenceCrawlResult:
    """Raw spider result before provider wrapping."""

    records: list[dict[str, Any]]
    total: int
    metadata: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)


class ConferenceSpider(Protocol):
    """Small source-specific spider interface."""

    source: str
    name: str

    async def crawl(self, request: ConferencePapersRequest) -> ConferenceCrawlResult:
        ...
