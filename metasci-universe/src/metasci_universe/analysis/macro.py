"""Macro-level country, institution, and collaboration analysis."""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
from typing import Any

from metasci_universe.analysis import _normalize as norm
from metasci_universe.analysis._artifacts import save_analysis_artifacts
from metasci_universe.analysis._dataset import load_records
from metasci_universe.analysis._viz import (
    chord,
    choropleth,
    institution_collaboration_network,
    institution_country_density_map,
    line,
    ranked_horizontal_bar,
    stacked_bar,
    wide_matrix,
)
from metasci_universe.schemas.analysis import MacroAnalysisRequest
from metasci_universe.schemas.common import MetaSciResult


async def macro(
    dataset_path: str,
    *,
    dimensions: list[str] | None = None,
    top_n: int = 30,
    min_count: float = 1,
    counting: str = "full",
    include_temporal: bool = True,
    year_field: str = "publication_year",
    output_dir: str | None = None,
) -> MetaSciResult:
    """Analyze country, institution, and collaboration structure in a works dataset."""
    request = MacroAnalysisRequest(
        dataset_path=dataset_path,
        dimensions=dimensions or ["countries", "institutions", "country_collaboration", "institution_collaboration"],
        top_n=top_n,
        min_count=min_count,
        counting=counting,  # type: ignore[arg-type]
        include_temporal=include_temporal,
        year_field=year_field,
        output_dir=output_dir,
    )
    records, dataset_metadata, resolved_path = load_records(request.dataset_path)
    data, diagnostics = _compute_macro(records, request)
    input_payload = request.model_dump(mode="json")
    artifacts = save_analysis_artifacts(
        command="analysis.macro",
        input_payload=input_payload,
        data=data,
        summary_markdown=_summary_markdown(data, resolved_path=resolved_path, diagnostics=diagnostics),
        tables={
            "countries": data["countries"],
            "institutions": data["institutions"],
            "country_by_year": data["country_by_year"],
            "country_by_year_matrix": data["country_by_year_matrix"],
            "institution_by_year": data["institution_by_year"],
            "institution_by_year_matrix": data["institution_by_year_matrix"],
            "institution_country_density": data["institution_country_density"],
            "country_collaboration": data["country_collaboration"],
            "institution_collaboration": data["institution_collaboration"],
            "corresponding_author_countries": data["corresponding_author_countries"],
        },
        figures=_figures(data),
        output_dir=request.output_dir,
        diagnostics=diagnostics,
    )
    return MetaSciResult(
        command="analysis.macro",
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


def _compute_macro(works: list[dict[str, Any]], request: MacroAnalysisRequest) -> tuple[dict[str, Any], list[str]]:
    diagnostics: list[str] = []
    country_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"n_papers": 0.0, "total_citations": 0.0})
    institution_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"name": "", "country_code": "", "type": "", "n_papers": 0.0, "total_citations": 0.0}
    )
    country_by_year: Counter[tuple[int, str]] = Counter()
    institution_by_year: Counter[tuple[int, str, str]] = Counter()
    institution_country_density: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"institution_ids": set(), "n_papers": 0.0}
    )
    country_edges: Counter[tuple[str, str]] = Counter()
    institution_edges: Counter[tuple[str, str]] = Counter()
    institution_edge_names: dict[tuple[str, str], tuple[str, str]] = {}
    records_with_institutions = 0
    country_collaborator_counts: Counter[str] = Counter()
    institution_collaborator_counts: Counter[str] = Counter()
    country_first_year: dict[str, int] = {}
    country_last_year: dict[str, int] = {}
    institution_first_year: dict[str, int] = {}
    institution_last_year: dict[str, int] = {}
    records_with_single_country = 0
    records_with_multi_country = 0
    records_with_single_institution = 0
    records_with_multi_institution = 0
    corresponding_country_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"scp": 0, "mcp": 0, "total": 0})
    records_with_corresponding_country = 0

    for work in works:
        authors = norm.authors(work)
        countries: set[str] = set()
        institutions: dict[str, dict[str, Any]] = {}
        for author in authors:
            for institution in author.get("institutions") or []:
                institution_id = institution.get("id") or institution.get("name")
                country_code = institution.get("country_code") or ""
                if country_code:
                    countries.add(country_code)
                if institution_id:
                    institutions[institution_id] = institution

        if institutions or countries:
            records_with_institutions += 1

        citation_count = norm.citations(work)
        publication_year = norm.year(work, request.year_field)
        if len(countries) == 1:
            records_with_single_country += 1
        elif len(countries) > 1:
            records_with_multi_country += 1
        if len(institutions) == 1:
            records_with_single_institution += 1
        elif len(institutions) > 1:
            records_with_multi_institution += 1

        corresponding_countries = _corresponding_author_countries(authors, countries)
        if corresponding_countries:
            records_with_corresponding_country += 1
        for country_code in corresponding_countries:
            country_row = corresponding_country_stats[country_code]
            country_row["total"] += 1
            if len(countries) > 1:
                country_row["mcp"] += 1
            else:
                country_row["scp"] += 1

        country_weight = _weight(len(countries), request.counting)
        for country_code in countries:
            country_stats[country_code]["n_papers"] += country_weight
            country_stats[country_code]["total_citations"] += citation_count * country_weight
            if publication_year is not None and request.include_temporal:
                country_by_year[(publication_year, country_code)] += 1
                country_first_year.setdefault(country_code, publication_year)
                country_last_year[country_code] = publication_year

        institution_weight = _weight(len(institutions), request.counting)
        for institution_id, institution in institutions.items():
            institution_stats[institution_id]["name"] = institution.get("name") or institution_id
            institution_stats[institution_id]["country_code"] = institution.get("country_code") or ""
            institution_stats[institution_id]["type"] = institution.get("type") or ""
            institution_stats[institution_id]["n_papers"] += institution_weight
            institution_stats[institution_id]["total_citations"] += citation_count * institution_weight
            country_code = institution.get("country_code") or ""
            if country_code:
                institution_country_density[country_code]["institution_ids"].add(institution_id)
                institution_country_density[country_code]["n_papers"] += institution_weight
            if publication_year is not None and request.include_temporal:
                institution_by_year[(publication_year, institution_id, institution_stats[institution_id]["name"])] += 1
                institution_first_year.setdefault(institution_id, publication_year)
                institution_last_year[institution_id] = publication_year

        for left, right in combinations(sorted(countries), 2):
            country_edges[(left, right)] += 1
            country_collaborator_counts[left] += 1
            country_collaborator_counts[right] += 1
        for left, right in combinations(sorted(institutions), 2):
            institution_edges[(left, right)] += 1
            institution_collaborator_counts[left] += 1
            institution_collaborator_counts[right] += 1
            institution_edge_names[(left, right)] = (
                institutions[left].get("name") or left,
                institutions[right].get("name") or right,
            )

    if records_with_institutions == 0:
        diagnostics.append("No authorship institution data found. Re-run works.search with include=['authors'] for macro analysis.")

    countries = [
        {
            "country_code": country_code,
            "country_iso3": _country_iso3(country_code),
            "country_name": _country_name(country_code),
            "n_papers": round(stats["n_papers"], 3),
            "total_citations": round(stats["total_citations"], 3),
            "avg_citations": round(stats["total_citations"] / stats["n_papers"], 3) if stats["n_papers"] else 0,
            "first_year": country_first_year.get(country_code),
            "last_year": country_last_year.get(country_code),
            "collaborator_count": country_collaborator_counts.get(country_code, 0),
        }
        for country_code, stats in country_stats.items()
        if stats["n_papers"] >= request.min_count
    ]
    countries.sort(key=lambda row: (row["n_papers"], row["total_citations"]), reverse=True)

    institutions_rows = [
        {
            "id": institution_id,
            "name": stats["name"],
            "country_code": stats["country_code"],
            "type": stats["type"],
            "n_papers": round(stats["n_papers"], 3),
            "total_citations": round(stats["total_citations"], 3),
            "avg_citations": round(stats["total_citations"] / stats["n_papers"], 3) if stats["n_papers"] else 0,
            "first_year": institution_first_year.get(institution_id),
            "last_year": institution_last_year.get(institution_id),
            "collaborator_count": institution_collaborator_counts.get(institution_id, 0),
        }
        for institution_id, stats in institution_stats.items()
        if stats["n_papers"] >= request.min_count
    ]
    institutions_rows.sort(key=lambda row: (row["n_papers"], row["total_citations"]), reverse=True)

    country_edge_rows = [
        {"source": left, "target": right, "weight": weight}
        for (left, right), weight in country_edges.most_common()
        if weight >= request.min_count
    ]
    institution_edge_rows = [
        {
            "source": institution_edge_names.get((left, right), (left, right))[0],
            "target": institution_edge_names.get((left, right), (left, right))[1],
            "source_id": left,
            "target_id": right,
            "weight": weight,
        }
        for (left, right), weight in institution_edges.most_common()
        if weight >= request.min_count
    ]

    country_by_year_rows = [
        {
            "year": year,
            "country_code": country_code,
            "country_iso3": _country_iso3(country_code),
            "country_name": _country_name(country_code),
            "n_papers": count,
        }
        for (year, country_code), count in sorted(country_by_year.items())
    ]
    if country_by_year and all(not row["country_iso3"] for row in country_by_year_rows):
        diagnostics.append("Could not normalize country codes for map output; install pycountry for choropleth maps.")

    institution_by_year_rows = [
        {"year": year, "institution_id": institution_id, "institution": name, "n_papers": count}
        for (year, institution_id, name), count in sorted(institution_by_year.items())
    ]
    institution_country_density_rows = [
        {
            "country_code": country_code,
            "country_iso3": _country_iso3(country_code),
            "country_name": _country_name(country_code),
            "n_institutions": len(stats["institution_ids"]),
            "n_papers": round(stats["n_papers"], 3),
        }
        for country_code, stats in institution_country_density.items()
        if stats["institution_ids"]
    ]
    institution_country_density_rows.sort(key=lambda row: (row["n_institutions"], row["n_papers"]), reverse=True)
    corresponding_country_rows = [
        {
            "country_code": country_code,
            "country_name": _country_name(country_code),
            "scp": stats["scp"],
            "mcp": stats["mcp"],
            "total": stats["total"],
            "mcp_share": round(stats["mcp"] / stats["total"] * 100, 3) if stats["total"] else 0,
        }
        for country_code, stats in corresponding_country_stats.items()
        if stats["total"] >= request.min_count
    ]
    corresponding_country_rows.sort(key=lambda row: (row["total"], row["mcp"]), reverse=True)

    return (
        {
            "overview": {
                "total_papers": len(works),
                "records_with_institution_data": records_with_institutions,
                "country_count": len(country_stats),
                "institution_count": len(institution_stats),
                "counting": request.counting,
                "records_with_single_country": records_with_single_country,
                "records_with_multi_country": records_with_multi_country,
                "records_with_single_institution": records_with_single_institution,
                "records_with_multi_institution": records_with_multi_institution,
                "records_with_corresponding_country": records_with_corresponding_country,
                "international_collaboration_share": round(
                    records_with_multi_country / records_with_institutions * 100, 3
                )
                if records_with_institutions
                else 0,
                "multi_institution_share": round(records_with_multi_institution / records_with_institutions * 100, 3)
                if records_with_institutions
                else 0,
            },
            "countries": countries[: request.top_n],
            "institutions": institutions_rows[: request.top_n],
            "institution_network_nodes": institutions_rows[: request.top_n * 5],
            "country_by_year": country_by_year_rows,
            "country_by_year_matrix": wide_matrix(
                country_by_year_rows, index="year", columns="country_code", values="n_papers"
            ),
            "corresponding_author_countries": corresponding_country_rows[: request.top_n],
            "institution_by_year": institution_by_year_rows,
            "institution_by_year_matrix": wide_matrix(
                institution_by_year_rows, index="year", columns="institution", values="n_papers"
            ),
            "institution_country_density": institution_country_density_rows,
            "country_collaboration": country_edge_rows[: request.top_n * 5],
            "institution_collaboration": institution_edge_rows[: request.top_n * 5],
        },
        diagnostics,
    )


def _weight(size: int, counting: str) -> float:
    if size <= 0:
        return 0.0
    if counting == "fractional":
        return 1.0 / size
    return 1.0


def _corresponding_author_countries(authors: list[dict[str, Any]], work_countries: set[str]) -> set[str]:
    corresponding_countries: set[str] = set()
    for author in authors:
        if author.get("is_corresponding") is not True:
            continue
        for institution in author.get("institutions") or []:
            country_code = institution.get("country_code") or ""
            if country_code:
                corresponding_countries.add(country_code)

    if corresponding_countries:
        return corresponding_countries

    first_author = next((author for author in authors if author.get("position") == 1), authors[0] if authors else None)
    if not first_author:
        return set()
    for institution in first_author.get("institutions") or []:
        country_code = institution.get("country_code") or ""
        if country_code:
            corresponding_countries.add(country_code)
    if corresponding_countries:
        return corresponding_countries
    return set(work_countries) if len(work_countries) == 1 else set()


def _figures(data: dict[str, Any]) -> dict[str, Any]:
    top_institution_names = {row["name"] for row in data["institutions"][:10]}
    top_institution_timeline = [
        row for row in data["institution_by_year"] if row.get("institution") in top_institution_names
    ]
    country_map_rows = [row for row in data["country_by_year"] if row.get("country_iso3")]
    institution_country_density_rows = [row for row in data["institution_country_density"] if row.get("country_iso3")]
    corresponding_country_rows = _corresponding_country_plot_rows(data["corresponding_author_countries"][:20])
    country_node_metadata = {
        row["country_code"]: {
            "label": row.get("country_name") or row["country_code"],
            "hover": (
                f"{row['country_name']} ({row['country_code']}): "
                f"{row['n_papers']} papers, {row['collaborator_count']} collaboration links"
            ),
            "size": 10 + min(30, float(row["n_papers"]) ** 0.5 * 2.5),
        }
        for row in data["countries"]
    }
    institution_node_rows = data.get("institution_network_nodes") or data["institutions"]
    institution_node_metadata = {
        row["name"]: {
            "n_papers": row["n_papers"],
            "country_code": row.get("country_code") or "",
            "hover": (
                f"{row['name']}: {row['n_papers']} papers, {row['avg_citations']} avg citations, "
                f"{row['collaborator_count']} collaborator links"
            ),
        }
        for row in institution_node_rows
    }
    institution_bar_colors = _ranked_palette(len(data["institutions"][:10]))
    return {
        "figure4a_top_institutions": ranked_horizontal_bar(
            data["institutions"],
            x="n_papers",
            y="name",
            title="A. Most Relevant Institutions",
            x_title="Number of Publications",
            top_n=10,
            marker_colors=institution_bar_colors,
            font_size=16,
            height=520,
        ),
        "country_timeline": line(
            data["country_by_year"],
            x="year",
            y="n_papers",
            color="country_code",
            title="Country Production Over Time",
        ),
        "country_productivity_map": choropleth(
            country_map_rows,
            locations="country_iso3",
            color="n_papers",
            animation_frame="year",
            hover_name="country_name",
            title="Country Productivity Map",
        ),
        "institution_timeline": line(
            top_institution_timeline,
            x="year",
            y="n_papers",
            color="institution",
            title="Top Institution Production Over Time",
        ),
        "figure4b_institution_collaboration_network": institution_collaboration_network(
            data["institution_collaboration"],
            title="B. Institutional Collaboration Network",
            node_metadata=institution_node_metadata,
            max_edges=100,
            highlight_top_n=6,
            font_size=15,
        ),
        "figure4c_institution_country_density_downgraded": institution_country_density_map(
            data["institutions"],
            data["institution_collaboration"],
            title="C. Geographic Distribution and Research Density of Institutions (Country-Level)",
            font_size=15,
            top_n=20,
        ),
        "country_collaboration_chord": chord(
            data["country_collaboration"],
            title="Country Collaboration Chord Diagram",
            max_edges=120,
            node_order=[row["country_code"] for row in data["countries"]],
            node_metadata=country_node_metadata,
        ),
        "corresponding_author_countries": stacked_bar(
            corresponding_country_rows,
            x="n_papers",
            y="country_name",
            color="publication_type",
            title="Corresponding Author Countries/Regions",
            orientation="h",
            color_discrete_map={"SCP": "#00bfc4", "MCP": "#f8766d"},
        ),
    }


def _ranked_palette(size: int) -> list[str]:
    palette = ["#3ba7d8", "#48c858", "#79cf48", "#f19b72", "#e96a6a", "#c85fa8", "#7d80c8", "#65b7c8", "#b39a4d", "#8fb9d9"]
    return [palette[index % len(palette)] for index in range(size)]


def _corresponding_country_plot_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plot_rows: list[dict[str, Any]] = []
    for row in reversed(rows):
        country_name = row.get("country_name") or row.get("country_code")
        plot_rows.append(
            {
                "country_code": row.get("country_code"),
                "country_name": country_name,
                "publication_type": "MCP",
                "n_papers": row.get("mcp") or 0,
            }
        )
        plot_rows.append(
            {
                "country_code": row.get("country_code"),
                "country_name": country_name,
                "publication_type": "SCP",
                "n_papers": row.get("scp") or 0,
            }
        )
    return plot_rows


def _summary_markdown(data: dict[str, Any], *, resolved_path: str, diagnostics: list[str]) -> str:
    lines = [
        "# Macro Analysis",
        "",
        f"Dataset: `{resolved_path}`",
        "",
        f"- Papers: {data['overview']['total_papers']}",
        f"- Records with institution data: {data['overview']['records_with_institution_data']}",
        f"- Countries: {data['overview']['country_count']}",
        f"- Institutions: {data['overview']['institution_count']}",
        f"- International collaboration share: {data['overview']['international_collaboration_share']}%",
        f"- Multi-institution share: {data['overview']['multi_institution_share']}%",
        f"- Records with corresponding-author country: {data['overview']['records_with_corresponding_country']}",
    ]
    if diagnostics:
        lines.extend(["", "## Diagnostics"])
        lines.extend(f"- {item}" for item in diagnostics)
    lines.extend(["", "## Top Countries"])
    for row in data["countries"][:10]:
        span = ""
        if row.get("first_year") or row.get("last_year"):
            span = f", active {row.get('first_year')}–{row.get('last_year')}"
        lines.append(
            f"- {row['country_code']}: {row['n_papers']} papers, {row['avg_citations']} avg citations, "
            f"{row['collaborator_count']} collaborator links{span}"
        )
    lines.extend(["", "## Top Institutions"])
    for row in data["institutions"][:10]:
        span = ""
        if row.get("first_year") or row.get("last_year"):
            span = f", active {row.get('first_year')}–{row.get('last_year')}"
        lines.append(
            f"- {row['name']}: {row['n_papers']} papers, {row['avg_citations']} avg citations, "
            f"{row['collaborator_count']} collaborator links{span}"
        )
    lines.extend(["", "## Strongest Country Collaboration Links"])
    for row in data["country_collaboration"][:10]:
        lines.append(f"- {row['source']} - {row['target']}: {row['weight']} shared papers")
    lines.extend(["", "## Top Corresponding-Author Countries"])
    for row in data["corresponding_author_countries"][:10]:
        lines.append(
            f"- {row['country_name']} ({row['country_code']}): {row['total']} papers "
            f"({row['scp']} SCP, {row['mcp']} MCP; MCP share {row['mcp_share']}%)"
        )
    return "\n".join(lines)


def _country_iso3(country_code: str) -> str:
    if not country_code:
        return ""
    if len(country_code) == 3:
        return country_code.upper()
    try:
        import pycountry

        country = pycountry.countries.get(alpha_2=country_code.upper())
        return country.alpha_3 if country else ""
    except Exception:
        return ""


def _country_name(country_code: str) -> str:
    if not country_code:
        return ""
    try:
        import pycountry

        country = pycountry.countries.get(alpha_2=country_code.upper()) or pycountry.countries.get(
            alpha_3=country_code.upper()
        )
        return country.name if country else country_code
    except Exception:
        return country_code
