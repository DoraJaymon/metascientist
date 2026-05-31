"""Provider interfaces and small provider result helper."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from metasci_universe.schemas.authors import AuthorProfileRequest, AuthorSearchRequest, WorkAuthorsRequest
from metasci_universe.schemas.conferences import ConferencePapersRequest
from metasci_universe.schemas.works import WorksGetRequest, WorksSearchRequest


@dataclass
class ProviderResult:
    """Provider-level result before artifact writing."""

    data: Any
    metadata: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)


class MetaSciProvider(Protocol):
    """Protocol implemented by data providers."""

    async def search_works(self, request: WorksSearchRequest) -> ProviderResult:
        ...

    async def get_work(self, request: WorksGetRequest) -> ProviderResult:
        ...

    async def search_authors(self, request: AuthorSearchRequest) -> ProviderResult:
        ...

    async def get_author(self, request: AuthorProfileRequest) -> ProviderResult:
        ...

    async def authors_from_work(self, request: WorkAuthorsRequest) -> ProviderResult:
        ...


class ConferencePapersProvider(Protocol):
    """Protocol implemented by conference-paper providers."""

    async def search_conference_papers(self, request: ConferencePapersRequest) -> ProviderResult:
        ...
