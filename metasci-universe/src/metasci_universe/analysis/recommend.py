"""Agent-facing analysis preflight helpers."""

from __future__ import annotations

from typing import Any

from metasci_universe.analysis import _normalize as norm
from metasci_universe.analysis._dataset import load_records
from metasci_universe.analysis.readiness import _inspect
from metasci_universe.schemas.analysis import AnalysisRecommendationRequest
from metasci_universe.schemas.common import MetaSciResult


INTENT_TOOLS: dict[str, list[str]] = {
    "auto": ["analysis.bibliometrics", "analysis.topic_landscape"],
    "bibliometrics": ["analysis.bibliometrics"],
    "macro": ["analysis.macro"],
    "author_landscape": ["analysis.author_landscape"],
    "coword": ["analysis.coword"],
    "topic_modeling": ["analysis.topic_modeling"],
    "topic_landscape": ["analysis.topic_landscape"],
    "citation_overview": ["analysis.citation_overview"],
    "science_landscape": [
        "analysis.bibliometrics",
        "analysis.macro",
        "analysis.author_landscape",
        "analysis.topic_landscape",
        "analysis.citation_overview",
    ],
}


async def preflight(
    dataset_path: str,
    *,
    intent: str = "auto",
    output_dir: str | None = None,
) -> MetaSciResult:
    """Inspect a saved dataset and return runnable tools, gaps, and safe defaults."""
    return await _build_preflight(
        dataset_path,
        intent=intent,
        output_dir=output_dir,
        command="analysis.preflight",
    )


async def recommend(
    dataset_path: str,
    *,
    intent: str = "auto",
    output_dir: str | None = None,
) -> MetaSciResult:
    """Compatibility alias for preflight."""
    return await _build_preflight(
        dataset_path,
        intent=intent,
        output_dir=output_dir,
        command="analysis.recommend",
    )


async def _build_preflight(
    dataset_path: str,
    *,
    intent: str,
    output_dir: str | None,
    command: str,
) -> MetaSciResult:
    request = AnalysisRecommendationRequest(
        dataset_path=dataset_path,
        intent=intent,  # type: ignore[arg-type]
        output_dir=output_dir,
    )
    records, dataset_metadata, resolved_path = load_records(request.dataset_path)
    readiness = _inspect(records)
    tool_status = {row["tool"]: row for row in readiness["tools"]}
    requested_tools = INTENT_TOOLS[request.intent]
    recommended_tools = [tool for tool in requested_tools if tool_status.get(tool, {}).get("status") != "missing"]
    blocked_tools = [tool for tool in requested_tools if tool_status.get(tool, {}).get("status") == "missing"]
    warnings = [
        f"{tool}: {tool_status[tool]['message']}"
        for tool in requested_tools
        if tool in tool_status and tool_status[tool]["status"] == "warning"
    ]
    fetch_args = _merge_fetch_args(tool_status.get(tool, {}).get("recommended_fetch_args", {}) for tool in blocked_tools)

    safe_defaults = _safe_defaults(records)
    data = {
        "overview": {
            "intent": request.intent,
            "total_papers": len(records),
            "recommended_tools": recommended_tools,
            "blocked_tools": blocked_tools,
        },
        "readiness": readiness,
        "safe_defaults": safe_defaults,
        "suggested_fetch_args": fetch_args,
        "warnings": warnings,
    }
    diagnostics = []
    if blocked_tools:
        diagnostics.append(
            "Some requested tools are missing required fields. Re-run data retrieval with suggested_fetch_args."
        )
    diagnostics.extend(warnings)
    return MetaSciResult(
        command=command,
        input=request.model_dump(mode="json"),
        data=data,
        metadata={
            "record_count": len(records),
            "dataset_path": resolved_path,
            "dataset_schema": dataset_metadata.get("schema_name"),
            "intent": request.intent,
        },
        diagnostics=diagnostics,
    )


def _safe_defaults(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Return dependency-light defaults that agents can reuse in composed workflows."""
    total = len(records)
    text_count = sum(1 for work in records if norm.title(work) or norm.abstract_text(work))
    topic_count = sum(1 for work in records if norm.topics(work))
    reference_count = sum(1 for work in records if norm.referenced_works(work))
    small_dataset = total < 100
    min_count = 1 if small_dataset else 2
    return {
        "text_backend": "sklearn",
        "modeling_backend": "sklearn_lda",
        "topic_landscape_methods": _topic_landscape_methods(text_count=text_count, topic_count=topic_count),
        "min_count": min_count,
        "min_term_count": min_count,
        "min_edge_weight": min_count,
        "nr_topics": 2 if total < 20 else None,
        "max_docs": 2000 if total > 2000 else None,
        "include_reference_frequency": reference_count > 0,
        "author_landscape_min_papers": 1 if total < 500 else 2,
    }


def _topic_landscape_methods(*, text_count: int, topic_count: int) -> list[str]:
    methods: list[str] = []
    if topic_count:
        methods.append("openalex_topics")
    if text_count:
        methods.extend(["coword", "topic_modeling"])
    return methods or ["coword"]


def _merge_fetch_args(items) -> dict[str, Any]:
    include: set[str] = set()
    for item in items:
        include.update(item.get("include", []))
    return {"include": sorted(include)} if include else {}
