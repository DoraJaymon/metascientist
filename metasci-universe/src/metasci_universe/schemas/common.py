"""Shared schemas for MetaSci results and dataset helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MetaSciResult(BaseModel):
    """Structured result object returned by public package APIs."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    command: str
    input: dict[str, Any] = Field(default_factory=dict)
    data: Any = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[str] = Field(default_factory=list)

    def summary(self) -> str:
        """Return a compact human-readable summary."""
        parts = [f"Command: {self.command}"]

        returned_count = self.metadata.get("returned_count")
        if returned_count is not None:
            parts.append(f"Returned: {returned_count}")

        filtered_total = self.metadata.get("filtered_total")
        if filtered_total is not None:
            parts.append(f"Filtered total: {filtered_total}")

        provider = self.metadata.get("provider")
        if provider:
            parts.append(f"Provider: {provider}")

        for key, value in self.artifacts.items():
            parts.append(f"{key}: {value}")

        if self.diagnostics:
            parts.append("Diagnostics: " + "; ".join(self.diagnostics))

        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict."""
        return self.model_dump(mode="json")

    def to_json(self, path: str | Path | None = None, *, indent: int = 2) -> str:
        """Serialize to JSON, optionally writing the JSON envelope to disk."""
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
        if path is not None:
            output_path = Path(path).expanduser()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(payload + "\n", encoding="utf-8")
        return payload

    def to_markdown(self, path: str | Path | None = None) -> str:
        """Render a short markdown summary, optionally writing it to disk."""
        lines = [f"# {self.command}", "", self.summary()]
        if self.data is not None:
            lines.extend(["", "```json", json.dumps(self.data, ensure_ascii=False, indent=2), "```"])
        payload = "\n".join(lines) + "\n"
        if path is not None:
            output_path = Path(path).expanduser()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(payload, encoding="utf-8")
        return payload


class DatasetInfoRequest(BaseModel):
    """Request for dataset metadata inspection."""

    path: str
