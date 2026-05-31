from __future__ import annotations

from typing import Any

from light_agent.core.message import ChatMessage, ToolCall
from light_agent.models.base import BaseModel


class ScriptedModel(BaseModel):
    """A deterministic light-agent model for ReAct smoke tests."""

    def __init__(self, responses: list[ChatMessage]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def generate(self, messages, tools=None, **kwargs) -> ChatMessage:
        self.calls.append({"messages": messages, "tools": tools})
        if not self.responses:
            return ChatMessage(role="assistant", content="No scripted response.")
        return self.responses.pop(0)


def tool_call(name: str, arguments: dict[str, Any], call_id: str = "call_1") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments)
