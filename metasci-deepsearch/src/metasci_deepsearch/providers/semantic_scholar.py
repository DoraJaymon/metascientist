"""Semantic Scholar keyword search provider for metasci-deepsearch.

Provides SemanticScholarSearchClient for iterative keyword retrieval.
Adapted from AcaDeepR/src/tools/paper_search/semantic_scholar_tools.py.
Removed: light-agent decorators.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

_S2_BASE = "https://api.semanticscholar.org/graph/v1"
_DEFAULT_FIELDS = ",".join([
    "paperId", "title", "abstract", "year", "authors",
    "venue", "url", "externalIds", "fieldsOfStudy",
    "citationCount", "influentialCitationCount", "referenceCount",
    "references.paperId", "references.corpusId", "references.title",
    "references.year", "references.citationCount", "references.venue",
])


@dataclass
class Paper:
    """Semantic Scholar paper record."""
    paper_id: str
    title: str = ""
    abstract: Optional[str] = None
    year: Optional[int] = None
    authors: List[str] = field(default_factory=list)
    venue: Optional[str] = None
    citation_count: int = 0
    url: Optional[str] = None
    doi: Optional[str] = None
    fields_of_study: List[str] = field(default_factory=list)
    external_info: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "abstract": self.abstract,
            "year": self.year,
            "authors": self.authors,
            "venue": self.venue,
            "citation_count": self.citation_count,
            "url": self.url,
            "doi": self.doi,
            "fields_of_study": self.fields_of_study,
            "external_info": self.external_info,
            # Aliases for CuraLib compatibility
            "corpus_id": str(self.external_info.get("corpusId", "") or self.paper_id),
            "openalex_id": self.external_info.get("openalex_id"),
            "cited_by_count": self.citation_count,
            "publication_year": self.year,
        }


def _parse_paper(data: Dict) -> Paper:
    authors = [a.get("name", "") for a in (data.get("authors") or [])]
    ext = data.get("externalIds") or {}
    doi = ext.get("DOI")
    corpus_id = ext.get("CorpusId")

    refs_data = data.get("references") or []
    references = []
    for ref in refs_data:
        rid = ref.get("paperId", "")
        ref_corpus = ref.get("corpusId") or (ref.get("externalIds") or {}).get("CorpusId", "")
        references.append({
            "paperId": rid,
            "corpusId": str(ref_corpus) if ref_corpus else "",
            "title": ref.get("title", ""),
            "year": ref.get("year"),
            "citationCount": ref.get("citationCount", 0),
            "venue": ref.get("venue", ""),
        })

    external_info: Dict[str, Any] = {
        "corpusId": str(corpus_id) if corpus_id else "",
        "doi": doi or "",
        "referenceCount": data.get("referenceCount", 0),
        "influentialCitationCount": data.get("influentialCitationCount", 0),
        "references": references,
    }

    return Paper(
        paper_id=data.get("paperId", ""),
        title=data.get("title", "") or "",
        abstract=data.get("abstract"),
        year=data.get("year"),
        authors=authors,
        venue=data.get("venue"),
        citation_count=data.get("citationCount", 0),
        url=data.get("url"),
        doi=doi,
        fields_of_study=data.get("fieldsOfStudy") or [],
        external_info=external_info,
    )


class SemanticScholarSearchClient:
    """Async Semantic Scholar REST API client for keyword-based paper retrieval.

    Usage::

        async with SemanticScholarSearchClient() as s2:
            papers = await s2.search_papers("graph neural network drug discovery", limit=50)
    """

    REQUEST_INTERVAL = 3.5
    MAX_RETRIES = 5

    def __init__(
        self,
        api_key: Optional[str] = None,
        request_interval: Optional[float] = None,
        year_upper_limit: Optional[int] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("S2_API_KEY")
        self.request_interval = float(request_interval or os.getenv("S2_REQUEST_INTERVAL", self.REQUEST_INTERVAL))
        self.year_upper_limit = year_upper_limit
        self._session: Optional[aiohttp.ClientSession] = None
        self._last_request_time: float = 0

    async def __aenter__(self) -> "SemanticScholarSearchClient":
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        self._session = aiohttp.ClientSession(headers=headers)
        return self

    async def __aexit__(self, *_) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def _wait(self) -> None:
        elapsed = time.time() - self._last_request_time
        if elapsed < self.request_interval:
            await asyncio.sleep(self.request_interval - elapsed)

    async def _get(self, url: str, params: Dict) -> Optional[Dict]:
        assert self._session, "Use as async context manager"
        for attempt in range(self.MAX_RETRIES):
            await self._wait()
            try:
                async with self._session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    self._last_request_time = time.time()
                    if resp.status == 200:
                        return await resp.json()
                    if resp.status == 429:
                        retry_after = resp.headers.get("Retry-After")
                        wait = float(retry_after) if retry_after else self.request_interval * (2 ** attempt)
                        wait = min(60, wait + random.uniform(0.1, 0.5))
                        logger.warning("S2 rate limit, waiting %.1fs (attempt %d)", wait, attempt + 1)
                        await asyncio.sleep(wait)
                    else:
                        logger.warning("S2 HTTP %d for %s", resp.status, url)
                        return None
            except asyncio.TimeoutError:
                await asyncio.sleep(self.request_interval * (2 ** attempt))
            except Exception as exc:
                logger.warning("S2 request error: %s", exc)
                await asyncio.sleep(self.request_interval)
        return None

    async def search_papers(
        self,
        query: str,
        limit: int = 50,
        year: Optional[str] = None,
        fields_of_study: Optional[List[str]] = None,
    ) -> List[Paper]:
        """Keyword search. Returns up to `limit` Paper objects."""
        if not self._session:
            raise RuntimeError("Use as async context manager: async with S2Client() as s2:")

        # Apply year upper limit
        effective_year = year
        if self.year_upper_limit is not None:
            if effective_year is None:
                effective_year = f"-{self.year_upper_limit}"

        params: Dict[str, Any] = {
            "query": query,
            "limit": min(limit, 100),
            "fields": _DEFAULT_FIELDS,
        }
        if effective_year:
            params["year"] = effective_year
        if fields_of_study:
            params["fieldsOfStudy"] = ",".join(fields_of_study)

        data = await self._get(f"{_S2_BASE}/paper/search", params)
        if not data:
            return []

        papers = []
        for item in data.get("data", []):
            try:
                papers.append(_parse_paper(item))
            except Exception as exc:
                logger.debug("Failed to parse S2 paper: %s", exc)

        # If we need more than 100, paginate
        total = data.get("total", 0)
        if limit > 100 and total > 100:
            offset = 100
            while offset < min(limit, total):
                params["offset"] = offset
                params["limit"] = min(100, limit - offset)
                page_data = await self._get(f"{_S2_BASE}/paper/search", params)
                if not page_data:
                    break
                for item in page_data.get("data", []):
                    try:
                        papers.append(_parse_paper(item))
                    except Exception:
                        pass
                offset += 100

        return papers[:limit]

    async def get_all_citations(
        self,
        paper_id: Optional[str] = None,
        title: Optional[str] = None,
        max_citations: int = 500,
        batch_size: int = 100,
    ) -> List[Paper]:
        """Fetch all citing papers for a given paper (by ID or title search)."""
        if not self._session:
            raise RuntimeError("Use as async context manager")

        # Resolve paper_id from title if needed
        if not paper_id and title:
            results = await self.search_papers(title, limit=1)
            if not results:
                return []
            paper_id = results[0].paper_id

        if not paper_id:
            return []

        papers = []
        fields = "paperId,title,abstract,year,authors,venue,citationCount,url,externalIds"
        offset = 0

        while len(papers) < max_citations:
            params = {
                "fields": fields,
                "limit": min(batch_size, max_citations - len(papers)),
                "offset": offset,
            }
            data = await self._get(f"{_S2_BASE}/paper/{paper_id}/citations", params)
            if not data:
                break
            items = data.get("data", [])
            if not items:
                break
            for item in items:
                citing = item.get("citingPaper") or item
                try:
                    papers.append(_parse_paper(citing))
                except Exception:
                    pass
            offset += len(items)
            if len(items) < batch_size:
                break

        return papers
