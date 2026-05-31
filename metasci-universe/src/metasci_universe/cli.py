"""MetaSci command line interface."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import click

from metasci_universe.tools.registry import describe_tool, list_tools, run_tool, tool_schema
from metasci_universe.schemas.common import MetaSciResult
from metasci_universe.storage.saved_dataset import SavedDataset
from metasci_universe.api._providers import get_provider


def _run(coro):
    return asyncio.run(coro)


def _emit_result(result: MetaSciResult, *, as_json: bool, output_path: Path | None = None) -> None:
    if output_path is not None:
        result.to_json(output_path)

    if as_json:
        click.echo(result.to_json())
        return

    click.echo(result.summary())

    data = result.data
    preview = data[:5] if isinstance(data, list) else data
    if preview:
        click.echo("")
        click.echo("Preview:")
        click.echo(json.dumps(preview, ensure_ascii=False, indent=2))


@click.group()
def main() -> None:
    """MetaSci Universe data acquisition CLI."""


@main.group()
def works() -> None:
    """Work retrieval commands."""


@works.command("search")
@click.argument("query", required=False)
@click.option("--topic-name")
@click.option("--source-name")
@click.option("--author-name")
@click.option("--institution-name")
@click.option("--topic-id")
@click.option("--source-id")
@click.option("--author-id")
@click.option("--institution-id")
@click.option("--from-year", type=int)
@click.option("--to-year", type=int)
@click.option("--country-code")
@click.option("--work-type", default="article", show_default=True)
@click.option("--any-work-type", is_flag=True, help="Do not apply the default OpenAlex type:article filter.")
@click.option("--is-oa/--not-oa", default=None)
@click.option("--min-cited-by-count", type=int)
@click.option("--max-cited-by-count", type=int)
@click.option("--limit", type=int, default=100, show_default=True)
@click.option(
    "--sort-by",
    type=click.Choice(
        [
            "cited_by_count:desc",
            "publication_date:desc",
            "publication_year:desc",
            "publication_year:asc",
            "relevance_score:desc",
        ]
    ),
    default="cited_by_count:desc",
    show_default=True,
)
@click.option("--include", multiple=True, type=click.Choice(["authors", "references"]))
@click.option("--include-raw", multiple=True)
@click.option("--provider", type=click.Choice(["auto", "openalex", "service"]), default="auto", show_default=True)
@click.option("--service-endpoint")
@click.option("--service-token")
@click.option("--output-dir", type=click.Path(file_okay=False, path_type=Path))
@click.option("--output", "output_path", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def works_search_cmd(
    query: str | None,
    topic_name: str | None,
    source_name: str | None,
    author_name: str | None,
    institution_name: str | None,
    topic_id: str | None,
    source_id: str | None,
    author_id: str | None,
    institution_id: str | None,
    from_year: int | None,
    to_year: int | None,
    country_code: str | None,
    work_type: str | None,
    any_work_type: bool,
    is_oa: bool | None,
    min_cited_by_count: int | None,
    max_cited_by_count: int | None,
    limit: int,
    sort_by: str,
    include: tuple[str, ...],
    include_raw: tuple[str, ...],
    provider: str,
    service_endpoint: str | None,
    service_token: str | None,
    output_dir: Path | None,
    output_path: Path | None,
    as_json: bool,
) -> None:
    """Search works and save a dataset artifact."""
    from metasci_universe.api import works as works_api

    try:
        result = _run(
            works_api.search(
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
                work_type=None if any_work_type else work_type,
                is_oa=is_oa,
                min_cited_by_count=min_cited_by_count,
                max_cited_by_count=max_cited_by_count,
                limit=limit,
                sort_by=sort_by,
                include=list(include),
                include_raw=list(include_raw),
                provider=provider,
                service_endpoint=service_endpoint,
                service_token=service_token,
                output_dir=str(output_dir) if output_dir else None,
            )
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    _emit_result(result, as_json=as_json, output_path=output_path)


@works.command("get")
@click.argument("identifier")
@click.option("--provider", type=click.Choice(["auto", "openalex", "service"]), default="auto", show_default=True)
@click.option("--service-endpoint")
@click.option("--service-token")
@click.option("--output-dir", type=click.Path(file_okay=False, path_type=Path))
@click.option("--output", "output_path", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def works_get_cmd(identifier: str, provider: str, output_dir: Path | None, output_path: Path | None, as_json: bool) -> None:
    """Get a single work."""
    from metasci_universe.api import works as works_api

    try:
        result = _run(works_api.get(identifier, provider=provider, output_dir=str(output_dir) if output_dir else None))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit_result(result, as_json=as_json, output_path=output_path)


@main.group()
def conferences() -> None:
    """Conference-paper retrieval commands."""


@conferences.command("papers")
@click.argument("venue")
@click.option("--year", type=int, required=True)
@click.option(
    "--source",
    type=click.Choice(["auto", "openreview", "dblp", "acl", "cvf", "pmlr"]),
    default="auto",
    show_default=True,
)
@click.option("--openreview-venue-id")
@click.option("--source-collection-id")
@click.option("--query")
@click.option("--limit", type=int, default=100, show_default=True)
@click.option("--include-raw", is_flag=True)
@click.option("--output-dir", type=click.Path(file_okay=False, path_type=Path))
@click.option("--output", "output_path", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def conferences_papers_cmd(
    venue: str,
    year: int,
    source: str,
    openreview_venue_id: str | None,
    source_collection_id: str | None,
    query: str | None,
    limit: int,
    include_raw: bool,
    output_dir: Path | None,
    output_path: Path | None,
    as_json: bool,
) -> None:
    """Retrieve accepted papers from a conference/year source."""
    from metasci_universe.api import conferences as conferences_api

    try:
        result = _run(
            conferences_api.papers(
                venue,
                year=year,
                source=source,
                openreview_venue_id=openreview_venue_id,
                source_collection_id=source_collection_id,
                query=query,
                limit=limit,
                include_raw=include_raw,
                output_dir=str(output_dir) if output_dir else None,
            )
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    _emit_result(result, as_json=as_json, output_path=output_path)


@main.group()
def authors() -> None:
    """Author lookup commands."""


@authors.command("search")
@click.argument("name")
@click.option("--limit", type=int, default=10, show_default=True)
@click.option("--detail-level", type=click.Choice(["summary", "full"]), default="summary", show_default=True)
@click.option("--provider", type=click.Choice(["auto", "openalex", "service"]), default="auto", show_default=True)
@click.option("--output-dir", type=click.Path(file_okay=False, path_type=Path))
@click.option("--output", "output_path", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def authors_search_cmd(
    name: str,
    limit: int,
    detail_level: str,
    provider: str,
    service_endpoint: str | None,
    service_token: str | None,
    output_dir: Path | None,
    output_path: Path | None,
    as_json: bool,
) -> None:
    """Search candidate authors by name."""
    from metasci_universe.api import authors as authors_api

    try:
        result = _run(
            authors_api.search(
                name,
                limit=limit,
                detail_level=detail_level,
                provider=provider,
                service_endpoint=service_endpoint,
                service_token=service_token,
                output_dir=str(output_dir) if output_dir else None,
            )
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit_result(result, as_json=as_json, output_path=output_path)


@authors.command("profile")
@click.argument("identifier")
@click.option("--detail-level", type=click.Choice(["summary", "full"]), default="full", show_default=True)
@click.option("--provider", type=click.Choice(["auto", "openalex", "service"]), default="auto", show_default=True)
@click.option("--service-endpoint")
@click.option("--service-token")
@click.option("--output-dir", type=click.Path(file_okay=False, path_type=Path))
@click.option("--output", "output_path", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def authors_profile_cmd(
    identifier: str,
    detail_level: str,
    provider: str,
    service_endpoint: str | None,
    service_token: str | None,
    output_dir: Path | None,
    output_path: Path | None,
    as_json: bool,
) -> None:
    """Get an author profile by OpenAlex author ID."""
    from metasci_universe.api import authors as authors_api

    try:
        result = _run(
            authors_api.profile(
                identifier,
                detail_level=detail_level,
                provider=provider,
                output_dir=str(output_dir) if output_dir else None,
            )
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit_result(result, as_json=as_json, output_path=output_path)


@authors.command("from-work")
@click.argument("identifier")
@click.option("--author-position", type=int, default=1, show_default=True)
@click.option("--all-authors", is_flag=True)
@click.option("--detail-level", type=click.Choice(["summary", "full"]), default="summary", show_default=True)
@click.option("--provider", type=click.Choice(["auto", "openalex", "service"]), default="auto", show_default=True)
@click.option("--output-dir", type=click.Path(file_okay=False, path_type=Path))
@click.option("--output", "output_path", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def authors_from_work_cmd(
    identifier: str,
    author_position: int,
    all_authors: bool,
    detail_level: str,
    provider: str,
    output_dir: Path | None,
    output_path: Path | None,
    as_json: bool,
) -> None:
    """Get authorship information from a DOI or OpenAlex work ID."""
    from metasci_universe.api import authors as authors_api

    try:
        result = _run(
            authors_api.from_work(
                identifier,
                author_position=author_position,
                all_authors=all_authors,
                detail_level=detail_level,
                provider=provider,
                service_endpoint=service_endpoint,
                service_token=service_token,
                output_dir=str(output_dir) if output_dir else None,
            )
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit_result(result, as_json=as_json, output_path=output_path)


@main.group()
def dataset() -> None:
    """Saved dataset output commands."""


@dataset.command("info")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def dataset_info_cmd(path: Path, as_json: bool) -> None:
    """Inspect a saved dataset artifact."""
    try:
        info = SavedDataset.load(path).info()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        click.echo(json.dumps(info, ensure_ascii=False, indent=2))
        return

    click.echo(f"Path: {info['path']}")
    click.echo(f"Schema: {info['schema_name']}")
    click.echo(f"Records: {info['record_count']}")


@main.group()
def tools() -> None:
    """Agent tool discovery commands."""


@tools.command("list")
@click.option("--json", "as_json", is_flag=True)
def tools_list_cmd(as_json: bool) -> None:
    names = list_tools()
    if as_json:
        click.echo(json.dumps(names, ensure_ascii=False, indent=2))
        return
    for name in names:
        click.echo(name)


@tools.command("describe")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True)
def tools_describe_cmd(name: str, as_json: bool) -> None:
    try:
        card = describe_tool(name)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        click.echo(json.dumps(card, ensure_ascii=False, indent=2))
        return

    click.echo(f"{card['name']}: {card['description']}")
    click.echo(json.dumps(card["inputs"], ensure_ascii=False, indent=2))


@tools.command("schema")
@click.argument("name")
def tools_schema_cmd(name: str) -> None:
    try:
        schema = tool_schema(name)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(schema, ensure_ascii=False, indent=2))


@tools.command("run")
@click.argument("name")
@click.argument("arguments_json")
@click.option("--json", "as_json", is_flag=True)
def tools_run_cmd(name: str, arguments_json: str, as_json: bool) -> None:
    """Run a registered tool from a JSON argument object."""
    try:
        arguments: dict[str, Any] = json.loads(arguments_json)
        result = _run(run_tool(name, arguments))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit_result(result, as_json=as_json)


if __name__ == "__main__":
    main()
