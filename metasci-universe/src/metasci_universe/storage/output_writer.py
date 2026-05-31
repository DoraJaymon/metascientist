"""Artifact writing utilities for agent workflows."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = "metasci_outputs"


class OutputWriter:
    """Write dataset artifacts with stable metadata."""

    def __init__(self, output_dir: str | Path | None = None) -> None:
        self.output_dir = Path(output_dir or DEFAULT_OUTPUT_DIR).expanduser()

    def save_dataset(
        self,
        *,
        kind: str,
        command: str,
        input_payload: dict[str, Any],
        records: Any,
        metadata: dict[str, Any],
        diagnostics: list[str],
    ) -> dict[str, str]:
        """Save records and metadata, returning artifact paths."""
        dataset_dir = self._dataset_dir(kind=kind, input_payload=input_payload)
        dataset_dir.mkdir(parents=True, exist_ok=True)

        data_filename = self._data_filename(kind)
        data_path = dataset_dir / data_filename
        metadata_path = dataset_dir / "metadata.json"

        data_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        metadata_payload = {
            "schema_name": kind,
            "command": command,
            "input": input_payload,
            "metadata": metadata,
            "diagnostics": diagnostics,
            "data_file": data_filename,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        metadata_path.write_text(
            json.dumps(metadata_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        return {
            "dataset_dir": str(dataset_dir),
            "data_file": str(data_path),
            "metadata_file": str(metadata_path),
        }

    def _dataset_dir(self, *, kind: str, input_payload: dict[str, Any]) -> Path:
        stable_json = json.dumps(input_payload, ensure_ascii=False, sort_keys=True, default=str)
        digest = hashlib.sha1(stable_json.encode("utf-8")).hexdigest()[:12]
        slug = self._slugify(self._slug_source(input_payload)) or kind
        return self.output_dir / f"{kind}_{slug}_{digest}"

    def _slug_source(self, input_payload: dict[str, Any]) -> str:
        for key in (
            "venue",
            "query",
            "name",
            "identifier",
            "source_name",
            "topic_name",
            "author_name",
            "institution_name",
        ):
            value = input_payload.get(key)
            if value:
                if key == "venue" and input_payload.get("year"):
                    return f"{value}-{input_payload['year']}"
                return str(value)
        return ""

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9]+", "-", value.lower()).strip("-")
        return slug[:80]

    def _data_filename(self, kind: str) -> str:
        if kind == "works":
            return "papers.json"
        if kind in {"authors", "author"}:
            return "authors.json"
        return "data.json"
