"""CiteFlow — deep literature search as composable, agent-native tools.

The package exposes atomic ``cf.*`` tools (query analysis, keyword search, citation
graph expansion, LLM seed selection, scoring, ranking, evaluation).  No tool encodes a
workflow; strategies live as recipe documents in the ``metasci-citeflow`` skill, so a
new method can be added without touching Python.
"""

from metasci_citeflow.deps import CiteFlowDeps
from metasci_citeflow.profiles import PROFILES, CiteFlowProfile, list_profiles, resolve
from metasci_citeflow.registry import TOOLS, describe_tool, list_tools, run_tool, tool_schema
from metasci_citeflow.session import Session

__all__ = [
    "CiteFlowDeps",
    "CiteFlowProfile",
    "PROFILES",
    "Session",
    "TOOLS",
    "describe_tool",
    "list_profiles",
    "list_tools",
    "resolve",
    "run_tool",
    "tool_schema",
]
