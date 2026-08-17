"""Semantic Scholar keyword search.

Semantic Scholar is the entry point for Phase 1: it has better keyword recall on
natural-language research questions than OpenAlex's search.  Papers it returns carry a
``corpus_id`` but **no OpenAlex id** — the S2 ``externalIds`` payload exposes
ArXiv / ACL / DBLP / MAG / DOI / CorpusId and nothing else.  Since the whole citation
graph is keyed on OpenAlex work ids, every search result must be resolved through
``OpenAlexGraph.resolve_many`` before it is useful; that step is what ``cf.papers.search``
does, and skipping it leaves the store with papers that can never be expanded.

The DOI and MAG ids parsed here are the resolution keys.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from typing import Any, Dict, List, Optional

from metasci_citeflow.errors import S2Unavailable

logger = logging.getLogger(__name__)

S2_BASE = "https://api.semanticscholar.org/graph/v1"

SEARCH_FIELDS = ",".join(
    [
        "paperId",
        "title",
        "abstract",
        "year",
        "authors",
        "venue",
        "url",
        "externalIds",
        "fieldsOfStudy",
        "citationCount",
        "influentialCitationCount",
        "referenceCount",
    ]
)


def parse_paper(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalise one S2 search hit into a CuraLib-compatible paper dict."""
    if not data:
        return None
    external = data.get("externalIds") or {}
    corpus_id = external.get("CorpusId")
    paper_id = data.get("paperId") or ""
    if not corpus_id and not paper_id:
        return None

    citation_count = data.get("citationCount") or 0
    return {
        "corpus_id": str(corpus_id) if corpus_id else str(paper_id),
        "paper_id": paper_id,
        # Never present from S2; resolution fills it in.
        "openalex_id": None,
        "doi": (external.get("DOI") or "").lower() or None,
        "mag_id": str(external.get("MAG")) if external.get("MAG") else None,
        "arxiv_id": external.get("ArXiv"),
        "title": data.get("title") or "",
        "abstract": data.get("abstract") or "",
        "year": data.get("year"),
        "publication_year": data.get("year"),
        "authors": [author.get("name", "") for author in (data.get("authors") or [])],
        "venue": data.get("venue") or "",
        "url": data.get("url") or "",
        "citation_count": citation_count,
        "cited_by_count": citation_count,
        "reference_count": data.get("referenceCount") or 0,
        "influential_citation_count": data.get("influentialCitationCount") or 0,
        "fields_of_study": data.get("fieldsOfStudy") or [],
        "_source": "semantic_scholar",
    }


class SemanticScholarSearchClient:
    """Rate-limited async client for the Semantic Scholar paper search endpoint."""

    # The anonymous pool is shared and aggressively throttled; an API key gets a
    # dedicated quota, so the spacing between requests can drop sharply.
    REQUEST_INTERVAL = 3.5
    AUTHENTICATED_REQUEST_INTERVAL = 1.1
    MAX_RETRIES = 5

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        request_interval: Optional[float] = None,
        client: Any = None,
    ) -> None:
        self.api_key = api_key or os.getenv("S2_API_KEY") or os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        default_interval = (
            self.AUTHENTICATED_REQUEST_INTERVAL if self.api_key else self.REQUEST_INTERVAL
        )
        self.request_interval = float(
            request_interval
            if request_interval is not None
            else os.getenv("S2_REQUEST_INTERVAL", default_interval)
        )
        self._client = client
        self._owns_client = client is None
        self._last_request = 0.0

    async def _get_client(self):
        if self._client is None:
            import httpx

            headers = {"x-api-key": self.api_key} if self.api_key else {}
            self._client = httpx.AsyncClient(headers=headers, timeout=30.0)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "SemanticScholarSearchClient":
        await self._get_client()
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.aclose()

    async def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.request_interval:
            await asyncio.sleep(self.request_interval - elapsed)

    async def _get(self, path: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        client = await self._get_client()
        transient_failure = False
        last_status = 0
        for attempt in range(self.MAX_RETRIES):
            await self._throttle()
            try:
                response = await client.get(f"{S2_BASE}{path}", params=params)
                self._last_request = time.monotonic()
                last_status = response.status_code
                if response.status_code == 200:
                    return response.json()
                if response.status_code == 429 or response.status_code >= 500:
                    transient_failure = True
                    retry_after = response.headers.get("Retry-After")
                    wait = (
                        float(retry_after)
                        if retry_after
                        else self.request_interval * (2**attempt)
                    )
                    wait = min(60.0, wait + random.uniform(0.1, 0.5))
                    logger.warning(
                        "Semantic Scholar HTTP %s; waiting %.1fs (attempt %d/%d)",
                        response.status_code,
                        wait,
                        attempt + 1,
                        self.MAX_RETRIES,
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.warning("Semantic Scholar HTTP %s for %s", response.status_code, path)
                return None
            except Exception as exc:
                transient_failure = True
                logger.warning("Semantic Scholar request error: %s", exc)
                await asyncio.sleep(self.request_interval * (2**attempt))

        if transient_failure:
            raise S2Unavailable(
                f"Semantic Scholar unavailable after {self.MAX_RETRIES} retries "
                f"(last status: {last_status}). "
                "Set S2_API_KEY for a dedicated quota."
            )
        return None

    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
        year: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Keyword search. ``year`` uses the S2 range syntax, e.g. ``"2015-2023"``."""
        papers: List[Dict[str, Any]] = []
        offset = 0

        while len(papers) < limit:
            params: Dict[str, Any] = {
                "query": query,
                "limit": min(100, limit - len(papers)),
                "fields": SEARCH_FIELDS,
            }
            if year:
                params["year"] = year
            if offset:
                params["offset"] = offset

            payload = await self._get("/paper/search", params)
            if not payload:
                break

            batch = payload.get("data") or []
            if not batch:
                break
            for item in batch:
                parsed = parse_paper(item)
                if parsed:
                    papers.append(parsed)

            offset += len(batch)
            total = payload.get("total", 0)
            if offset >= total or len(batch) < params["limit"]:
                break

        return papers[:limit]
