from __future__ import annotations

import asyncio

from metasci_agent.workflows import create_direct_tool_workflow


def test_direct_workflow_reports_invalid_schema_without_network() -> None:
    workflow = create_direct_tool_workflow()
    try:
        asyncio.run(workflow({"tool_name": "metasci_search_works", "arguments": {}}))
    except RuntimeError as exc:
        assert "works.search requires at least one search or filter constraint" in str(exc)
    else:
        raise AssertionError("workflow should have raised on invalid schema")
