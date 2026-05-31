"""Composed science-landscape analysis workflows."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from metasci_universe.analysis.author_landscape import author_landscape
from metasci_universe.analysis.bibliometrics import bibliometrics
from metasci_universe.analysis.citations import citation_overview
from metasci_universe.analysis.macro import macro
from metasci_universe.analysis.recommend import preflight
from metasci_universe.analysis.topics import topic_landscape
from metasci_universe.schemas.analysis import ScienceLandscapeRequest
from metasci_universe.schemas.common import MetaSciResult


async def science_landscape(
    dataset_path: str,
    *,
    include: list[str] | None = None,
    top_n: int = 30,
    min_count: int | None = None,
    text_backend: str = "sklearn",
    modeling_backend: str = "sklearn_lda",
    nr_topics: int | None = None,
    max_docs: int | None = None,
    skip_unready: bool = True,
    output_dir: str | None = None,
) -> MetaSciResult:
    """Run a compact multi-tool analysis for a saved works dataset."""
    request = ScienceLandscapeRequest(
        dataset_path=dataset_path,
        include=include or ["bibliometrics", "macro", "author_landscape", "topic_landscape", "citation_overview"],
        top_n=top_n,
        min_count=min_count,
        text_backend=text_backend,  # type: ignore[arg-type]
        modeling_backend=modeling_backend,  # type: ignore[arg-type]
        nr_topics=nr_topics,
        max_docs=max_docs,
        skip_unready=skip_unready,
        output_dir=output_dir,
    )
    rec = await preflight(request.dataset_path, intent="science_landscape")
    safe_defaults = rec.data["safe_defaults"]
    ready_tools = set(rec.data["overview"]["recommended_tools"])
    output_root = Path(request.output_dir).expanduser() if request.output_dir else None
    results: dict[str, MetaSciResult] = {"recommendation": rec}
    diagnostics = list(rec.diagnostics)

    for component in request.include:
        tool_name = _component_tool(component)
        if request.skip_unready and tool_name not in ready_tools:
            diagnostics.append(f"Skipped {component}: {tool_name} is not ready for this dataset.")
            continue
        try:
            results[component] = await _run_component(component, request, safe_defaults, output_root)
        except Exception as exc:
            diagnostics.append(f"{component} failed: {exc}")

    data = _summarize_results(results)
    artifacts = _write_landscape_summary(data, request=request, results=results, diagnostics=diagnostics)
    return MetaSciResult(
        command="workflows.science_landscape",
        input=request.model_dump(mode="json"),
        data=data,
        artifacts=artifacts,
        metadata={
            "dataset_path": rec.metadata.get("dataset_path", request.dataset_path),
            "record_count": rec.metadata.get("record_count"),
            "components": [key for key in results if key != "recommendation"],
        },
        diagnostics=diagnostics,
    )


def _component_tool(component: str) -> str:
    return {
        "bibliometrics": "analysis.bibliometrics",
        "macro": "analysis.macro",
        "author_landscape": "analysis.author_landscape",
        "topic_landscape": "analysis.topic_landscape",
        "citation_overview": "analysis.citation_overview",
    }[component]


async def _run_component(
    component: str,
    request: ScienceLandscapeRequest,
    safe_defaults: dict[str, Any],
    output_root: Path | None,
) -> MetaSciResult:
    output_dir = str(output_root / component) if output_root else None
    runners: dict[str, Callable[[], Awaitable[MetaSciResult]]] = {
        "bibliometrics": lambda: bibliometrics(
            request.dataset_path,
            top_authors=request.top_n,
            top_papers=request.top_n,
            top_sources=request.top_n,
            top_topics=request.top_n,
            output_dir=output_dir,
        ),
        "macro": lambda: macro(
            request.dataset_path,
            top_n=request.top_n,
            min_count=request.min_count or safe_defaults["min_count"],
            output_dir=output_dir,
        ),
        "author_landscape": lambda: author_landscape(
            request.dataset_path,
            top_n=request.top_n,
            min_papers=safe_defaults["author_landscape_min_papers"],
            output_dir=output_dir,
        ),
        "topic_landscape": lambda: topic_landscape(
            request.dataset_path,
            top_n=request.top_n,
            min_count=request.min_count or safe_defaults["min_count"],
            methods=safe_defaults["topic_landscape_methods"],
            text_backend=request.text_backend,
            modeling_backend=request.modeling_backend,
            nr_topics=request.nr_topics if request.nr_topics is not None else safe_defaults["nr_topics"],
            max_docs=request.max_docs if request.max_docs is not None else safe_defaults["max_docs"],
            output_dir=output_dir,
        ),
        "citation_overview": lambda: citation_overview(
            request.dataset_path,
            top_papers=request.top_n,
            include_reference_frequency=safe_defaults["include_reference_frequency"],
            output_dir=output_dir,
        ),
    }
    return await runners[component]()


def _summarize_results(results: dict[str, MetaSciResult]) -> dict[str, Any]:
    recommendation = results["recommendation"]
    summary: dict[str, Any] = {
        "overview": {
            "total_papers": recommendation.data["overview"]["total_papers"],
            "components_run": [key for key in results if key != "recommendation"],
            "blocked_tools": recommendation.data["overview"]["blocked_tools"],
        },
        "recommendation": recommendation.data,
        "components": {},
    }
    if "bibliometrics" in results:
        bib = results["bibliometrics"].data
        summary["components"]["bibliometrics"] = {
            "overview": bib.get("overview", {}),
            "top_papers": bib.get("most_cited_papers", {}).get("papers", [])[:10],
            "top_sources": bib.get("most_relevant_sources", {}).get("sources", [])[:10],
            "top_topics": bib.get("most_frequent_topics", {}).get("topics", [])[:10],
            "artifacts": results["bibliometrics"].artifacts,
        }
    if "macro" in results:
        mac = results["macro"].data
        summary["components"]["macro"] = {
            "overview": mac.get("overview", {}),
            "countries": mac.get("countries", [])[:10],
            "institutions": mac.get("institutions", [])[:10],
            "country_collaboration": mac.get("country_collaboration", [])[:10],
            "institution_collaboration": mac.get("institution_collaboration", [])[:10],
            "artifacts": results["macro"].artifacts,
        }
    if "author_landscape" in results:
        authors = results["author_landscape"].data
        summary["components"]["author_landscape"] = {
            "overview": authors.get("overview", {}),
            "authors": authors.get("authors", [])[:10],
            "author_collaboration": authors.get("author_collaboration", [])[:10],
            "author_roles": authors.get("author_roles", [])[:10],
            "artifacts": results["author_landscape"].artifacts,
        }
    if "topic_landscape" in results:
        topics = results["topic_landscape"].data
        summary["components"]["topic_landscape"] = {
            "overview": topics.get("overview", {}),
            "openalex_topics": topics.get("openalex_topics", {}).get("topics", [])[:10],
            "coword_terms": topics.get("coword", {}).get("terms", [])[:10],
            "modeled_topics": topics.get("topic_modeling", {}).get("topics", [])[:10],
            "artifacts": results["topic_landscape"].artifacts,
        }
    if "citation_overview" in results:
        citations = results["citation_overview"].data
        summary["components"]["citation_overview"] = {
            "overview": citations.get("overview", {}),
            "top_cited_papers": citations.get("top_cited_papers", [])[:10],
            "top_references": citations.get("top_references", [])[:10],
            "artifacts": results["citation_overview"].artifacts,
        }
    return summary


def _write_landscape_summary(
    data: dict[str, Any],
    *,
    request: ScienceLandscapeRequest,
    results: dict[str, MetaSciResult],
    diagnostics: list[str],
) -> dict[str, str]:
    if request.output_dir is None:
        return {}
    output_dir = Path(request.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "science_landscape_summary.md"
    lines = [
        "# Science Landscape",
        "",
        f"- Dataset: `{request.dataset_path}`",
        f"- Papers: {data['overview']['total_papers']}",
        f"- Components: {', '.join(data['overview']['components_run']) or 'none'}",
    ]
    if diagnostics:
        lines.extend(["", "## Diagnostics"])
        lines.extend(f"- {item}" for item in diagnostics)
    for name, result in results.items():
        if name == "recommendation":
            continue
        lines.extend(["", f"## {name.replace('_', ' ').title()}", "", result.summary()])
    summary_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {"summary_md": str(summary_path)}
