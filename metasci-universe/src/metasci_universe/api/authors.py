"""Public author APIs."""

from __future__ import annotations

from typing import Any

from metasci_universe.schemas.authors import AuthorProfileRequest, AuthorSearchRequest, WorkAuthorsRequest
from metasci_universe.schemas.common import MetaSciResult
from metasci_universe.api._providers import get_provider
from metasci_universe.storage.output_writer import OutputWriter


async def search(
    name: str,
    *,
    limit: int = 10,
    detail_level: str = "summary",
    provider: str = "auto",
    service_endpoint: str | None = None,
    service_token: str | None = None,
    output_dir: str | None = None,
) -> MetaSciResult:
    """Search candidate authors by name."""
    request = AuthorSearchRequest(
        name=name,
        limit=limit,
        detail_level=detail_level,  # type: ignore[arg-type]
        provider=provider,  # type: ignore[arg-type]
        output_dir=output_dir,
    )
    selected_provider = get_provider(request.provider, service_endpoint=service_endpoint, service_token=service_token)
    provider_result = await selected_provider.search_authors(request)
    input_payload = request.model_dump(mode="json")
    artifacts = OutputWriter(request.output_dir).save_dataset(
        kind="authors",
        command="authors.search",
        input_payload=input_payload,
        records=provider_result.data,
        metadata=provider_result.metadata,
        diagnostics=provider_result.diagnostics,
    )
    return MetaSciResult(
        command="authors.search",
        input=input_payload,
        data=provider_result.data,
        artifacts=artifacts,
        metadata=provider_result.metadata,
        diagnostics=provider_result.diagnostics,
    )


async def profile(
    identifier: str,
    *,
    detail_level: str = "full",
    provider: str = "auto",
    service_endpoint: str | None = None,
    service_token: str | None = None,
    output_dir: str | None = None,
) -> MetaSciResult:
    """Get a single author profile by OpenAlex author ID."""
    request = AuthorProfileRequest(
        identifier=identifier,
        detail_level=detail_level,  # type: ignore[arg-type]
        provider=provider,  # type: ignore[arg-type]
        output_dir=output_dir,
    )
    selected_provider = get_provider(request.provider, service_endpoint=service_endpoint, service_token=service_token)
    provider_result = await selected_provider.get_author(request)
    input_payload = request.model_dump(mode="json")
    artifacts = OutputWriter(request.output_dir).save_dataset(
        kind="author",
        command="authors.profile",
        input_payload=input_payload,
        records=provider_result.data,
        metadata=provider_result.metadata,
        diagnostics=provider_result.diagnostics,
    )
    return MetaSciResult(
        command="authors.profile",
        input=input_payload,
        data=provider_result.data,
        artifacts=artifacts,
        metadata=provider_result.metadata,
        diagnostics=provider_result.diagnostics,
    )


async def from_work(
    identifier: str,
    *,
    author_position: int = 1,
    all_authors: bool = False,
    detail_level: str = "summary",
    provider: str = "auto",
    service_endpoint: str | None = None,
    service_token: str | None = None,
    output_dir: str | None = None,
) -> MetaSciResult:
    """Get author information from a DOI or OpenAlex work ID."""
    request = WorkAuthorsRequest(
        identifier=identifier,
        author_position=author_position,
        all_authors=all_authors,
        detail_level=detail_level,  # type: ignore[arg-type]
        provider=provider,  # type: ignore[arg-type]
        output_dir=output_dir,
    )
    selected_provider = get_provider(request.provider, service_endpoint=service_endpoint, service_token=service_token)
    provider_result = await selected_provider.authors_from_work(request)
    input_payload = request.model_dump(mode="json")
    artifacts = OutputWriter(request.output_dir).save_dataset(
        kind="authors",
        command="authors.from_work",
        input_payload=input_payload,
        records=provider_result.data,
        metadata=provider_result.metadata,
        diagnostics=provider_result.diagnostics,
    )
    return MetaSciResult(
        command="authors.from_work",
        input=input_payload,
        data=provider_result.data,
        artifacts=artifacts,
        metadata=provider_result.metadata,
        diagnostics=provider_result.diagnostics,
    )


async def run_search_from_dict(payload: dict[str, Any]) -> MetaSciResult:
    return await search(**payload)
