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

    def save_text_artifact(
        self,
        *,
        kind: str,
        command: str,
        input_payload: dict[str, Any],
        filename: str,
        content: str,
        metadata: dict[str, Any],
        diagnostics: list[str],
        extra_files: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """Save a text artifact plus metadata, returning artifact paths."""
        artifact_dir = self._dataset_dir(kind=kind, input_payload=input_payload)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        text_path = artifact_dir / filename
        metadata_path = artifact_dir / "metadata.json"

        text_path.write_text(content, encoding="utf-8")
        extra_file_names: list[str] = []
        extra_artifacts: dict[str, str] = {}
        for extra_filename, extra_content in (extra_files or {}).items():
            extra_path = artifact_dir / extra_filename
            extra_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(extra_content, bytes):
                extra_path.write_bytes(extra_content)
            elif isinstance(extra_content, str):
                extra_path.write_text(extra_content, encoding="utf-8")
            else:
                extra_path.write_text(
                    json.dumps(extra_content, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            extra_file_names.append(extra_filename)
            extra_artifacts[self._artifact_key(extra_filename)] = str(extra_path)

        metadata_payload = {
            "schema_name": kind,
            "command": command,
            "input": input_payload,
            "metadata": metadata,
            "diagnostics": diagnostics,
            "data_file": filename,
            "extra_files": extra_file_names,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        metadata_path.write_text(
            json.dumps(metadata_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {
            "artifact_dir": str(artifact_dir),
            "text_file": str(text_path),
            "metadata_file": str(metadata_path),
            **extra_artifacts,
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

    def _artifact_key(self, filename: str) -> str:
        path = Path(filename)
        stem = self._slugify(path.stem).replace("-", "_") or "extra"
        suffix = path.suffix.lower().lstrip(".")
        if suffix == "pdf":
            return "pdf_file"
        if suffix:
            return f"{stem}_file"
        return stem
