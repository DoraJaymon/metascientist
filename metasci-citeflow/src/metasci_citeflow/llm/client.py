"""OpenAI-compatible chat client.

The original ran through light_agent's ``OpenAIModel`` against an OpenAI-compatible
gateway (the batch configs point at ``gemini-flash-latest`` model ids).  This is the
same contract with the framework dependency removed.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).parent


def load_prompts(filename: str) -> Dict[str, Any]:
    with open(PROMPT_DIR / filename, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def default_model() -> str:
    return os.getenv("CITEFLOW_MODEL") or os.getenv("OPENAI_MODEL") or "gemini-2.5-flash"


class OpenAICompatibleClient:
    """Thin async wrapper over the OpenAI chat-completions API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        client: Any = None,
    ) -> None:
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._base_url = (
            base_url
            or os.getenv("OPENAI_BASE_URL")
            or os.getenv("OPENAI_API_BASE_URL")
        )
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            from openai import AsyncOpenAI

            if not self._api_key:
                raise RuntimeError(
                    "OPENAI_API_KEY is not set; CiteFlow needs it for query analysis, "
                    "seed selection, relevance judging and expansion-parameter decisions."
                )
            self._client = AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)
        return self._client

    async def complete(
        self,
        *,
        system: str,
        user: str,
        model: Optional[str] = None,
        temperature: float = 0.5,
        history: Optional[Sequence[Dict[str, str]]] = None,
        prompt_key: str = "",
    ) -> str:
        """Return the assistant reply.

        When ``history`` is supplied the new user turn is appended to it rather than
        starting a fresh conversation — the query analyzer relies on this so its later
        turns can refer back to the keywords it already extracted.
        """
        if history:
            messages: List[Dict[str, str]] = [dict(message) for message in history]
            messages.append({"role": "user", "content": user})
        else:
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]

        response = await self._get_client().chat.completions.create(
            model=model or default_model(),
            messages=messages,
            temperature=temperature,
        )
        content = response.choices[0].message.content or ""
        return content.strip()
