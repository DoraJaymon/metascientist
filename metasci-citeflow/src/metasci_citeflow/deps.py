"""Dependency injection seam for CiteFlow tools.

Every tool takes ``deps: CiteFlowDeps | None`` and falls back to ``CiteFlowDeps.from_env()``.
This exists so the algorithm can be tested without monkeypatching: the previous port
imported its HTTP/LLM clients inside function bodies, which made the decision logic
untestable in isolation.  ``sleep`` is injected too, so retry/backoff paths run instantly
under test.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, Sequence, Tuple


class LLMClient(Protocol):
    async def complete(
        self,
        *,
        system: str,
        user: str,
        model: str,
        temperature: float = 0.5,
        history: Optional[Sequence[Dict[str, str]]] = None,
    ) -> str:
        """Return the assistant message content for a single completion."""


class S2SearchClient(Protocol):
    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
        year: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Keyword search returning normalised paper dicts."""


class OpenAlexGraphClient(Protocol):
    async def resolve_many(self, queries: Sequence[Dict[str, str]]) -> List[Optional[Dict[str, Any]]]:
        """Resolve ``{"doi": ...}`` / ``{"title": ...}`` queries to OpenAlex works."""

    async def get_by_ids(self, openalex_ids: Sequence[str]) -> List[Optional[Dict[str, Any]]]:
        """Hydrate full metadata for OpenAlex work ids."""

    async def get_references(
        self, openalex_id: str, *, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Fetch the works this paper cites."""

    async def get_citations(
        self,
        openalex_ids: Sequence[str],
        *,
        year_range: Optional[Tuple[int, int]] = None,
        min_cited_by: int = 0,
        field_id: Optional[str] = None,
        max_per_work: Optional[int] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch citing works, filtered and fully paginated."""


class RerankerClient(Protocol):
    async def rerank(self, query: str, documents: Sequence[str]) -> List[float]:
        """Return one relevance score per document, aligned by index."""


async def _default_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class CiteFlowDeps:
    """External collaborators for the CiteFlow tools."""

    llm: Optional[LLMClient] = None
    s2: Optional[S2SearchClient] = None
    openalex: Optional[OpenAlexGraphClient] = None
    reranker: Optional[RerankerClient] = None
    sleep: Callable[[float], Awaitable[None]] = _default_sleep
    now: Callable[[], datetime] = _utcnow
    _built: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_env(cls) -> "CiteFlowDeps":
        """Build real clients from environment variables (lazily, on first access)."""
        return cls()

    # Lazy construction keeps optional dependencies (and their env vars) out of the
    # import path for tools that do not need them.

    def require_llm(self) -> LLMClient:
        if self.llm is None:
            from metasci_citeflow.llm.client import OpenAICompatibleClient

            self.llm = OpenAICompatibleClient()
        return self.llm

    def require_s2(self) -> S2SearchClient:
        if self.s2 is None:
            from metasci_citeflow.providers.s2_search import SemanticScholarSearchClient

            self.s2 = SemanticScholarSearchClient()
        return self.s2

    def require_openalex(self) -> OpenAlexGraphClient:
        if self.openalex is None:
            from metasci_citeflow.providers.openalex_graph import OpenAlexGraph

            self.openalex = OpenAlexGraph()
        return self.openalex

    def require_reranker(self) -> RerankerClient:
        if self.reranker is None:
            from metasci_citeflow.scoring.reranker import BGEReranker

            self.reranker = BGEReranker()
        return self.reranker


def resolve_deps(deps: Optional[CiteFlowDeps]) -> CiteFlowDeps:
    return deps if deps is not None else CiteFlowDeps.from_env()
