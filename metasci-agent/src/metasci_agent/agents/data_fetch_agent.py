"""MetaSci data-fetch agent with direct MetaSci Universe tools."""

from __future__ import annotations

from pathlib import Path

from light_agent.core.base_agent import BaseAgent
from light_agent.core.tool import AsyncTool, ToolResult
from light_agent.models.base import BaseModel as BaseModelInterface

from metasci_agent.prompts import metasci_react_system_prompt
from metasci_agent.tools.metasci_tools import metasci_agent_tools


class MetaSciFinalAnswerTool(AsyncTool):
    """Local final-answer tool without importing optional light-agent tool bundles."""

    name: str = "final_answer"
    description: str = "Use this tool to provide the final answer and complete the task."
    parameters: dict = {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "description": "The final answer to the user's task.",
            }
        },
        "required": ["answer"],
    }

    async def forward(self, answer: str) -> ToolResult:
        return ToolResult(output=answer)


class DataFetchAgent(BaseAgent):
    """Agent that chooses among direct MetaSci Universe data-fetch tools."""

    def __init__(
        self,
        *,
        model: BaseModelInterface,
        skill_paths: list[str | Path] | None = None,
        max_steps: int = 8,
        verbose: bool = True,
    ) -> None:
        tools = metasci_agent_tools()
        tools.append(MetaSciFinalAnswerTool())

        super().__init__(
            mode="react",
            tools=tools,
            model=model,
            system_prompt=metasci_react_system_prompt(skill_paths),
            task_prompt="{{task}}",
            max_steps=max_steps,
            name="metasci_data_fetch_agent",
            verbose=verbose,
        )
