"""ACL Anthology provider and spider for NLP conference-paper entry points."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

import httpx

from metasci_universe.providers.base import ProviderResult
from metasci_universe.providers.conference_spiders import ConferenceCrawlResult
from metasci_universe.providers.html_utils import extract_links, html_text
from metasci_universe.schemas.conferences import ConferencePapersRequest


ACL_ANTHOLOGY_BASE_URL = "https://aclanthology.org"
ACL_VENUES = {"acl", "emnlp", "naacl", "coling", "eacl", "findings"}


class ACLAnthologyPaperSpider:
    """Spider for ACL Anthology proceedings pages."""

    source = "acl"
    name = "acl-anthology-proceedings-html"

    def __init__(
        self,
        *,
        base_url: str = ACL_ANTHOLOGY_BASE_URL,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client

    async def crawl(self, request: ConferencePapersRequest) -> ConferenceCrawlResult:
        proceedings_url = await self._resolve_proceedings_url(request)
        html = await self._get_text(proceedings_url)
        records = self._parse_proceedings(html, request=request, proceedings_url=proceedings_url)

        if request.query:
            query = request.query.casefold()
            records = [record for record in records if query in str(record.get("title") or "").casefold()]

        diagnostics: list[str] = []
        total = len(records)
        if request.limit < total:
            diagnostics.append(f"Returned first {request.limit} ACL Anthology records out of {total}.")
        limited = records[: request.limit]

        return ConferenceCrawlResult(
            records=limited,
            total=total,
            metadata={
                "source": self.source,
                "spider": self.name,
                "proceedings_url": proceedings_url,
            },
            diagnostics=diagnostics,
        )

    async def _resolve_proceedings_url(self, request: ConferencePapersRequest) -> str:
        if request.source_collection_id:
            return self._collection_url(request.source_collection_id)

        venue_url = f"{self.base_url}/venues/{request.venue}/"
        html = await self._get_text(venue_url)
        year = str(request.year)
        candidates = []
        for link in extract_links(html):
            href = link.href
            text = f"{link.text} {href}".casefold()
            if year in text and self._href_matches_venue_year(href, request.venue, year):
                candidates.append(urljoin(self.base_url, href))
        if candidates:
            return candidates[0]

        raise ValueError(
            f"No ACL Anthology proceedings page found for venue={request.venue!r}, year={request.year}. "
            "Pass source_collection_id explicitly, e.g. '2024.acl-long'."
        )

    def _href_matches_venue_year(self, href: str, venue: str, year: str) -> bool:
        normalized = href.strip("/").casefold()
        return normalized.startswith(f"{year}.{venue}") or normalized.startswith(f"{year}-{venue}")

    def _collection_url(self, collection_id: str) -> str:
        slug = collection_id.strip().strip("/")
        if slug.startswith("http://") or slug.startswith("https://"):
            return slug
        return f"{self.base_url}/{slug}/"

    def _parse_proceedings(
        self,
        html: str,
        *,
        request: ConferencePapersRequest,
        proceedings_url: str,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for link in extract_links(html):
            href = link.href
            title = link.text
            if not self._is_paper_link(href, title):
                continue
            landing_url = urljoin(self.base_url, href)
            paper_id = landing_url.rstrip("/").rsplit("/", 1)[-1]
            if paper_id in seen:
                continue
            seen.add(paper_id)
            records.append(self._record_from_listing(paper_id, title, landing_url, request, proceedings_url))
        return records

    def _is_paper_link(self, href: str, text: str) -> bool:
        if not text or href.endswith(".pdf") or href.startswith("#"):
            return False
        normalized = href.strip("/")
        return bool(re.match(r"^\d{4}\.[a-z0-9-]+\.\d+$", normalized, flags=re.IGNORECASE))

    def _record_from_listing(
        self,
        paper_id: str,
        title: str,
        landing_url: str,
        request: ConferencePapersRequest,
        proceedings_url: str,
    ) -> dict[str, Any]:
        return {
            "id": f"acl:{paper_id}",
            "source_record_id": paper_id,
            "title": html_text(title),
            "publication_year": request.year,
            "publication_date": None,
            "type": "conference-paper",
            "abstract": None,
            "authors": [],
            "doi": None,
            "pdf_url": f"{landing_url.rstrip('/')}.pdf",
            "landing_url": landing_url,
            "source": {
                "id": f"acl:venue:{request.venue}",
                "name": request.venue.upper(),
                "type": "conference",
                "acronym": request.venue.upper(),
                "year": request.year,
            },
            "external_ids": {
                "acl": paper_id,
            },
            "acl": {
                "anthology_id": paper_id,
                "proceedings_url": proceedings_url,
            },
            "provenance": [
                {
                    "source": self.source,
                    "spider": self.name,
                    "record_id": paper_id,
                    "url": landing_url,
                    "retrieval_key": proceedings_url,
                }
            ],
        }

    async def _get_text(self, url: str) -> str:
        if self._client is not None:
            response = await self._client.get(url)
            response.raise_for_status()
            return response.text

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text


class ACLAnthologyProvider:
    """Provider backed by an ACL Anthology proceedings spider."""

    name = "acl"

    def __init__(
        self,
        *,
        base_url: str = ACL_ANTHOLOGY_BASE_URL,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
        spider: ACLAnthologyPaperSpider | None = None,
    ) -> None:
        self.spider = spider or ACLAnthologyPaperSpider(base_url=base_url, timeout=timeout, client=client)

    async def search_conference_papers(self, request: ConferencePapersRequest) -> ProviderResult:
        crawl = await self.spider.crawl(request)
        metadata = {
            "provider": self.name,
            "venue": request.venue,
            "year": request.year,
            "status": request.status,
            "returned_count": len(crawl.records),
            "filtered_total": crawl.total,
            **crawl.metadata,
        }
        return ProviderResult(data=crawl.records, metadata=metadata, diagnostics=crawl.diagnostics)
