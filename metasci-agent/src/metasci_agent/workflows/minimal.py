"""Minimal workflow builders."""

from __future__ import annotations

from typing import Any

from metasci_agent.tools.metasci_tools import get_metasci_agent_tool


class DirectMetaSciToolWorkflow:
    """One-node workflow that executes one direct MetaSci agent tool."""

    name = "metasci_direct_tool_workflow"

    async def __call__(self, input_data: dict[str, Any] | str) -> str:
        if not isinstance(input_data, dict):
            raise TypeError("DirectMetaSciToolWorkflow expects a dict with tool_name and arguments")
        tool_name = input_data.get("tool_name")
        arguments = input_data.get("arguments", {})
        if not isinstance(tool_name, str):
            raise TypeError("DirectMetaSciToolWorkflow requires a string tool_name")
        if not isinstance(arguments, dict):
            raise TypeError("DirectMetaSciToolWorkflow requires a dict arguments payload")

        tool = get_metasci_agent_tool(tool_name)
        result = await tool.forward(**arguments)
        if result.error:
            raise RuntimeError(result.error)
        return str(result.output)


def create_direct_tool_workflow() -> DirectMetaSciToolWorkflow:
    """Create a workflow that expects {'tool_name': 'metasci_search_works', 'arguments': {...}}."""
    return DirectMetaSciToolWorkflow()
