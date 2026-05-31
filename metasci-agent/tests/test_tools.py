from __future__ import annotations

import asyncio

from metasci_agent.tools import metasci_tools
from metasci_agent.tools.metasci_tools import (
    MetaSciFetchConferencePapersTool,
    MetaSciSearchWorksTool,
    list_metasci_agent_tool_names,
)
from metasci_universe.schemas.common import MetaSciResult


def test_direct_tool_names_are_business_actions() -> None:
    names = list_metasci_agent_tool_names()
    assert "metasci_search_works" in names
    assert "metasci_fetch_conference_papers" in names
    assert "metasci_search_authors" in names
    assert "metasci_list_tools" not in names
    assert "metasci_describe_tool" not in names


def test_search_works_adapter_calls_public_api(monkeypatch) -> None:
    async def fake_search(**kwargs):
        return MetaSciResult(
            command="works.search",
            input=kwargs,
            data=[{"id": "W1", "title": "Science of Science"}],
            artifacts={"papers_json": "metasci_outputs/example/papers.json"},
            metadata={"provider": "openalex", "returned_count": 1, "filtered_total": 10},
        )

    monkeypatch.setattr(metasci_tools.ms.works, "search", fake_search)

    result = asyncio.run(MetaSciSearchWorksTool().forward(query="science of science", limit=1))
    assert result.success
    assert result.structured_output["command"] == "works.search"
    assert result.structured_output["metadata"]["returned_count"] == 1
    assert result.structured_output["preview_works"][0]["title"] == "Science of Science"
    assert result.artifacts["papers_json"].endswith("papers.json")


def test_fetch_conference_papers_adapter_calls_public_api(monkeypatch) -> None:
    async def fake_papers(**kwargs):
        return MetaSciResult(
            command="conferences.papers",
            input=kwargs,
            data=[{"id": "acl:2024.acl-long.1", "title": "A Language Paper"}],
            artifacts={"data_file": "metasci_outputs/example/papers.json"},
            metadata={"provider": "acl", "returned_count": 1, "filtered_total": 2},
        )

    monkeypatch.setattr(metasci_tools.ms.conferences, "papers", fake_papers)

    result = asyncio.run(MetaSciFetchConferencePapersTool().forward(venue="acl", year=2024, source="acl", limit=1))
    assert result.success
    assert result.structured_output["command"] == "conferences.papers"
    assert result.structured_output["metadata"]["provider"] == "acl"
    assert result.structured_output["preview_works"][0]["title"] == "A Language Paper"
    assert result.artifacts["data_file"].endswith("papers.json")
