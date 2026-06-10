"""Small Semantic Scholar Graph API client for citation lookup."""

from __future__ import annotations

import os
from typing import Any

import httpx
from dotenv import load_dotenv


DEFAULT_BASE_URL = "https://api.semanticscholar.org/graph/v1"


class SemanticScholarPartialError(RuntimeError):
    """Raised when a paged S2 lookup fails after returning partial records."""

    def __init__(self, message: str, *, records: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.records = records


class SemanticScholarAPIProvider:
    """Provider backed by the public Semantic Scholar Graph API."""

    name = "semantic_scholar"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        load_dotenv()
        self.api_key = api_key or os.getenv("S2_API_KEY") or os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client

    async def get_paper(self, identifier: str) -> dict[str, Any]:
        return await self._get_json(f"/paper/{self._paper_identifier(identifier)}", params={"fields": self._fields()})

    async def search_paper(self, title: str, *, limit: int = 3) -> list[dict[str, Any]]:
        payload = await self._get_json(
            "/paper/search",
            params={
                "query": title,
                "limit": min(limit, 10),
                "fields": self._fields(),
            },
        )
        return payload.get("data") or []

    async def references(self, paper_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        return await self._paged_edge_lookup(paper_id, "references", "citedPaper", limit=limit)

    async def citations(self, paper_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        return await self._paged_edge_lookup(paper_id, "citations", "citingPaper", limit=limit)

    async def _paged_edge_lookup(self, paper_id: str, edge: str, item_key: str, *, limit: int) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        offset = 0
        while len(records) < limit:
            batch_size = min(100, limit - len(records))
            try:
                payload = await self._get_json(
                    f"/paper/{self._paper_identifier(paper_id)}/{edge}",
                    params={"fields": self._fields(), "limit": batch_size, "offset": offset},
                )
            except httpx.HTTPError as exc:
                if records:
                    raise SemanticScholarPartialError(
                        f"S2 {edge} lookup stopped after {len(records)} records: {exc}",
                        records=records,
                    ) from exc
                raise
            items = payload.get("data") or []
            if not items:
                break
            for item in items:
                paper = item.get(item_key) or item
                if paper:
                    records.append(paper)
            offset += len(items)
            if len(items) < batch_size:
                break
        return records[:limit]

    async def _get_json(self, endpoint: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {"x-api-key": self.api_key} if self.api_key else None

        if self._client is not None:
            response = await self._client.get(url, params=params or {}, headers=headers)
            response.raise_for_status()
            return response.json()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params or {}, headers=headers)
            response.raise_for_status()
            return response.json()

    def _paper_identifier(self, identifier: str) -> str:
        value = identifier.strip()
        if value.startswith("CorpusId:"):
            return value
        if value.isdigit():
            return f"CorpusId:{value}"
        if value.lower().startswith("arxiv:"):
            return f"ARXIV:{value.split(':', 1)[1]}"
        if value.lower().startswith("arxiv/"):
            return f"ARXIV:{value.split('/', 1)[1]}"
        if value.startswith("10."):
            return f"DOI:{value}"
        if "doi.org/" in value:
            return f"DOI:{value.rsplit('doi.org/', 1)[1]}"
        return value

    def _fields(self) -> str:
        return ",".join(
            [
                "paperId",
                "corpusId",
                "title",
                "abstract",
                "year",
                "authors",
                "venue",
                "url",
                "externalIds",
                "fieldsOfStudy",
                "citationCount",
                "referenceCount",
                "influentialCitationCount",
            ]
        )
