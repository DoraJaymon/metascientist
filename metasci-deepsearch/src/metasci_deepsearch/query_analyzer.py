"""Query Analyzer — converts research questions to structured search elements.

Ported from AcaDeepR/src/tools/query_analyzer/query_analyzer.py.
Removed: light-agent imports and TOOL registration decorator.
LLM interface: uses openai-compatible API via OPENAI_API_KEY + OPENAI_BASE_URL env vars.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

logger = logging.getLogger(__name__)

_PROMPTS_PATH = Path(__file__).parent / "query_analyzer_prompts.yaml"


def _load_prompts() -> Dict[str, Any]:
    with open(_PROMPTS_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


class QueryAnalyzer:
    """Parses a research question into structured search elements.

    Calls an LLM (OpenAI-compatible) to extract:
    - core_keywords: compact keyword string for academic search
    - criteria: weighted evaluation criteria list
    - (expand mode) unique/expanded/synonyms variants
    """

    VALID_KEYS = {"core_keywords", "reasoning", "unique_keywords", "expanded_keywords", "synonyms"}
    LIST_KEYS = {"expanded_keywords", "synonyms"}
    CRITERION_PATTERN = re.compile(r"^\s*[-*]\s*\[(?P<weight>[\d\.]+)\]\s*(?P<text>.+)$")

    def __init__(self, model: Optional[str] = None, prompts_path: Optional[str] = None) -> None:
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.prompts = _load_prompts() if prompts_path is None else yaml.safe_load(
            open(prompts_path, encoding="utf-8")
        )
        self._client = None  # lazy

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=os.getenv("OPENAI_API_KEY"),
                base_url=os.getenv("OPENAI_BASE_URL"),
            )
        return self._client

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        stripped = text.strip()
        if not stripped.startswith("```"):
            return stripped
        parts = stripped.splitlines()
        if len(parts) < 2:
            return stripped
        if parts[-1].strip().startswith("```"):
            return "\n".join(parts[1:-1]).strip()
        return "\n".join(parts[1:]).strip()

    async def _call_llm(self, prompt_key: str, **kwargs) -> str:
        cfg = self.prompts[prompt_key]
        system_msg = cfg["system"]
        user_msg = cfg["user"].format(**kwargs)
        client = self._get_client()
        resp = await client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
        )
        return resp.choices[0].message.content.strip()

    def _parse_keywords_response(self, content: str) -> Dict[str, Union[str, List[str]]]:
        content = self._strip_code_fence(content)
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError:
            data = None
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                data = None
        if isinstance(data, dict):
            parsed: Dict[str, Union[str, List[str]]] = {}
            for key, value in data.items():
                if key not in self.VALID_KEYS:
                    continue
                if key in self.LIST_KEYS:
                    if isinstance(value, list):
                        parsed[key] = [str(v).strip() for v in value if str(v).strip()]
                    else:
                        parsed[key] = [v.strip() for v in str(value).split(",") if v.strip()]
                else:
                    parsed[key] = str(value).strip()
            if parsed:
                return parsed
        # Line-by-line fallback
        result: Dict[str, Union[str, List[str]]] = {}
        for line in content.strip().split("\n"):
            line = line.strip()
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            if key not in self.VALID_KEYS:
                continue
            if key in self.LIST_KEYS:
                result[key] = [v.strip() for v in value.split(",") if v.strip()]
            else:
                result[key] = value.strip()
        return result

    def _parse_criteria_response(self, content: str) -> List[Dict[str, Any]]:
        content = self._strip_code_fence(content)
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError:
            data = None
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                data = None

        candidates: Any = None
        if isinstance(data, dict):
            candidates = data.get("criteria")
        elif isinstance(data, list):
            candidates = data

        if isinstance(candidates, list):
            criteria: List[Dict[str, Any]] = []
            total_w = 0.0
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text") or item.get("description") or "").strip()
                try:
                    w = float(item.get("weight") or 0.0)
                except (TypeError, ValueError):
                    w = 0.0
                if not text or w <= 0:
                    continue
                criteria.append({"text": text, "weight": w})
                total_w += w
            if criteria:
                norm = total_w if total_w > 0 else 1.0
                for c in criteria:
                    c["weight"] = round(c["weight"] / norm, 4)
                return criteria

        # Line-by-line fallback: - [0.35] description
        criteria = []
        total_w = 0.0
        for line in content.strip().splitlines():
            m = self.CRITERION_PATTERN.match(line)
            if not m:
                continue
            try:
                w = float(m.group("weight"))
            except (TypeError, ValueError):
                w = 0.0
            text = m.group("text").strip()
            if not text or w <= 0:
                continue
            criteria.append({"text": text, "weight": w})
            total_w += w
        if not criteria:
            raise ValueError("Could not parse any evaluation criteria from LLM response.")
        norm = total_w if total_w > 0 else 1.0
        for c in criteria:
            c["weight"] = round(c["weight"] / norm, 4)
        return criteria

    async def analyze(self, query: str, mode: str = "simple") -> Dict[str, Any]:
        """Analyze a research query.

        Args:
            query: Natural-language research question.
            mode: ``"simple"`` (keywords + criteria) or ``"expand"``
                  (adds unique/expanded/synonyms variants).

        Returns:
            Dict with ``criteria`` list and keyword fields.
        """
        if mode not in ("simple", "expand"):
            raise ValueError(f"Invalid mode '{mode}'. Use 'simple' or 'expand'.")

        keyword_raw = await self._call_llm("keywords", query=query)
        keyword_result = self._parse_keywords_response(keyword_raw)
        core_keywords = str(keyword_result.get("core_keywords", "")).strip()
        keyword_reasoning = str(keyword_result.get("reasoning", "")).strip() or "N/A"

        criteria_raw = await self._call_llm(
            "criteria",
            query=query,
            core_keywords=core_keywords,
            keyword_reasoning=keyword_reasoning,
        )
        criteria = self._parse_criteria_response(criteria_raw)

        if mode == "simple":
            return {"criteria": criteria, **keyword_result}

        expand_raw = await self._call_llm("expand", query=query, core_keywords=core_keywords)
        expand_result = self._parse_keywords_response(expand_raw)
        return {
            "criteria": criteria,
            "core_keywords": core_keywords,
            "reasoning": keyword_result.get("reasoning", ""),
            **expand_result,
        }
