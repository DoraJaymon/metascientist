import asyncio
import json
from pathlib import Path

import metasci_universe as ms


DATASET_DIR = Path("metasci_outputs/nature_communications_llm_2025_2026_relevance")
OUTPUT_DIR = Path("metasci_outputs/analysis/nature_communications_llm_2025_2026_science_landscape")


def locate_papers_json(root: Path) -> Path:
    candidates = sorted(root.rglob("papers.json"))
    if not candidates:
        raise FileNotFoundError(f"No papers.json found under {root}")
    if len(candidates) > 1:
        raise RuntimeError(f"Multiple papers.json files found: {candidates}")
    return candidates[0]


async def main() -> None:
    dataset_path = locate_papers_json(DATASET_DIR)
    preflight = await ms.analysis.preflight(str(dataset_path), intent="science_landscape")
    safe_defaults = preflight.data["safe_defaults"]
    readiness = preflight.data["readiness"]
    field_coverage = {
        row["field"]: {
            "records": row["records"],
            "coverage": row["coverage"],
        }
        for row in readiness["field_coverage"]
    }

    result = await ms.workflows.science_landscape(
        str(dataset_path),
        output_dir=str(OUTPUT_DIR),
        top_n=30,
        text_backend="sklearn",
        modeling_backend="sklearn_lda",
        min_count=safe_defaults["min_count"],
        skip_unready=True,
    )

    requested = ["bibliometrics", "macro", "topic_landscape", "citation_overview"]
    run = result.data["overview"]["components_run"]
    skipped = [component for component in requested if component not in run]

    component_artifacts = {}
    for name, payload in result.data.get("components", {}).items():
        artifacts = payload.get("artifacts", {})
        component_artifacts[name] = artifacts

    summary = {
        "dataset_path": str(dataset_path),
        "output_dir": str(OUTPUT_DIR),
        "preflight": {
            "summary": preflight.summary(),
            "diagnostics": preflight.diagnostics,
            "recommended_tools": preflight.data["overview"]["recommended_tools"],
            "blocked_tools": preflight.data["overview"]["blocked_tools"],
            "suggested_fetch_args": preflight.data["suggested_fetch_args"],
            "warnings": preflight.data["warnings"],
            "safe_defaults": safe_defaults,
            "field_coverage": field_coverage,
        },
        "workflow": {
            "summary": result.summary(),
            "components_run": run,
            "components_skipped": skipped,
            "diagnostics": result.diagnostics,
            "artifacts": result.artifacts,
            "component_artifacts": component_artifacts,
            "metadata": result.metadata,
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
