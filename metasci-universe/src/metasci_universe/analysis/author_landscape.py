"""Corpus-level author role, collaboration, and influence analysis."""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
from typing import Any

from metasci_universe.analysis import _normalize as norm
from metasci_universe.analysis._artifacts import save_analysis_artifacts
from metasci_universe.analysis._dataset import load_records
from metasci_universe.analysis._viz import bar, line, network, wide_matrix
from metasci_universe.schemas.analysis import AuthorLandscapeRequest
from metasci_universe.schemas.common import MetaSciResult


async def author_landscape(
    dataset_path: str,
    *,
    top_n: int = 30,
    min_papers: int = 1,
    include_temporal: bool = True,
    year_field: str = "publication_year",
    output_dir: str | None = None,
) -> MetaSciResult:
    """Analyze author productivity, roles, affiliations, topics, and coauthor networks."""
    request = AuthorLandscapeRequest(
        dataset_path=dataset_path,
        top_n=top_n,
        min_papers=min_papers,
        include_temporal=include_temporal,
        year_field=year_field,
        output_dir=output_dir,
    )
    records, dataset_metadata, resolved_path = load_records(request.dataset_path)
    data, diagnostics = _compute_author_landscape(records, request)
    input_payload = request.model_dump(mode="json")
    artifacts = save_analysis_artifacts(
        command="analysis.author_landscape",
        input_payload=input_payload,
        data=data,
        summary_markdown=_summary_markdown(data, resolved_path=resolved_path, diagnostics=diagnostics),
        tables={
            "authors": data["authors"],
            "author_by_year": data["author_by_year"],
            "author_by_year_matrix": data["author_by_year_matrix"],
            "author_collaboration": data["author_collaboration"],
            "author_institutions": data["author_institutions"],
            "author_topics": data["author_topics"],
            "author_roles": data["author_roles"],
        },
        figures=_figures(data),
        output_dir=request.output_dir,
        diagnostics=diagnostics,
    )
    return MetaSciResult(
        command="analysis.author_landscape",
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


def _compute_author_landscape(
    works: list[dict[str, Any]],
    request: AuthorLandscapeRequest,
) -> tuple[dict[str, Any], list[str]]:
    diagnostics: list[str] = []
    author_stats: dict[str, dict[str, Any]] = defaultdict(_author_stats)
    author_year: Counter[tuple[int, str]] = Counter()
    author_edges: Counter[tuple[str, str]] = Counter()
    author_edge_names: dict[tuple[str, str], tuple[str, str]] = {}
    author_institution: Counter[tuple[str, str, str, str]] = Counter()
    author_topic: Counter[tuple[str, str, str]] = Counter()
    records_with_authors = 0
    records_with_corresponding = 0

    for work in works:
        authors = norm.authors(work)
        if not authors:
            continue
        records_with_authors += 1
        has_corresponding_author = False
        citation_count = norm.citations(work)
        publication_year = norm.year(work, request.year_field)
        work_topics = norm.topics(work)
        author_ids_in_work: list[str] = []

        for index, author in enumerate(authors, start=1):
            author_id = author.get("id") or author.get("name")
            if not author_id:
                continue
            author_ids_in_work.append(author_id)
            stats = author_stats[author_id]
            stats["id"] = author_id
            stats["name"] = author.get("name") or author_id
            stats["papers"].add(norm.work_id(work))
            stats["citations"].append(citation_count)
            stats["collaborators"].update(
                other.get("id") or other.get("name")
                for other in authors
                if (other.get("id") or other.get("name")) and (other.get("id") or other.get("name")) != author_id
            )

            position = author.get("author_position") or ""
            if position == "first" or index == 1:
                stats["first_author_papers"] += 1
            if position == "last" or index == len(authors):
                stats["last_author_papers"] += 1
            if author.get("is_corresponding") is True:
                stats["corresponding_author_papers"] += 1
                has_corresponding_author = True

            if publication_year is not None and request.include_temporal:
                author_year[(publication_year, author_id)] += 1

            for institution in author.get("institutions") or []:
                institution_id = institution.get("id") or institution.get("name")
                institution_name = institution.get("name") or institution_id
                country_code = institution.get("country_code") or ""
                if institution_id:
                    stats["institutions"][institution_id] = (institution_name, country_code)
                    author_institution[(author_id, institution_id, institution_name, country_code)] += 1

            for topic in work_topics:
                topic_name = topic.get("name") or topic.get("id")
                if topic_name:
                    stats["topics"].add(topic_name)
                    author_topic[(author_id, stats["name"], topic_name)] += 1

        for left, right in combinations(sorted(set(author_ids_in_work)), 2):
            author_edges[(left, right)] += 1
            author_edge_names[(left, right)] = (
                author_stats[left]["name"] or left,
                author_stats[right]["name"] or right,
            )

        if has_corresponding_author:
            records_with_corresponding += 1

    if records_with_authors == 0:
        diagnostics.append("No authorship data found. Re-run works.search with include=['authors'] for author landscape analysis.")

    authors_rows = []
    for author_id, stats in author_stats.items():
        n_papers = len(stats["papers"])
        if n_papers < request.min_papers:
            continue
        citations = sorted(stats["citations"], reverse=True)
        primary_institution, primary_country = _primary_affiliation(author_id, author_institution)
        authors_rows.append(
            {
                "id": author_id,
                "name": stats["name"],
                "n_papers": n_papers,
                "total_citations": sum(citations),
                "avg_citations": round(sum(citations) / n_papers, 3) if n_papers else 0,
                "corpus_h_index": _h_index(citations),
                "first_author_papers": stats["first_author_papers"],
                "last_author_papers": stats["last_author_papers"],
                "corresponding_author_papers": stats["corresponding_author_papers"],
                "collaborator_count": len(stats["collaborators"]),
                "institution_count": len(stats["institutions"]),
                "country_count": len({country for _, country in stats["institutions"].values() if country}),
                "topic_count": len(stats["topics"]),
                "primary_institution": primary_institution,
                "primary_country": primary_country,
            }
        )
    authors_rows.sort(key=lambda row: (row["n_papers"], row["total_citations"]), reverse=True)
    returned_author_ids = {row["id"] for row in authors_rows[: request.top_n]}

    author_by_year_rows = [
        {
            "year": year,
            "author_id": author_id,
            "author": author_stats[author_id]["name"] or author_id,
            "n_papers": count,
        }
        for (year, author_id), count in sorted(author_year.items())
        if author_id in returned_author_ids
    ]
    author_edge_rows = [
        {
            "source": author_edge_names.get((left, right), (left, right))[0],
            "target": author_edge_names.get((left, right), (left, right))[1],
            "source_id": left,
            "target_id": right,
            "weight": weight,
        }
        for (left, right), weight in author_edges.most_common(request.top_n * 10)
    ]
    author_institution_rows = [
        {
            "author_id": author_id,
            "author": author_stats[author_id]["name"] or author_id,
            "institution_id": institution_id,
            "institution": institution_name,
            "country_code": country_code,
            "n_papers": count,
        }
        for (author_id, institution_id, institution_name, country_code), count in author_institution.most_common()
        if author_id in returned_author_ids
    ][: request.top_n * 10]
    author_topic_rows = [
        {"author_id": author_id, "author": author_name, "topic": topic, "n_papers": count}
        for (author_id, author_name, topic), count in author_topic.most_common()
        if author_id in returned_author_ids
    ][: request.top_n * 10]
    role_rows = [
        {
            "author_id": row["id"],
            "author": row["name"],
            "role": role,
            "n_papers": row[field],
        }
        for row in authors_rows[: request.top_n]
        for role, field in [
            ("first", "first_author_papers"),
            ("last", "last_author_papers"),
            ("corresponding", "corresponding_author_papers"),
        ]
        if row[field]
    ]

    return (
        {
            "overview": {
                "total_papers": len(works),
                "records_with_authors": records_with_authors,
                "records_with_corresponding_authors": records_with_corresponding,
                "total_authors": len(author_stats),
                "author_collaboration_edges": len(author_edges),
                "authors_returned": min(len(authors_rows), request.top_n),
            },
            "authors": authors_rows[: request.top_n],
            "author_by_year": author_by_year_rows,
            "author_by_year_matrix": wide_matrix(author_by_year_rows, index="year", columns="author", values="n_papers"),
            "author_collaboration": author_edge_rows,
            "author_institutions": author_institution_rows,
            "author_topics": author_topic_rows,
            "author_roles": role_rows,
        },
        diagnostics,
    )


def _author_stats() -> dict[str, Any]:
    return {
        "id": "",
        "name": "",
        "papers": set(),
        "citations": [],
        "first_author_papers": 0,
        "last_author_papers": 0,
        "corresponding_author_papers": 0,
        "collaborators": set(),
        "institutions": {},
        "topics": set(),
    }


def _primary_affiliation(author_id: str, counts: Counter[tuple[str, str, str, str]]) -> tuple[str, str]:
    candidates = [
        (institution_name, country_code, count)
        for (row_author_id, _, institution_name, country_code), count in counts.items()
        if row_author_id == author_id
    ]
    if not candidates:
        return "", ""
    institution_name, country_code, _ = max(candidates, key=lambda row: row[2])
    return institution_name, country_code


def _h_index(citations: list[int]) -> int:
    h = 0
    for rank, count in enumerate(sorted(citations, reverse=True), start=1):
        if count >= rank:
            h = rank
        else:
            break
    return h


def _figures(data: dict[str, Any]) -> dict[str, Any]:
    top_author_names = {row["name"] for row in data["authors"][:10]}
    top_author_timeline = [row for row in data["author_by_year"] if row.get("author") in top_author_names]
    return {
        "top_authors": bar(
            list(reversed(data["authors"][:20])),
            x="n_papers",
            y="name",
            title="Top Authors by Corpus Publications",
            orientation="h",
        ),
        "author_timeline": line(
            top_author_timeline,
            x="year",
            y="n_papers",
            color="author",
            title="Top Author Production Over Time",
        ),
        "author_collaboration_network": network(
            data["author_collaboration"],
            title="Author Collaboration Network",
            max_edges=150,
        ),
        "first_author_leaders": bar(
            list(reversed([row for row in data["authors"] if row["first_author_papers"]][:20])),
            x="first_author_papers",
            y="name",
            title="Top First-Author Contributors",
            orientation="h",
        ),
    }


def _summary_markdown(data: dict[str, Any], *, resolved_path: str, diagnostics: list[str]) -> str:
    lines = [
        "# Author Landscape",
        "",
        f"Dataset: `{resolved_path}`",
        "",
        f"- Papers: {data['overview']['total_papers']}",
        f"- Records with authors: {data['overview']['records_with_authors']}",
        f"- Authors: {data['overview']['total_authors']}",
        f"- Author collaboration edges: {data['overview']['author_collaboration_edges']}",
    ]
    if diagnostics:
        lines.extend(["", "## Diagnostics"])
        lines.extend(f"- {item}" for item in diagnostics)
    lines.extend(["", "## Top Authors"])
    for row in data["authors"][:10]:
        role_bits = []
        if row["first_author_papers"]:
            role_bits.append(f"{row['first_author_papers']} first-author")
        if row["last_author_papers"]:
            role_bits.append(f"{row['last_author_papers']} last-author")
        if row["corresponding_author_papers"]:
            role_bits.append(f"{row['corresponding_author_papers']} corresponding")
        role_text = f" ({', '.join(role_bits)})" if role_bits else ""
        lines.append(
            f"- {row['name']}: {row['n_papers']} papers, {row['total_citations']} citations{role_text}"
        )
    lines.extend(["", "## Strongest Coauthor Links"])
    for row in data["author_collaboration"][:10]:
        lines.append(f"- {row['source']} - {row['target']}: {row['weight']} shared papers")
    return "\n".join(lines)
