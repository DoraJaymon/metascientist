"""SavedDataset loading and inspection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SavedDataset:
    """A saved MetaSci dataset artifact."""

    def __init__(
        self,
        *,
        records: Any,
        path: Path,
        schema_name: str = "unknown",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.records = records
        self.path = path
        self.schema_name = schema_name
        self.metadata = metadata or {}

    @classmethod
    def load(cls, path: str | Path) -> "SavedDataset":
        """Load a dataset from a data file or dataset directory."""
        input_path = Path(path).expanduser()
        if input_path.is_dir():
            metadata_path = input_path / "metadata.json"
            metadata = cls._load_json(metadata_path) if metadata_path.exists() else {}
            data_file = metadata.get("data_file") or cls._guess_data_file(input_path)
            data_path = input_path / data_file
        else:
            data_path = input_path
            metadata_path = input_path.parent / "metadata.json"
            metadata = cls._load_json(metadata_path) if metadata_path.exists() else {}

        records = cls._load_json(data_path)
        return cls(
            records=records,
            path=data_path,
            schema_name=metadata.get("schema_name", "unknown"),
            metadata=metadata,
        )

    def info(self) -> dict[str, Any]:
        """Return compact metadata about the dataset."""
        if isinstance(self.records, list):
            record_count = len(self.records)
        elif self.records is None:
            record_count = 0
        else:
            record_count = 1

        return {
            "path": str(self.path),
            "schema_name": self.schema_name,
            "record_count": record_count,
            "metadata": self.metadata.get("metadata", self.metadata),
            "diagnostics": self.metadata.get("diagnostics", []),
        }

    def save(self, path: str | Path) -> Path:
        """Save records to a JSON file."""
        output_path = Path(path).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(self.records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return output_path

    @staticmethod
    def _load_json(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _guess_data_file(directory: Path) -> str:
        for filename in ("papers.json", "authors.json", "data.json"):
            if (directory / filename).exists():
                return filename
        raise FileNotFoundError(f"No known dataset data file found in {directory}")
