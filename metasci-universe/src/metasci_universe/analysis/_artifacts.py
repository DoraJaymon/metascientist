"""Artifact writing helpers for analysis results."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from metasci_universe.storage.output_writer import DEFAULT_OUTPUT_DIR


def save_analysis_artifacts(
    *,
    command: str,
    input_payload: dict[str, Any],
    data: dict[str, Any],
    summary_markdown: str,
    tables: Mapping[str, Any] | None = None,
    figures: Mapping[str, Any] | None = None,
    output_dir: str | Path | None = None,
    diagnostics: list[str] | None = None,
) -> dict[str, str]:
    """Save JSON, markdown, CSV, and HTML artifacts for an analysis command."""
    artifact_dir = _analysis_dir(command=command, input_payload=input_payload, output_dir=output_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    artifacts: dict[str, str] = {"analysis_dir": str(artifact_dir)}

    analysis_path = artifact_dir / "analysis.json"
    analysis_payload = {
        "command": command,
        "input": input_payload,
        "data": data,
        "diagnostics": diagnostics or [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    analysis_path.write_text(json.dumps(analysis_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifacts["analysis_json"] = str(analysis_path)

    summary_path = artifact_dir / "summary.md"
    summary_path.write_text(summary_markdown.rstrip() + "\n", encoding="utf-8")
    artifacts["summary_md"] = str(summary_path)

    for name, table in (tables or {}).items():
        csv_path = artifact_dir / _safe_filename(name, "csv")
        _table_to_dataframe(table).to_csv(csv_path, index=False)
        artifacts[f"{_artifact_key(name)}_csv"] = str(csv_path)

    for name, figure in (figures or {}).items():
        html_path = artifact_dir / _safe_filename(name, "html")
        if hasattr(figure, "write_html"):
            figure.write_html(str(html_path), include_plotlyjs="cdn", full_html=True)
        else:
            html_path.write_text(
                "<html><body><pre>" + json.dumps({"figure": str(figure)}, ensure_ascii=False, indent=2) + "</pre></body></html>",
                encoding="utf-8",
            )
        artifacts[f"{_artifact_key(name)}_html"] = str(html_path)

    return artifacts


def _analysis_dir(*, command: str, input_payload: dict[str, Any], output_dir: str | Path | None) -> Path:
    stable_json = json.dumps(input_payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha1(stable_json.encode("utf-8")).hexdigest()[:12]
    slug = _slugify(_slug_source(input_payload) or command.replace(".", "-"))
    return Path(output_dir or DEFAULT_OUTPUT_DIR).expanduser() / f"analysis_{slug}_{digest}"


def _slug_source(input_payload: dict[str, Any]) -> str:
    dataset_path = input_payload.get("dataset_path")
    if dataset_path:
        return Path(str(dataset_path)).stem
    return ""


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80]


def _safe_filename(name: str, extension: str) -> str:
    return f"{_slugify(name) or 'artifact'}.{extension}"


def _artifact_key(name: str) -> str:
    return _slugify(name).replace("-", "_")


def _table_to_dataframe(table: Any) -> pd.DataFrame:
    if isinstance(table, pd.DataFrame):
        return table
    if isinstance(table, list):
        return pd.DataFrame(table)
    if isinstance(table, dict):
        return pd.DataFrame([table])
    return pd.DataFrame([{"value": table}])
