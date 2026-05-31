"""CVF Open Access provider and spider for computer-vision proceedings."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import httpx

from metasci_universe.providers.base import ProviderResult
from metasci_universe.providers.conference_spiders import ConferenceCrawlResult
from metasci_universe.providers.html_utils import Link, extract_links, html_text
from metasci_universe.schemas.conferences import ConferencePapersRequest


CVF_OPENACCESS_BASE_URL = "https://openaccess.thecvf.com"
CVF_VENUES = {"cvpr", "iccv", "wacv"}


class CVFOpenAccessPaperSpider:
    """Spider for CVF Open Access paper listing pages."""

    source = "cvf"
    name = "cvf-openaccess-html"

    def __init__(
        self,
        *,
        base_url: str = CVF_OPENACCESS_BASE_URL,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client

    async def crawl(self, request: ConferencePapersRequest) -> ConferenceCrawlResult:
        listing_url = self._listing_url(request)
        html = await self._get_text(listing_url)
        records = self._parse_listing(html, request=request, listing_url=listing_url)

        if request.query:
            query = request.query.casefold()
            records = [record for record in records if query in str(record.get("title") or "").casefold()]

        diagnostics: list[str] = []
        total = len(records)
        if request.limit < total:
            diagnostics.append(f"Returned first {request.limit} CVF records out of {total}.")

        return ConferenceCrawlResult(
            records=records[: request.limit],
            total=total,
            metadata={
                "source": self.source,
                "spider": self.name,
                "listing_url": listing_url,
            },
            diagnostics=diagnostics,
        )

    def _listing_url(self, request: ConferencePapersRequest) -> str:
        if request.source_collection_id:
            slug = request.source_collection_id.strip()
            if slug.startswith("http://") or slug.startswith("https://"):
                return slug
            return urljoin(f"{self.base_url}/", slug.lstrip("/"))
        return f"{self.base_url}/{request.venue.upper()}{request.year}?day=all"

    def _parse_listing(
        self,
        html: str,
        *,
        request: ConferencePapersRequest,
        listing_url: str,
    ) -> list[dict[str, Any]]:
        links = extract_links(html)
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, link in enumerate(links):
            if not self._is_paper_link(link.href, link.text):
                continue
            landing_url = urljoin(self.base_url, link.href)
            record_id = self._record_id(landing_url)
            if record_id in seen:
                continue
            seen.add(record_id)
            pdf_url = self._find_pdf_url(links[index + 1 : index + 8])
            records.append(self._record(record_id, link.text, landing_url, pdf_url, request, listing_url))
        return records

    def _is_paper_link(self, href: str, text: str) -> bool:
        if not text:
            return False
        normalized = href.casefold()
        return "html" in normalized and "_paper.html" in normalized

    def _find_pdf_url(self, nearby_links: list[Link]) -> str | None:
        for link in nearby_links:
            if link.href.casefold().endswith(".pdf") or "pdf" in link.text.casefold():
                return urljoin(self.base_url, link.href)
        return None

    def _record_id(self, landing_url: str) -> str:
        return landing_url.rstrip("/").rsplit("/", 1)[-1].replace(".html", "")

    def _record(
        self,
        record_id: str,
        title: str,
        landing_url: str,
        pdf_url: str | None,
        request: ConferencePapersRequest,
        listing_url: str,
    ) -> dict[str, Any]:
        return {
            "id": f"cvf:{record_id}",
            "source_record_id": record_id,
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
                "id": f"cvf:venue:{request.venue}",
                "name": request.venue.upper(),
                "type": "conference",
                "acronym": request.venue.upper(),
                "year": request.year,
            },
            "external_ids": {
                "cvf": record_id,
            },
            "cvf": {
                "paper_id": record_id,
                "listing_url": listing_url,
            },
            "provenance": [
                {
                    "source": self.source,
                    "spider": self.name,
                    "record_id": record_id,
                    "url": landing_url,
                    "retrieval_key": listing_url,
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


class CVFOpenAccessProvider:
    """Provider backed by a CVF Open Access spider."""

    name = "cvf"

    def __init__(
        self,
        *,
        base_url: str = CVF_OPENACCESS_BASE_URL,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
        spider: CVFOpenAccessPaperSpider | None = None,
    ) -> None:
        self.spider = spider or CVFOpenAccessPaperSpider(base_url=base_url, timeout=timeout, client=client)

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
