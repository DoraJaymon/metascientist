"""HTTP client provider for private MetaSci services."""

from __future__ import annotations

import os
from typing import Any

import httpx
from dotenv import load_dotenv

from metasci_universe.providers.base import ProviderResult
from metasci_universe.schemas.authors import AuthorProfileRequest, AuthorSearchRequest, WorkAuthorsRequest
from metasci_universe.schemas.works import WorksGetRequest, WorksSearchRequest


DEFAULT_ENV_ENDPOINT = "METASCI_SERVICE_ENDPOINT"
DEFAULT_ENV_TOKEN = "METASCI_SERVICE_TOKEN"


class ServiceProvider:
    """Provider backed by a private MetaSci HTTP service.

    The public package intentionally speaks HTTP here instead of importing DB
    clients or private query code. Private deployments can implement the same
    endpoints with OpenAlex mirrors, fact tables, and online computation.
    """

    name = "service"

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        token: str | None = None,
        timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        load_dotenv()
        self.endpoint = (endpoint or os.getenv(DEFAULT_ENV_ENDPOINT) or "").rstrip("/")
        self.token = token if token is not None else os.getenv(DEFAULT_ENV_TOKEN)
        self.timeout = timeout
        self._client = client
        if not self.endpoint:
            raise ValueError(
                "Service provider requires an endpoint. Set METASCI_SERVICE_ENDPOINT "
                "or pass endpoint=... when constructing ServiceProvider."
            )

    async def search_works(self, request: WorksSearchRequest) -> ProviderResult:
        payload = request.model_dump(mode="json")
        response = await self._post("/v1/works/search", payload)
        return self._provider_result(response, default_provider=self.name)

    async def get_work(self, request: WorksGetRequest) -> ProviderResult:
        response = await self._post("/v1/works/get", request.model_dump(mode="json"))
        return self._provider_result(response, default_provider=self.name)

    async def search_authors(self, request: AuthorSearchRequest) -> ProviderResult:
        response = await self._post("/v1/authors/search", request.model_dump(mode="json"))
        return self._provider_result(response, default_provider=self.name)

    async def get_author(self, request: AuthorProfileRequest) -> ProviderResult:
        response = await self._post("/v1/authors/profile", request.model_dump(mode="json"))
        return self._provider_result(response, default_provider=self.name)

    async def authors_from_work(self, request: WorkAuthorsRequest) -> ProviderResult:
        response = await self._post("/v1/authors/from-work", request.model_dump(mode="json"))
        return self._provider_result(response, default_provider=self.name)

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.endpoint}/{path.lstrip('/')}"
        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        if self._client is not None:
            response = await self._client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()

    def _provider_result(self, payload: dict[str, Any], *, default_provider: str) -> ProviderResult:
        data = payload.get("data", payload.get("result"))
        metadata = dict(payload.get("metadata") or {})
        diagnostics = list(payload.get("diagnostics") or [])
        metadata.setdefault("provider", default_provider)
        return ProviderResult(data=data, metadata=metadata, diagnostics=diagnostics)
