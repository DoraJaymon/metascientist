"""DBLP provider and spider for conference-paper entry points."""

from __future__ import annotations

from typing import Any

import httpx

from metasci_universe.providers.base import ProviderResult
from metasci_universe.providers.conference_spiders import ConferenceCrawlResult
from metasci_universe.schemas.conferences import ConferencePapersRequest


DEFAULT_DBLP_PUBLICATION_API = "https://dblp.org/search/publ/api"

DBLP_VENUE_ALIASES = {
    "aaai": "AAAI",
    "acl": "ACL",
    "acm mm": "ACM Multimedia",
    "chi": "CHI",
    "cikm": "CIKM",
    "cvpr": "CVPR",
    "eccv": "ECCV",
    "emnlp": "EMNLP",
    "iccv": "ICCV",
    "iclr": "ICLR",
    "icml": "ICML",
    "ijcai": "IJCAI",
    "kdd": "KDD",
    "mm": "ACM Multimedia",
    "naacl": "NAACL",
    "neurips": "NeurIPS",
    "nips": "NeurIPS",
    "sigir": "SIGIR",
    "sigmod": "SIGMOD Conference",
    "uist": "UIST",
    "www": "WWW",
}


class DblpPublicationSearchSpider:
    """Spider for DBLP publication-search results."""

    source = "dblp"
    name = "dblp-publication-search-api"

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_DBLP_PUBLICATION_API,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self._client = client

    async def crawl(self, request: ConferencePapersRequest) -> ConferenceCrawlResult:
        query = self.query(request)
        hits, total = await self._fetch_hits(query=query, limit=request.limit)
        records = [record for hit in hits if (record := self._normalize_hit(hit, request=request, query=query)) is not None]

        diagnostics: list[str] = []
        if request.limit < total:
            diagnostics.append(f"Returned first {request.limit} DBLP records out of {total}.")
        if len(records) < len(hits):
            diagnostics.append("Some DBLP hits were dropped because their year did not match the request.")

        return ConferenceCrawlResult(
            records=records,
            total=total,
            metadata={
                "source": self.source,
                "spider": self.name,
                "query": query,
            },
            diagnostics=diagnostics,
        )

    def query(self, request: ConferencePapersRequest) -> str:
        venue = DBLP_VENUE_ALIASES.get(request.venue, request.venue.upper())
        parts: list[str] = []
        if request.query:
            parts.append(request.query)
        parts.append(f"venue:{venue}:")
        parts.append(f"year:{request.year}:")
        return " ".join(parts)

    async def _fetch_hits(self, *, query: str, limit: int) -> tuple[list[dict[str, Any]], int]:
        hits: list[dict[str, Any]] = []
        total = 0
        offset = 0

        while len(hits) < limit:
            page_limit = min(100, limit - len(hits))
            payload = await self._get_json(
                params={
                    "q": query,
                    "format": "json",
                    "h": page_limit,
                    "f": offset,
                    "c": 0,
                }
            )
            hits_payload = ((payload.get("result") or {}).get("hits") or {})
            page_hits = self._as_list(hits_payload.get("hit"))
            total = self._int_or_zero(hits_payload.get("@total"))
            if not page_hits:
                break

            hits.extend(page_hits)
            offset += len(page_hits)
            if len(page_hits) < page_limit:
                break

        return hits[:limit], total or len(hits)

    async def _get_json(self, *, params: dict[str, Any]) -> dict[str, Any]:
        if self._client is not None:
            response = await self._client.get(self.base_url, params=params)
            response.raise_for_status()
            return response.json()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(self.base_url, params=params)
            response.raise_for_status()
            return response.json()

    def _normalize_hit(
        self,
        hit: dict[str, Any],
        *,
        request: ConferencePapersRequest,
        query: str,
    ) -> dict[str, Any] | None:
        info = hit.get("info") or {}
        year = self._int_or_zero(self._string(info.get("year")))
        if year and year != request.year:
            return None

        key = self._string(info.get("key"))
        title = self._string(info.get("title"))
        venue_name = self._string(info.get("venue")) or DBLP_VENUE_ALIASES.get(request.venue, request.venue.upper())
        ee_url = self._first_url(info.get("ee"))
        dblp_url = self._string(info.get("url"))
        doi = self._doi_url(self._string(info.get("doi")))
        landing_url = dblp_url or ee_url
        pdf_url = ee_url if ee_url and ee_url.lower().endswith(".pdf") else None

        record = {
            "id": f"dblp:{key}" if key else None,
            "source_record_id": key or None,
            "title": title,
            "publication_year": year or request.year,
            "publication_date": None,
            "type": "conference-paper",
            "abstract": None,
            "authors": self._normalize_authors(((info.get("authors") or {}).get("author"))),
            "doi": doi,
            "pdf_url": pdf_url,
            "landing_url": landing_url,
            "source": {
                "id": f"dblp:venue:{request.venue}",
                "name": venue_name,
                "type": "conference",
                "acronym": request.venue.upper(),
                "year": request.year,
            },
            "external_ids": {
                "dblp": key or None,
                "doi": doi,
            },
            "dblp": {
                "key": key or None,
                "type": self._string(info.get("type")),
                "pages": self._string(info.get("pages")),
                "access": self._string(info.get("access")),
                "ee": ee_url,
            },
            "provenance": [
                {
                    "source": self.source,
                    "spider": self.name,
                    "record_id": key or None,
                    "url": dblp_url,
                    "retrieval_key": query,
                }
            ],
        }
        if request.include_raw:
            record["_raw"] = hit
        return record

    def _normalize_authors(self, authors: Any) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, author in enumerate(self._as_list(authors), start=1):
            author_id = None
            if isinstance(author, dict):
                author_id = author.get("@pid")
            normalized.append(
                {
                    "display_name": self._string(author),
                    "id": author_id,
                    "position": index,
                }
            )
        return normalized

    def _as_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    def _string(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, dict):
            if "#text" in value:
                return self._string(value.get("#text"))
            if "text" in value:
                return self._string(value.get("text"))
            if "@text" in value:
                return self._string(value.get("@text"))
            return None
        if isinstance(value, list):
            parts = [item for item in (self._string(item) for item in value) if item]
            return ", ".join(parts) if parts else None
        text = str(value).strip()
        return text or None

    def _first_url(self, value: Any) -> str | None:
        if isinstance(value, list):
            for item in value:
                url = self._first_url(item)
                if url:
                    return url
            return None
        if isinstance(value, dict):
            return self._string(value.get("#text") or value.get("text") or value.get("url"))
        return self._string(value)

    def _doi_url(self, doi: str | None) -> str | None:
        if not doi:
            return None
        if doi.startswith("http://") or doi.startswith("https://"):
            return doi
        return f"https://doi.org/{doi}"

    def _int_or_zero(self, value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0


class DblpAPIProvider:
    """Provider backed by a DBLP publication-search spider."""

    name = "dblp"

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_DBLP_PUBLICATION_API,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
        spider: DblpPublicationSearchSpider | None = None,
    ) -> None:
        self.spider = spider or DblpPublicationSearchSpider(base_url=base_url, timeout=timeout, client=client)

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
