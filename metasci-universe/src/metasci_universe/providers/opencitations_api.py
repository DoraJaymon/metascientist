"""Small OpenCitations REST API client for citation lookup."""

from __future__ import annotations

from typing import Any

import httpx


DEFAULT_INDEX_BASE_URL = "https://api.opencitations.net/index/v2"
DEFAULT_META_BASE_URL = "https://api.opencitations.net/meta/v1"


class OpenCitationsAPIProvider:
    """Provider backed by the public OpenCitations Index and Meta APIs."""

    name = "opencitations"

    def __init__(
        self,
        *,
        index_base_url: str = DEFAULT_INDEX_BASE_URL,
        meta_base_url: str = DEFAULT_META_BASE_URL,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.index_base_url = index_base_url.rstrip("/")
        self.meta_base_url = meta_base_url.rstrip("/")
        self.timeout = timeout
        self._client = client

    async def references(self, identifier: str) -> list[dict[str, Any]]:
        payload = await self._get_json(f"/references/{identifier}", base_url=self.index_base_url)
        return payload if isinstance(payload, list) else []

    async def citations(self, identifier: str) -> list[dict[str, Any]]:
        payload = await self._get_json(f"/citations/{identifier}", base_url=self.index_base_url)
        return payload if isinstance(payload, list) else []

    async def reference_count(self, identifier: str) -> int | None:
        return self._count(await self._get_json(f"/reference-count/{identifier}", base_url=self.index_base_url))

    async def citation_count(self, identifier: str) -> int | None:
        return self._count(await self._get_json(f"/citation-count/{identifier}", base_url=self.index_base_url))

    async def metadata(self, identifiers: list[str]) -> list[dict[str, Any]]:
        if not identifiers:
            return []
        payload = await self._get_json(f"/metadata/{'__'.join(identifiers)}", base_url=self.meta_base_url)
        return payload if isinstance(payload, list) else []

    async def _get_json(self, endpoint: str, *, base_url: str) -> Any:
        url = f"{base_url}/{endpoint.lstrip('/')}"

        if self._client is not None:
            response = await self._client.get(url)
            response.raise_for_status()
            return response.json()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()

    def _count(self, payload: Any) -> int | None:
        if not isinstance(payload, list) or not payload:
            return None
        raw = payload[0].get("count") if isinstance(payload[0], dict) else None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
