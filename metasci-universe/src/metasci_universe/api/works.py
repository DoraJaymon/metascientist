"""Public works API."""

from __future__ import annotations

from typing import Any

from metasci_universe.schemas.common import MetaSciResult
from metasci_universe.schemas.works import WorksFullTextRequest, WorksGetRequest, WorksSearchRequest
from metasci_universe.api._providers import get_provider
from metasci_universe.storage.output_writer import OutputWriter


async def search(
    query: str | None = None,
    *,
    topic_name: str | None = None,
    source_name: str | None = None,
    author_name: str | None = None,
    institution_name: str | None = None,
    topic_id: str | None = None,
    source_id: str | None = None,
    author_id: str | None = None,
    institution_id: str | None = None,
    from_year: int | None = None,
    to_year: int | None = None,
    country_code: str | None = None,
    work_type: str | None = "article",
    is_oa: bool | None = None,
    min_cited_by_count: int | None = None,
    max_cited_by_count: int | None = None,
    limit: int = 100,
    sort_by: str = "cited_by_count:desc",
    include: list[str] | None = None,
    include_raw: list[str] | None = None,
    provider: str = "auto",
    service_endpoint: str | None = None,
    service_token: str | None = None,
    output_dir: str | None = None,
) -> MetaSciResult:
    """Search scholarly works and save a reusable dataset artifact."""
    request = WorksSearchRequest(
        query=query,
        topic_name=topic_name,
        source_name=source_name,
        author_name=author_name,
        institution_name=institution_name,
        topic_id=topic_id,
        source_id=source_id,
        author_id=author_id,
        institution_id=institution_id,
        from_year=from_year,
        to_year=to_year,
        country_code=country_code,
        work_type=work_type,
        is_oa=is_oa,
        min_cited_by_count=min_cited_by_count,
        max_cited_by_count=max_cited_by_count,
        limit=limit,
        sort_by=sort_by,  # type: ignore[arg-type]
        include=include or [],
        include_raw=include_raw or [],
        provider=provider,  # type: ignore[arg-type]
        output_dir=output_dir,
    )
    selected_provider = get_provider(request.provider, service_endpoint=service_endpoint, service_token=service_token)
    provider_result = await selected_provider.search_works(request)
    input_payload = request.model_dump(mode="json")

    artifacts = OutputWriter(request.output_dir).save_dataset(
        kind="works",
        command="works.search",
        input_payload=input_payload,
        records=provider_result.data,
        metadata=provider_result.metadata,
        diagnostics=provider_result.diagnostics,
    )

    return MetaSciResult(
        command="works.search",
        input=input_payload,
        data=provider_result.data,
        artifacts=artifacts,
        metadata=provider_result.metadata,
        diagnostics=provider_result.diagnostics,
    )


async def get(
    identifier: str,
    *,
    provider: str = "auto",
    service_endpoint: str | None = None,
    service_token: str | None = None,
    output_dir: str | None = None,
) -> MetaSciResult:
    """Get one work by OpenAlex ID, DOI, PMID, or URL."""
    request = WorksGetRequest(identifier=identifier, provider=provider, output_dir=output_dir)  # type: ignore[arg-type]
    selected_provider = get_provider(request.provider, service_endpoint=service_endpoint, service_token=service_token)
    provider_result = await selected_provider.get_work(request)
    input_payload = request.model_dump(mode="json")

    artifacts = OutputWriter(request.output_dir).save_dataset(
        kind="work",
        command="works.get",
        input_payload=input_payload,
        records=provider_result.data,
        metadata=provider_result.metadata,
        diagnostics=provider_result.diagnostics,
    )

    return MetaSciResult(
        command="works.get",
        input=input_payload,
        data=provider_result.data,
        artifacts=artifacts,
        metadata=provider_result.metadata,
        diagnostics=provider_result.diagnostics,
    )


async def fulltext(
    identifier: str,
    *,
    provider: str = "sciencedirect",
    service_endpoint: str | None = None,
    service_token: str | None = None,
    output_dir: str | None = None,
    download_pdf: bool = False,
) -> MetaSciResult:
    """Fetch provider-supported full text and save it as a standalone artifact."""
    request = WorksFullTextRequest(
        identifier=identifier,
        provider=provider,  # type: ignore[arg-type]
        output_dir=output_dir,
        download_pdf=download_pdf,
    )
    selected_provider = get_provider(request.provider, service_endpoint=service_endpoint, service_token=service_token)
    if not hasattr(selected_provider, "get_fulltext"):
        raise ValueError(f"Provider {request.provider!r} does not support works.fulltext")

    provider_result = await selected_provider.get_fulltext(request)  # type: ignore[attr-defined]
    input_payload = request.model_dump(mode="json")
    result_artifacts: dict[str, str]
    result_data: dict[str, Any]

    if request.provider == "springer":
        if not isinstance(provider_result.data, dict):
            raise ValueError("Springer fulltext provider returned an invalid payload.")
        markdown = str(provider_result.data.get("markdown") or "")
        work = provider_result.data.get("work") or {}
        extra_files: dict[str, Any] = {"work.json": work}
        if provider_result.data.get("pdf_bytes") is not None:
            extra_files["article.pdf"] = provider_result.data["pdf_bytes"]
        artifacts = OutputWriter(request.output_dir).save_text_artifact(
            kind="fulltext",
            command="works.fulltext",
            input_payload=input_payload,
            filename="fulltext.md",
            content=markdown,
            metadata=provider_result.metadata,
            diagnostics=provider_result.diagnostics,
            extra_files=extra_files,
        )
        markdown_file = artifacts["text_file"]
        result_artifacts = {
            "artifact_dir": artifacts["artifact_dir"],
            "markdown_file": markdown_file,
            "work_file": artifacts["work_file"],
            "metadata_file": artifacts["metadata_file"],
        }
        if "pdf_file" in artifacts:
            result_artifacts["pdf_file"] = artifacts["pdf_file"]
        result_data = {
            "markdown_file": markdown_file,
            "work_file": artifacts["work_file"],
            "content_length": len(markdown),
        }
        if "pdf_file" in artifacts:
            result_data["pdf_file"] = artifacts["pdf_file"]
    else:
        diagnostics = list(provider_result.diagnostics)
        if request.download_pdf:
            diagnostics.append("download_pdf is only supported for provider='springer'; ignored for sciencedirect.")
        artifacts = OutputWriter(request.output_dir).save_text_artifact(
            kind="fulltext",
            command="works.fulltext",
            input_payload=input_payload,
            filename="fulltext.xml",
            content=str(provider_result.data),
            metadata=provider_result.metadata,
            diagnostics=diagnostics,
        )
        xml_file = artifacts["text_file"]
        result_artifacts = {
            "artifact_dir": artifacts["artifact_dir"],
            "xml_file": xml_file,
            "metadata_file": artifacts["metadata_file"],
        }
        result_data = {
            "xml_file": xml_file,
            "content_length": len(str(provider_result.data)),
        }

    return MetaSciResult(
        command="works.fulltext",
        input=input_payload,
        data=result_data,
        artifacts=result_artifacts,
        metadata=provider_result.metadata,
        diagnostics=provider_result.diagnostics if request.provider == "springer" else diagnostics,
    )


async def run_search_from_dict(payload: dict[str, Any]) -> MetaSciResult:
    """Execute works.search from a generic tool payload."""
    return await search(**payload)
