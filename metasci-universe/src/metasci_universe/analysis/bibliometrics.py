"""Bibliometric analysis for works datasets."""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median
from typing import Any

from metasci_universe.analysis import _normalize as norm
from metasci_universe.analysis._artifacts import save_analysis_artifacts
from metasci_universe.analysis._dataset import load_records
from metasci_universe.analysis._viz import bar, dual_axis_line_bar, line
from metasci_universe.schemas.analysis import BibliometricsRequest
from metasci_universe.schemas.common import MetaSciResult


async def bibliometrics(
    dataset_path: str,
    *,
    top_authors: int = 20,
    top_papers: int = 20,
    top_sources: int = 20,
    top_topics: int = 30,
    output_dir: str | None = None,
) -> MetaSciResult:
    """Run descriptive bibliometric analysis on a saved works dataset."""
    request = BibliometricsRequest(
        dataset_path=dataset_path,
        top_authors=top_authors,
        top_papers=top_papers,
        top_sources=top_sources,
        top_topics=top_topics,
        output_dir=output_dir,
    )
    records, dataset_metadata, resolved_path = load_records(request.dataset_path)
    data, diagnostics = _compute_bibliometrics(
        records,
        top_authors=request.top_authors,
        top_papers=request.top_papers,
        top_sources=request.top_sources,
        top_topics=request.top_topics,
    )
    input_payload = request.model_dump(mode="json")
    summary = _summary_markdown(data, resolved_path=resolved_path, diagnostics=diagnostics)
    artifacts = save_analysis_artifacts(
        command="analysis.bibliometrics",
        input_payload=input_payload,
        data=data,
        summary_markdown=summary,
        tables={
            "annual_production": data["annual_production"]["annual_data"],
            "annual_impact": data["annual_impact"]["annual_data"],
            "top_authors": data["most_productive_authors"]["authors"],
            "top_papers": data["most_cited_papers"]["papers"],
            "top_sources": data["most_relevant_sources"]["sources"],
            "top_topics": data["most_frequent_topics"]["topics"],
        },
        figures=_figures(data),
        output_dir=request.output_dir,
        diagnostics=diagnostics,
    )
    return MetaSciResult(
        command="analysis.bibliometrics",
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


def _compute_bibliometrics(
    works: list[dict[str, Any]],
    *,
    top_authors: int,
    top_papers: int,
    top_sources: int,
    top_topics: int,
) -> tuple[dict[str, Any], list[str]]:
    diagnostics: list[str] = []
    total_papers = len(works)
    citation_counts = [norm.citations(work) for work in works]
    total_citations = sum(citation_counts)

    year_stats: dict[int, dict[str, Any]] = defaultdict(lambda: {"n_papers": 0, "total_citations": 0})
    type_counts: Counter[str] = Counter()
    oa_count = 0
    for work in works:
        publication_year = norm.year(work)
        if publication_year is not None:
            year_stats[publication_year]["n_papers"] += 1
            year_stats[publication_year]["total_citations"] += norm.citations(work)
        work_type = work.get("type") or "unknown"
        type_counts[str(work_type)] += 1
        if work.get("is_oa") is True:
            oa_count += 1

    annual_data = _annual_impact_rows(year_stats)
    annual_growth_rate = _annual_growth_rate(annual_data)
    annual_diagnostics = _annual_diagnostics(annual_data)
    diagnostics.extend(annual_diagnostics)

    author_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"name": "", "papers": set(), "citations": []})
    for work in works:
        work_authors = norm.authors(work)
        for author in work_authors:
            author_id = author.get("id") or author.get("name")
            if not author_id:
                continue
            author_stats[author_id]["name"] = author.get("name") or author_id
            author_stats[author_id]["papers"].add(norm.work_id(work))
            author_stats[author_id]["citations"].append(norm.citations(work))
    if not author_stats:
        diagnostics.append("No authorship data found. Re-run works.search with include=['authors'] for author metrics.")

    authors_data = []
    for author_id, stats in author_stats.items():
        author_citation_counts = sorted(stats["citations"], reverse=True)
        n_papers = len(stats["papers"])
        total_author_citations = sum(author_citation_counts)
        authors_data.append(
            {
                "id": author_id,
                "name": stats["name"],
                "n_papers": n_papers,
                "total_citations": total_author_citations,
                "avg_citations": round(total_author_citations / n_papers, 3) if n_papers else 0,
                "h_index": _h_index(author_citation_counts),
            }
        )
    authors_data.sort(key=lambda row: (row["n_papers"], row["total_citations"]), reverse=True)

    sorted_works = sorted(works, key=norm.citations, reverse=True)
    papers_data = []
    for rank, work in enumerate(sorted_works[:top_papers], start=1):
        work_authors = norm.authors(work)
        author_names = [author["name"] for author in work_authors[:5] if author.get("name")]
        author_text = "; ".join(author_names)
        if len(work_authors) > 5:
            author_text = f"{author_text} et al." if author_text else "et al."
        papers_data.append(
            {
                "rank": rank,
                "id": norm.work_id(work),
                "title": norm.title(work),
                "authors": author_text,
                "year": norm.year(work),
                "source": norm.source(work).get("name") or "",
                "cited_by_count": norm.citations(work),
                "doi": work.get("doi") or "",
            }
        )

    source_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"name": "", "type": "", "papers": set(), "citations": []})
    for work in works:
        source = norm.source(work)
        source_id = source.get("id") or source.get("name")
        if not source_id:
            continue
        source_stats[source_id]["name"] = source.get("name") or source_id
        source_stats[source_id]["type"] = source.get("type") or ""
        source_stats[source_id]["papers"].add(norm.work_id(work))
        source_stats[source_id]["citations"].append(norm.citations(work))
    if not source_stats:
        diagnostics.append("No source data found; source metrics were skipped.")

    sources_data = []
    for source_id, stats in source_stats.items():
        n_papers = len(stats["papers"])
        source_citations = sum(stats["citations"])
        sources_data.append(
            {
                "id": source_id,
                "name": stats["name"],
                "type": stats["type"],
                "n_papers": n_papers,
                "total_citations": source_citations,
                "avg_citations": round(source_citations / n_papers, 3) if n_papers else 0,
                "h_index": _h_index(sorted(stats["citations"], reverse=True)),
            }
        )
    sources_data.sort(key=lambda row: (row["n_papers"], row["total_citations"]), reverse=True)

    topic_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"name": "", "scores": [], "citations": []})
    for work in works:
        for topic in norm.topics(work):
            topic_id = topic.get("id") or topic.get("name")
            if not topic_id:
                continue
            topic_stats[topic_id]["name"] = topic.get("name") or topic_id
            topic_stats[topic_id]["scores"].append(topic.get("score") or 0)
            topic_stats[topic_id]["citations"].append(norm.citations(work))
    if not topic_stats:
        diagnostics.append("No topic data found; topic frequency metrics were skipped.")

    topics_data = []
    for topic_id, stats in topic_stats.items():
        frequency = len(stats["scores"])
        topic_citations = sum(stats["citations"])
        topics_data.append(
            {
                "id": topic_id,
                "name": stats["name"],
                "frequency": frequency,
                "percentage": round(frequency / total_papers * 100, 3) if total_papers else 0,
                "avg_score": round(sum(stats["scores"]) / frequency, 4) if frequency else 0,
                "total_citations": topic_citations,
                "avg_citations": round(topic_citations / frequency, 3) if frequency else 0,
            }
        )
    topics_data.sort(key=lambda row: (row["frequency"], row["total_citations"]), reverse=True)

    return (
        {
            "overview": {
                "total_papers": total_papers,
                "total_citations": total_citations,
                "avg_citations": round(total_citations / total_papers, 3) if total_papers else 0,
                "median_citations": median(citation_counts) if citation_counts else 0,
                "citation_percentiles": {
                    "p25": _percentile(citation_counts, 25),
                    "p50": _percentile(citation_counts, 50),
                    "p75": _percentile(citation_counts, 75),
                    "p90": _percentile(citation_counts, 90),
                },
                "year_range": [min(year_stats), max(year_stats)] if year_stats else [None, None],
                "annual_growth_rate": annual_growth_rate,
                "open_access_count": oa_count,
                "open_access_share": round(oa_count / total_papers * 100, 3) if total_papers else 0,
                "document_types": [{"type": key, "count": value} for key, value in type_counts.most_common()],
            },
            "annual_production": {
                "total_years": len(year_stats),
                "annual_data": annual_data,
            },
            "annual_impact": {
                "total_years": len(year_stats),
                "annual_data": annual_data,
                "diagnostics": annual_diagnostics,
            },
            "most_productive_authors": {
                "total_authors": len(author_stats),
                "authors": authors_data[:top_authors],
            },
            "most_cited_papers": {
                "papers": papers_data,
            },
            "most_relevant_sources": {
                "total_sources": len(source_stats),
                "sources": sources_data[:top_sources],
            },
            "most_frequent_topics": {
                "total_topics": len(topic_stats),
                "topics": topics_data[:top_topics],
            },
        },
        diagnostics,
    )


def _h_index(citations: list[int]) -> int:
    return sum(1 for index, value in enumerate(citations, start=1) if value >= index)


def _percentile(values: list[int], percentile: int) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * percentile / 100
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 3)


def _annual_growth_rate(annual_data: list[dict[str, Any]]) -> float | None:
    if len(annual_data) < 2:
        return None
    first = annual_data[0]["n_papers"]
    last = annual_data[-1]["n_papers"]
    years = annual_data[-1]["year"] - annual_data[0]["year"]
    if first <= 0 or years <= 0:
        return None
    return round(((last / first) ** (1 / years) - 1) * 100, 3)


def _annual_impact_rows(year_stats: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cumulative_papers = 0
    cumulative_citations = 0
    ordered_years = sorted(year_stats)
    max_year = max(ordered_years) if ordered_years else None
    previous_papers: int | None = None
    for year in ordered_years:
        stats = year_stats[year]
        n_papers = int(stats["n_papers"])
        total_citations = int(stats["total_citations"])
        cumulative_papers += n_papers
        cumulative_citations += total_citations
        year_is_incomplete = bool(max_year is not None and year == max_year and previous_papers and n_papers < previous_papers * 0.5)
        rows.append(
            {
                "year": year,
                "n_papers": n_papers,
                "total_citations": total_citations,
                "avg_citations": round(total_citations / n_papers, 3) if n_papers else 0,
                "cumulative_papers": cumulative_papers,
                "cumulative_citations": cumulative_citations,
                "year_is_incomplete": year_is_incomplete,
                "citation_lag_warning": bool(max_year is not None and year >= max_year - 1),
            }
        )
        previous_papers = n_papers
    return rows


def _annual_diagnostics(annual_data: list[dict[str, Any]]) -> list[str]:
    diagnostics: list[str] = []
    incomplete = [row["year"] for row in annual_data if row.get("year_is_incomplete")]
    if incomplete:
        diagnostics.append(
            "Latest year appears incomplete based on publication volume; avoid interpreting the final-year drop as a field decline."
        )
    if annual_data:
        latest_year = annual_data[-1]["year"]
        diagnostics.append(
            f"Citation counts for recent years, especially {latest_year}, may be affected by citation lag."
        )
    return diagnostics


def _figures(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "annual_production": line(
            data["annual_production"]["annual_data"],
            x="year",
            y="n_papers",
            title="Annual Scientific Production",
        ),
        "annual_publications_and_citations": dual_axis_line_bar(
            data["annual_impact"]["annual_data"],
            x="year",
            bar_y="n_papers",
            line_y="total_citations",
            title="Annual Publications and Citations",
            bar_name="Number of Publications",
            line_name="Total Citations",
        ),
        "cumulative_publications": line(
            data["annual_impact"]["annual_data"],
            x="year",
            y="cumulative_papers",
            title="Cumulative Publications",
        ),
        "cumulative_citations": line(
            data["annual_impact"]["annual_data"],
            x="year",
            y="cumulative_citations",
            title="Cumulative Citations",
        ),
        "top_authors": bar(
            list(reversed(data["most_productive_authors"]["authors"][:20])),
            x="n_papers",
            y="name",
            title="Most Productive Authors",
            orientation="h",
        ),
        "top_sources": bar(
            list(reversed(data["most_relevant_sources"]["sources"][:20])),
            x="n_papers",
            y="name",
            title="Most Relevant Sources",
            orientation="h",
        ),
        "top_topics": bar(
            list(reversed(data["most_frequent_topics"]["topics"][:20])),
            x="frequency",
            y="name",
            title="Most Frequent Topics",
            orientation="h",
        ),
    }


def _summary_markdown(data: dict[str, Any], *, resolved_path: str, diagnostics: list[str]) -> str:
    overview = data["overview"]
    lines = [
        "# Bibliometric Analysis",
        "",
        f"Dataset: `{resolved_path}`",
        "",
        f"- Papers: {overview['total_papers']}",
        f"- Total citations: {overview['total_citations']}",
        f"- Average citations: {overview['avg_citations']}",
        f"- Median citations: {overview['median_citations']}",
        f"- Year range: {overview['year_range'][0]} - {overview['year_range'][1]}",
        f"- Annual growth rate: {overview['annual_growth_rate']}%",
        f"- Open access share: {overview['open_access_share']}%",
    ]
    annual_notes = data.get("annual_impact", {}).get("diagnostics") or []
    if annual_notes:
        lines.extend(["", "## Annual Trend Notes"])
        lines.extend(f"- {item}" for item in annual_notes)
    if diagnostics:
        lines.extend(["", "## Diagnostics"])
        lines.extend(f"- {item}" for item in diagnostics)
    lines.extend(["", "## Top Papers"])
    for paper in data["most_cited_papers"]["papers"][:10]:
        lines.append(f"- {paper['cited_by_count']} citations: {paper['title']} ({paper['year']})")
    lines.extend(["", "## Top Topics"])
    for topic in data["most_frequent_topics"]["topics"][:10]:
        lines.append(f"- {topic['name']}: {topic['frequency']} papers")
    return "\n".join(lines)
