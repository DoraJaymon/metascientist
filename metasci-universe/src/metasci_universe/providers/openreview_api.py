"""OpenReview provider and spider for conference-paper entry points."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from metasci_universe.providers.base import ProviderResult
from metasci_universe.providers.conference_spiders import ConferenceCrawlResult
from metasci_universe.schemas.conferences import ConferencePapersRequest


DEFAULT_API2_BASE_URL = "https://api2.openreview.net"
OPENREVIEW_WEB_BASE_URL = "https://openreview.net"

OPENREVIEW_VENUE_PATTERNS = {
    "iclr": "ICLR.cc/{year}/Conference",
    "neurips": "NeurIPS.cc/{year}/Conference",
    "nips": "NeurIPS.cc/{year}/Conference",
    "icml": "ICML.cc/{year}/Conference",
}


class OpenReviewAcceptedPaperSpider:
    """Spider for OpenReview accepted/camera-ready notes."""

    source = "openreview"
    name = "openreview-api-v2-notes"

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_API2_BASE_URL,
        web_base_url: str = OPENREVIEW_WEB_BASE_URL,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.web_base_url = web_base_url.rstrip("/")
        self.timeout = timeout
        self._client = client

    async def crawl(self, request: ConferencePapersRequest) -> ConferenceCrawlResult:
        venue_id = request.openreview_venue_id or self.openreview_venue_id(request.venue, request.year)
        if not venue_id:
            raise ValueError(
                f"No OpenReview venue id is known for venue={request.venue!r}, year={request.year}. "
                "Pass openreview_venue_id explicitly or use source='dblp'."
            )

        notes, total = await self._fetch_notes(venue_id=venue_id, request=request)
        records = [self._normalize_note(note, request=request, venue_id=venue_id) for note in notes]

        diagnostics: list[str] = []
        if request.limit < total:
            diagnostics.append(f"Returned first {request.limit} OpenReview records out of {total}.")

        return ConferenceCrawlResult(
            records=records,
            total=total,
            metadata={
                "source": self.source,
                "spider": self.name,
                "venue_id": venue_id,
            },
            diagnostics=diagnostics,
        )

    def openreview_venue_id(self, venue: str, year: int) -> str | None:
        pattern = OPENREVIEW_VENUE_PATTERNS.get(venue)
        if pattern is None:
            return None
        return pattern.format(year=year)

    async def _fetch_notes(self, *, venue_id: str, request: ConferencePapersRequest) -> tuple[list[dict[str, Any]], int]:
        notes: list[dict[str, Any]] = []
        total = 0
        offset = 0

        while len(notes) < request.limit:
            page_limit = min(100, request.limit - len(notes))
            params: dict[str, Any] = {
                "limit": page_limit,
                "offset": offset,
            }
            endpoint = "/notes"
            if request.query:
                endpoint = "/notes/search"
                params["venueid"] = venue_id
                params["source"] = "forum"
                params["query"] = request.query
            else:
                params["content.venueid"] = venue_id

            payload = await self._get_json(endpoint, params=params)
            page_notes = payload.get("notes") or []
            total = self._int_or_zero(payload.get("count"))
            if not page_notes:
                break

            notes.extend(page_notes)
            offset += len(page_notes)
            if len(page_notes) < page_limit:
                break

        return notes[: request.limit], total or len(notes)

    async def _get_json(self, endpoint: str, *, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        if self._client is not None:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            return response.json()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    def _normalize_note(
        self,
        note: dict[str, Any],
        *,
        request: ConferencePapersRequest,
        venue_id: str,
    ) -> dict[str, Any]:
        content = note.get("content") or {}
        note_id = str(note.get("id") or "")
        authors = self._content_value(content, "authors") or []
        authorids = self._content_value(content, "authorids") or []
        title = self._content_value(content, "title")
        venue_label = self._content_value(content, "venue") or f"{request.venue.upper()} {request.year}"
        pdf_url = self._pdf_url(note_id, self._content_value(content, "pdf"))
        landing_url = f"{self.web_base_url}/forum?id={note_id}" if note_id else None

        record = {
            "id": f"openreview:{note_id}" if note_id else None,
            "source_record_id": note_id or None,
            "title": title,
            "publication_year": request.year,
            "publication_date": self._epoch_millis_to_date(note.get("pdate") or note.get("cdate")),
            "type": "conference-paper",
            "abstract": self._content_value(content, "abstract"),
            "authors": self._normalize_authors(authors, authorids),
            "doi": None,
            "pdf_url": pdf_url,
            "landing_url": landing_url,
            "source": {
                "id": venue_id,
                "name": venue_label,
                "type": "conference",
                "acronym": request.venue.upper(),
                "year": request.year,
            },
            "external_ids": {
                "openreview": note_id or None,
            },
            "openreview": {
                "venue_id": venue_id,
                "number": note.get("number"),
                "forum": note.get("forum"),
                "invitation": note.get("invitation") or self._first_item(note.get("invitations")),
                "venue": venue_label,
                "presentation_type": self._content_value(content, "presentation_type"),
                "keywords": self._content_value(content, "keywords"),
                "tl_dr": (
                    self._content_value(content, "TL;DR")
                    or self._content_value(content, "TLDR")
                    or self._content_value(content, "tl_dr")
                ),
            },
            "provenance": [
                {
                    "source": self.source,
                    "spider": self.name,
                    "record_id": note_id or None,
                    "url": landing_url,
                    "retrieval_key": venue_id,
                }
            ],
        }
        if request.include_raw:
            record["_raw"] = note
        return record

    def _normalize_authors(self, authors: Any, authorids: Any) -> list[dict[str, Any]]:
        author_names = self._as_list(authors)
        author_ids = self._as_list(authorids)
        normalized: list[dict[str, Any]] = []
        for index, name in enumerate(author_names, start=1):
            normalized.append(
                {
                    "display_name": str(name),
                    "id": str(author_ids[index - 1]) if index - 1 < len(author_ids) else None,
                    "position": index,
                }
            )
        return normalized

    def _content_value(self, content: dict[str, Any], key: str) -> Any:
        raw = content.get(key)
        if isinstance(raw, dict) and "value" in raw:
            return raw.get("value")
        return raw

    def _as_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    def _first_item(self, value: Any) -> Any:
        items = self._as_list(value)
        return items[0] if items else None

    def _pdf_url(self, note_id: str, pdf_value: Any) -> str | None:
        if isinstance(pdf_value, str) and pdf_value:
            if pdf_value.startswith("http://") or pdf_value.startswith("https://"):
                return pdf_value
            if pdf_value.startswith("/"):
                return f"{self.web_base_url}{pdf_value}"
        if note_id:
            return f"{self.web_base_url}/pdf?id={note_id}"
        return None

    def _epoch_millis_to_date(self, value: Any) -> str | None:
        if value is None:
            return None
        try:
            return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).date().isoformat()
        except (TypeError, ValueError, OSError):
            return None

    def _int_or_zero(self, value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0


class OpenReviewAPIProvider:
    """Provider backed by an OpenReview accepted-paper spider."""

    name = "openreview"

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_API2_BASE_URL,
        web_base_url: str = OPENREVIEW_WEB_BASE_URL,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
        spider: OpenReviewAcceptedPaperSpider | None = None,
    ) -> None:
        self.spider = spider or OpenReviewAcceptedPaperSpider(
            base_url=base_url,
            web_base_url=web_base_url,
            timeout=timeout,
            client=client,
        )

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

    def openreview_venue_id(self, venue: str, year: int) -> str | None:
        return self.spider.openreview_venue_id(venue, year)
