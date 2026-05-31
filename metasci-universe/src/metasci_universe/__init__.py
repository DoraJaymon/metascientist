"""Agent-native MetaSci Universe public API."""

from importlib import import_module
from typing import Any

from .tools.registry import describe_tool, list_tools, run_tool, tool_schema
from .storage.saved_dataset import SavedDataset
from .api import authors, conferences, works

Dataset = SavedDataset

__all__ = [
    "Dataset",
    "SavedDataset",
    "analysis",
    "authors",
    "conferences",
    "embeddings",
    "memory",
    "works",
    "describe_tool",
    "list_tools",
    "run_tool",
    "tool_schema",
    "workflows",
]


def __getattr__(name: str) -> Any:
    """Load optional heavier API namespaces only when requested."""
    if name == "analysis":
        return import_module("metasci_universe.analysis")
    if name == "embeddings":
        return import_module("metasci_universe.embeddings")
    if name == "memory":
        return import_module("metasci_universe.memory")
    if name == "workflows":
        return import_module("metasci_universe.workflows")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
