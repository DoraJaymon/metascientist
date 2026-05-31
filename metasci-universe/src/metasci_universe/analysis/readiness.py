"""Readiness diagnostics for saved works datasets."""

from __future__ import annotations

from typing import Any

from metasci_universe.analysis import _normalize as norm
from metasci_universe.analysis._artifacts import save_analysis_artifacts
from metasci_universe.analysis._dataset import load_records
from metasci_universe.schemas.analysis import AnalysisReadinessRequest
from metasci_universe.schemas.common import MetaSciResult


async def inspect_readiness(dataset_path: str, *, output_dir: str | None = None) -> MetaSciResult:
    """Inspect whether a saved works dataset has enough fields for analysis tools."""
    request = AnalysisReadinessRequest(dataset_path=dataset_path, output_dir=output_dir)
    records, dataset_metadata, resolved_path = load_records(request.dataset_path)
    data = _inspect(records)
    input_payload = request.model_dump(mode="json")
    artifacts = save_analysis_artifacts(
        command="analysis.inspect_readiness",
        input_payload=input_payload,
        data=data,
        summary_markdown=_summary_markdown(data, resolved_path=resolved_path),
        tables={
            "field_coverage": data["field_coverage"],
            "tool_readiness": data["tools"],
        },
        output_dir=request.output_dir,
        diagnostics=[],
    )
    return MetaSciResult(
        command="analysis.inspect_readiness",
        input=input_payload,
        data=data,
        artifacts=artifacts,
        metadata={
            "record_count": len(records),
            "dataset_path": resolved_path,
            "dataset_schema": dataset_metadata.get("schema_name"),
        },
    )


def _inspect(works: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(works)
    counts = {
        "title": sum(1 for work in works if norm.title(work)),
        "abstract": sum(1 for work in works if norm.abstract_text(work)),
        "year": sum(1 for work in works if norm.year(work) is not None),
        "authors": sum(1 for work in works if norm.authors(work)),
        "author_institutions": sum(
            1
            for work in works
            if any(author.get("institutions") for author in norm.authors(work))
        ),
        "source": sum(1 for work in works if norm.source(work).get("name")),
        "topics": sum(1 for work in works if norm.topics(work)),
        "referenced_works": sum(1 for work in works if norm.referenced_works(work)),
    }
    coverage = [
        {
            "field": field,
            "records": count,
            "coverage": round(count / total * 100, 3) if total else 0,
        }
        for field, count in counts.items()
    ]

    tools = [
        _tool_status(
            "analysis.bibliometrics",
            total,
            checks=[
                ("title", counts["title"], 0.8, "titles"),
                ("year", counts["year"], 0.5, "publication years"),
                ("source", counts["source"], 0.5, "sources"),
                ("authors", counts["authors"], 0.5, "authors"),
            ],
            recommended_fetch_args={"include": ["authors"]},
        ),
        _tool_status(
            "analysis.macro",
            total,
            checks=[
                ("authors", counts["authors"], 0.5, "authors"),
                ("author_institutions", counts["author_institutions"], 0.5, "author institutions"),
            ],
            recommended_fetch_args={"include": ["authors"]},
        ),
        _tool_status(
            "analysis.author_landscape",
            total,
            checks=[
                ("authors", counts["authors"], 0.5, "authors"),
            ],
            recommended_fetch_args={"include": ["authors"]},
        ),
        _tool_status(
            "analysis.coword",
            total,
            checks=[
                ("title_or_abstract", max(counts["title"], counts["abstract"]), 0.8, "titles or abstracts"),
            ],
            recommended_fetch_args={},
        ),
        _tool_status(
            "analysis.topic_landscape",
            total,
            checks=[
                ("topics", counts["topics"], 0.3, "OpenAlex topics"),
                ("title_or_abstract", max(counts["title"], counts["abstract"]), 0.8, "titles or abstracts"),
            ],
            recommended_fetch_args={},
        ),
        _tool_status(
            "analysis.topic_modeling",
            total,
            checks=[
                ("title_or_abstract", max(counts["title"], counts["abstract"]), 0.8, "titles or abstracts"),
            ],
            recommended_fetch_args={},
        ),
        _tool_status(
            "analysis.citation_overview",
            total,
            checks=[
                ("referenced_works", counts["referenced_works"], 0.5, "referenced works"),
            ],
            recommended_fetch_args={"include": ["references"]},
        ),
    ]

    return {
        "overview": {"total_papers": total},
        "field_coverage": coverage,
        "tools": tools,
    }


def _tool_status(
    name: str,
    total: int,
    *,
    checks: list[tuple[str, int, float, str]],
    recommended_fetch_args: dict[str, Any],
) -> dict[str, Any]:
    missing = []
    warnings = []
    for field, count, threshold, label in checks:
        coverage = count / total if total else 0
        if count == 0:
            missing.append(label)
        elif coverage < threshold:
            warnings.append(f"low {label} coverage ({round(coverage * 100, 1)}%)")

    if missing:
        status = "missing"
        message = "Missing " + ", ".join(missing)
    elif warnings:
        status = "warning"
        message = "; ".join(warnings)
    else:
        status = "ready"
        message = "Ready"

    return {
        "tool": name,
        "status": status,
        "message": message,
        "recommended_fetch_args": recommended_fetch_args,
    }


def _summary_markdown(data: dict[str, Any], *, resolved_path: str) -> str:
    lines = [
        "# Analysis Readiness",
        "",
        f"Dataset: `{resolved_path}`",
        "",
        f"- Papers: {data['overview']['total_papers']}",
        "",
        "## Tool Status",
    ]
    for row in data["tools"]:
        lines.append(f"- {row['tool']}: {row['status']} - {row['message']}")
    lines.extend(["", "## Field Coverage"])
    for row in data["field_coverage"]:
        lines.append(f"- {row['field']}: {row['coverage']}% ({row['records']} records)")
    return "\n".join(lines)
