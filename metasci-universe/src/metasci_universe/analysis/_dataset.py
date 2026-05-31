"""Dataset loading helpers for analysis tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from metasci_universe.storage.saved_dataset import SavedDataset


def load_records(dataset: str | Path | SavedDataset | list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    """Load records from a path, SavedDataset, or in-memory list."""
    if isinstance(dataset, SavedDataset):
        records = _as_records(dataset.records)
        return records, dataset.metadata, str(dataset.path)

    if isinstance(dataset, (str, Path)):
        saved = SavedDataset.load(dataset)
        records = _as_records(saved.records)
        return records, saved.metadata, str(saved.path)

    records = _as_records(dataset)
    return records, {}, "in_memory"


def _as_records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    raise TypeError("Analysis dataset must contain a list of records or a single record object.")
