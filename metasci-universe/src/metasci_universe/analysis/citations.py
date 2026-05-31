"""Citation overview analysis for works datasets."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from metasci_universe.analysis import _normalize as norm
from metasci_universe.analysis._artifacts import save_analysis_artifacts
from metasci_universe.analysis._dataset import load_records
from metasci_universe.analysis._viz import bar, line
from metasci_universe.schemas.analysis import CitationOverviewRequest
from metasci_universe.schemas.common import MetaSciResult


async def citation_overview(
    dataset_path: str,
    *,
    top_papers: int = 30,
    top_references: int = 100,
    include_reference_frequency: bool = True,
    include_temporal: bool = True,
    year_field: str = "publication_year",
    output_dir: str | None = None,
) -> MetaSciResult:
    """Analyze citation counts and referenced-work frequency."""
    request = CitationOverviewRequest(
        dataset_path=dataset_path,
        top_papers=top_papers,
        top_references=top_references,
        include_reference_frequency=include_reference_frequency,
        include_temporal=include_temporal,
        year_field=year_field,
        output_dir=output_dir,
    )
    records, dataset_metadata, resolved_path = load_records(request.dataset_path)
    data, diagnostics = _compute_citation_overview(records, request)
    input_payload = request.model_dump(mode="json")
    artifacts = save_analysis_artifacts(
        command="analysis.citation_overview",
        input_payload=input_payload,
        data=data,
        summary_markdown=_summary_markdown(data, resolved_path=resolved_path, diagnostics=diagnostics),
        tables={
            "top_cited_papers": data["top_cited_papers"],
            "citation_by_year": data["citation_by_year"],
            "top_references": data["top_references"],
        },
        figures={
            "top_cited_papers": bar(
                list(reversed(data["top_cited_papers"][:20])),
                x="cited_by_count",
                y="title",
                title="Top Cited Papers",
                orientation="h",
            ),
            "citation_by_year": line(
                data["citation_by_year"],
                x="year",
                y="avg_citations",
                title="Average Citations by Publication Year",
            ),
        },
        output_dir=request.output_dir,
        diagnostics=diagnostics,
    )
    return MetaSciResult(
        command="analysis.citation_overview",
        input=input_payload,
        data=data,
        artifacts=artifacts,
        metadata={
            "record_count": len(records),
            "dataset_path": resolved_path,
            "dataset_schema": dataset_metadata.get("schema_name"),
        },
        diagnostics=diagnostics,
    )


def _compute_citation_overview(
    works: list[dict[str, Any]],
    request: CitationOverviewRequest,
) -> tuple[dict[str, Any], list[str]]:
    diagnostics: list[str] = []
    citation_counts = [norm.citations(work) for work in works]
    sorted_works = sorted(works, key=norm.citations, reverse=True)
    top_papers = [
        {
            "rank": rank,
            "id": norm.work_id(work),
            "title": norm.title(work),
            "year": norm.year(work, request.year_field),
            "source": norm.source(work).get("name") or "",
            "cited_by_count": norm.citations(work),
            "doi": work.get("doi") or "",
        }
        for rank, work in enumerate(sorted_works[: request.top_papers], start=1)
    ]

    year_stats: dict[int, dict[str, Any]] = defaultdict(lambda: {"n_papers": 0, "total_citations": 0})
    for work in works:
        publication_year = norm.year(work, request.year_field)
        if publication_year is None:
            continue
        year_stats[publication_year]["n_papers"] += 1
        year_stats[publication_year]["total_citations"] += norm.citations(work)

    citation_by_year = [
        {
            "year": year,
            "n_papers": stats["n_papers"],
            "total_citations": stats["total_citations"],
            "avg_citations": round(stats["total_citations"] / stats["n_papers"], 3) if stats["n_papers"] else 0,
        }
        for year, stats in sorted(year_stats.items())
    ]

    reference_counter: Counter[str] = Counter()
    records_with_references = 0
    if request.include_reference_frequency:
        for work in works:
            references = norm.referenced_works(work)
            if references:
                records_with_references += 1
                reference_counter.update(references)
        if records_with_references == 0:
            diagnostics.append(
                "No referenced_works data found. Re-run works.search with include=['references'] for reference frequency."
            )

    top_references = [
        {"rank": rank, "referenced_work": reference, "frequency": count}
        for rank, (reference, count) in enumerate(reference_counter.most_common(request.top_references), start=1)
    ]

    zero_citation_count = sum(1 for count in citation_counts if count == 0)
    return (
        {
            "overview": {
                "total_papers": len(works),
                "total_citations": sum(citation_counts),
                "avg_citations": round(sum(citation_counts) / len(citation_counts), 3) if citation_counts else 0,
                "max_citations": max(citation_counts) if citation_counts else 0,
                "zero_citation_count": zero_citation_count,
                "zero_citation_share": round(zero_citation_count / len(citation_counts) * 100, 3) if citation_counts else 0,
                "records_with_references": records_with_references,
            },
            "top_cited_papers": top_papers,
            "citation_by_year": citation_by_year,
            "top_references": top_references,
        },
        diagnostics,
    )


def _summary_markdown(data: dict[str, Any], *, resolved_path: str, diagnostics: list[str]) -> str:
    lines = [
        "# Citation Overview",
        "",
        f"Dataset: `{resolved_path}`",
        "",
        f"- Papers: {data['overview']['total_papers']}",
        f"- Total citations: {data['overview']['total_citations']}",
        f"- Average citations: {data['overview']['avg_citations']}",
        f"- Zero-citation share: {data['overview']['zero_citation_share']}%",
    ]
    if diagnostics:
        lines.extend(["", "## Diagnostics"])
        lines.extend(f"- {item}" for item in diagnostics)
    lines.extend(["", "## Top Cited Papers"])
    for row in data["top_cited_papers"][:10]:
        lines.append(f"- {row['cited_by_count']} citations: {row['title']} ({row['year']})")
    return "\n".join(lines)
