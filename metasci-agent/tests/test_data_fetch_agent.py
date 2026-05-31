from __future__ import annotations

import asyncio

from light_agent.core.message import ChatMessage

from metasci_agent.agents.data_fetch_agent import DataFetchAgent
from metasci_agent.tools import metasci_tools
from metasci_universe.schemas.common import MetaSciResult

from fakes import ScriptedModel, tool_call


def test_data_fetch_agent_can_call_direct_data_tool_and_finish(monkeypatch) -> None:
    async def fake_search(**kwargs):
        return MetaSciResult(
            command="works.search",
            input=kwargs,
            data=[{"id": "W1", "title": "Science of Science"}],
            artifacts={"papers_json": "metasci_outputs/example/papers.json"},
            metadata={"provider": "openalex", "returned_count": 1},
        )

    monkeypatch.setattr(metasci_tools.ms.works, "search", fake_search)

    model = ScriptedModel(
        [
            ChatMessage(
                role="assistant",
                content="I will fetch works directly.",
                tool_calls=[
                    tool_call(
                        "metasci_search_works",
                        {"query": "science of science", "limit": 1},
                        "call_1",
                    )
                ],
            ),
            ChatMessage(
                role="assistant",
                content="I can answer now.",
                tool_calls=[
                    tool_call(
                        "final_answer",
                        {"answer": "Fetched 1 work and saved metasci_outputs/example/papers.json."},
                        "call_2",
                    )
                ],
            ),
        ]
    )
    agent = DataFetchAgent(model=model, verbose=False)
    answer = asyncio.run(agent.run("Get one paper about science of science."))
    assert "Fetched 1 work" in answer
    assert len(model.calls) == 2
    tool_names = [tool.name for tool in model.calls[0]["tools"]]
    assert "metasci_search_works" in tool_names
    assert "metasci_list_tools" not in tool_names
