"""PMLR provider and spider for machine-learning proceedings."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

import httpx

from metasci_universe.providers.base import ProviderResult
from metasci_universe.providers.conference_spiders import ConferenceCrawlResult
from metasci_universe.providers.html_utils import extract_links, html_text
from metasci_universe.schemas.conferences import ConferencePapersRequest


PMLR_BASE_URL = "https://proceedings.mlr.press"
PMLR_VENUES = {"aistats", "colt", "corl", "uai"}


class PMLRPaperSpider:
    """Spider for Proceedings of Machine Learning Research volume pages."""

    source = "pmlr"
    name = "pmlr-volume-html"

    def __init__(
        self,
        *,
        base_url: str = PMLR_BASE_URL,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client

    async def crawl(self, request: ConferencePapersRequest) -> ConferenceCrawlResult:
        volume_url = await self._resolve_volume_url(request)
        html = await self._get_text(volume_url)
        records = self._parse_volume(html, request=request, volume_url=volume_url)

        if request.query:
            query = request.query.casefold()
            records = [record for record in records if query in str(record.get("title") or "").casefold()]

        diagnostics: list[str] = []
        total = len(records)
        if request.limit < total:
            diagnostics.append(f"Returned first {request.limit} PMLR records out of {total}.")

        return ConferenceCrawlResult(
            records=records[: request.limit],
            total=total,
            metadata={
                "source": self.source,
                "spider": self.name,
                "volume_url": volume_url,
            },
            diagnostics=diagnostics,
        )

    async def _resolve_volume_url(self, request: ConferencePapersRequest) -> str:
        if request.source_collection_id:
            return self._collection_url(request.source_collection_id)

        html = await self._get_text(f"{self.base_url}/")
        year = str(request.year)
        venue = request.venue.casefold()
        candidates = []
        for link in extract_links(html):
            haystack = f"{link.text} {link.href}".casefold()
            if year in haystack and venue in haystack and "/v" in link.href:
                candidates.append(urljoin(self.base_url, link.href))
        if candidates:
            return candidates[0]

        raise ValueError(
            f"No PMLR volume found for venue={request.venue!r}, year={request.year}. "
            "Pass source_collection_id explicitly, e.g. 'v235'."
        )

    def _collection_url(self, collection_id: str) -> str:
        slug = collection_id.strip().strip("/")
        if slug.startswith("http://") or slug.startswith("https://"):
            return slug
        return f"{self.base_url}/{slug}/"

    def _parse_volume(
        self,
        html: str,
        *,
        request: ConferencePapersRequest,
        volume_url: str,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for link in extract_links(html):
            if not self._is_paper_link(link.href, link.text):
                continue
            landing_url = urljoin(self.base_url, link.href)
            paper_id = landing_url.rstrip("/").rsplit("/", 1)[-1].replace(".html", "")
            if paper_id in seen:
                continue
            seen.add(paper_id)
            records.append(self._record(paper_id, link.text, landing_url, request, volume_url))
        return records

    def _is_paper_link(self, href: str, text: str) -> bool:
        if not text or href.casefold().endswith(".pdf"):
            return False
        return bool(re.search(r"/v\d+/[^/]+\.html$", href, flags=re.IGNORECASE))

    def _record(
        self,
        paper_id: str,
        title: str,
        landing_url: str,
        request: ConferencePapersRequest,
        volume_url: str,
    ) -> dict[str, Any]:
        pdf_url = landing_url.replace(".html", ".pdf") if landing_url.endswith(".html") else None
        return {
            "id": f"pmlr:{paper_id}",
            "source_record_id": paper_id,
            "title": html_text(title),
            "publication_year": request.year,
            "publication_date": None,
            "type": "conference-paper",
            "abstract": None,
            "authors": [],
            "doi": None,
            "pdf_url": pdf_url,
            "landing_url": landing_url,
            "source": {
                "id": f"pmlr:venue:{request.venue}",
                "name": request.venue.upper(),
                "type": "conference",
                "acronym": request.venue.upper(),
                "year": request.year,
            },
            "external_ids": {
                "pmlr": paper_id,
            },
            "pmlr": {
                "paper_id": paper_id,
                "volume_url": volume_url,
            },
            "provenance": [
                {
                    "source": self.source,
                    "spider": self.name,
                    "record_id": paper_id,
                    "url": landing_url,
                    "retrieval_key": volume_url,
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


class PMLRProvider:
    """Provider backed by a PMLR volume spider."""

    name = "pmlr"

    def __init__(
        self,
        *,
        base_url: str = PMLR_BASE_URL,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
        spider: PMLRPaperSpider | None = None,
    ) -> None:
        self.spider = spider or PMLRPaperSpider(base_url=base_url, timeout=timeout, client=client)

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
