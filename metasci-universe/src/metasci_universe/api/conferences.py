"""Public conference-paper API."""

from __future__ import annotations

from metasci_universe.api._providers import get_conference_provider
from metasci_universe.schemas.common import MetaSciResult
from metasci_universe.schemas.conferences import ConferencePapersRequest
from metasci_universe.storage.output_writer import OutputWriter


async def papers(
    venue: str,
    *,
    year: int,
    source: str = "auto",
    status: str = "accepted",
    openreview_venue_id: str | None = None,
    source_collection_id: str | None = None,
    query: str | None = None,
    limit: int = 100,
    include_raw: bool = False,
    output_dir: str | None = None,
) -> MetaSciResult:
    """Retrieve accepted papers from a conference/year entry point."""
    request = ConferencePapersRequest(
        venue=venue,
        year=year,
        source=source,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        openreview_venue_id=openreview_venue_id,
        source_collection_id=source_collection_id,
        query=query,
        limit=limit,
        include_raw=include_raw,
        output_dir=output_dir,
    )
    selected_provider = get_conference_provider(request)
    provider_result = await selected_provider.search_conference_papers(request)
    input_payload = request.model_dump(mode="json")

    artifacts = OutputWriter(request.output_dir).save_dataset(
        kind="works",
        command="conferences.papers",
        input_payload=input_payload,
        records=provider_result.data,
        metadata=provider_result.metadata,
        diagnostics=provider_result.diagnostics,
    )

    return MetaSciResult(
        command="conferences.papers",
        input=input_payload,
        data=provider_result.data,
        artifacts=artifacts,
        metadata=provider_result.metadata,
        diagnostics=provider_result.diagnostics,
    )
