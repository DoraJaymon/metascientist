"""Response parsers for the CiteFlow prompts.

Every prompt asks for a plain-text, line-oriented reply (``reasoning:`` followed by one
data line) rather than JSON.  That is deliberate in the original and is preserved here,
so the parsers must be forgiving: a malformed reply degrades to an empty result plus a
recorded parse error instead of raising, because an LLM hiccup should not abort a run
that has already spent hundreds of API calls building a store.
"""

from __future__ import annotations

import ast
from typing import Any, Dict, List, Tuple

FENCE_LANGS = {"yaml", "yml", "python", "py", "json", ""}


def strip_code_fence(text: str) -> str:
    """Remove a wrapping markdown code fence, if present."""
    stripped = (text or "").strip()
    if not stripped.startswith("```"):
        return stripped
    parts = stripped.splitlines()
    if len(parts) < 2:
        return stripped
    if parts[0].strip("`").lower() not in FENCE_LANGS:
        return stripped
    if parts[-1].strip().startswith("```"):
        return "\n".join(parts[1:-1]).strip()
    return "\n".join(parts[1:]).strip()


def parse_slot_keywords(content: str) -> Dict[str, Any]:
    """Parse ``reasoning:`` + ``core_keywords: [("a","b"), ("c",)]``.

    Returns ``core_keywords`` as a list of tuples.  Bare strings are promoted to
    one-element tuples; empty components are dropped.
    """
    content = strip_code_fence(content)
    result: Dict[str, Any] = {"reasoning": "", "core_keywords": []}

    for line in content.strip().split("\n"):
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()

        if key == "reasoning":
            result["reasoning"] = value
        elif key == "core_keywords":
            try:
                parsed = ast.literal_eval(value)
            except (ValueError, SyntaxError) as exc:
                result["core_keywords"] = []
                result["_parse_error"] = f"Failed to parse core_keywords: {value}"
                result["_error_detail"] = str(exc)
                continue

            if not isinstance(parsed, list):
                result["core_keywords"] = []
                continue

            normalised: List[Tuple[str, ...]] = []
            for item in parsed:
                if isinstance(item, (tuple, list)):
                    clean = tuple(str(part).strip() for part in item if str(part).strip())
                    if clean:
                        normalised.append(clean)
                elif isinstance(item, str) and item.strip():
                    normalised.append((item.strip(),))
            result["core_keywords"] = normalised

    return result


def parse_search_queries(content: str, *, max_queries: int = 5) -> Dict[str, Any]:
    """Parse a ``reasoning:`` line followed by one search query per line."""
    reasoning = ""
    queries: List[str] = []

    for line in strip_code_fence(content).strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("---"):
            continue
        if line.startswith("reasoning:"):
            reasoning = line.split(":", 1)[1].strip()
        elif reasoning or queries:
            queries.append(line.lower())

    return {"reasoning": reasoning, "queries": queries[:max_queries]}


def parse_discriminative_terms(content: str) -> Dict[str, Any]:
    """Parse ``reasoning`` + ``terms: {term: score}``, YAML first then line-by-line."""
    import yaml

    cleaned = strip_code_fence(content)
    try:
        data = yaml.safe_load(cleaned)
        if isinstance(data, dict) and "terms" in data:
            raw_terms = data.get("terms") or {}
            terms = {}
            if isinstance(raw_terms, dict):
                for term, score in raw_terms.items():
                    try:
                        terms[str(term).strip()] = int(score)
                    except (TypeError, ValueError):
                        continue
            return {"reasoning": str(data.get("reasoning", "") or ""), "terms": terms}
    except yaml.YAMLError:
        pass

    reasoning = ""
    terms: Dict[str, int] = {}
    in_terms = False
    for raw_line in cleaned.strip().split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("reasoning:"):
            reasoning = line.split(":", 1)[1].strip()
            in_terms = False
        elif line.startswith("terms:"):
            in_terms = True
        elif in_terms and ":" in line:
            term, _, score = line.partition(":")
            term = term.strip().lstrip("-").strip()
            try:
                terms[term] = int(score.strip())
            except ValueError:
                continue

    return {"reasoning": reasoning, "terms": terms}


def parse_indexed_selection(content: str) -> Dict[str, Any]:
    """Parse ``reasoning:`` + ``selected_indices: [1, 3, 5]`` (1-indexed).

    Used by both the seed selector and the relevance judge.  An unparseable or absent
    list yields an empty selection — the prompts explicitly allow selecting nothing.
    """
    result: Dict[str, Any] = {"reasoning": "", "selected_indices": []}

    for line in strip_code_fence(content).strip().split("\n"):
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()

        if key == "reasoning":
            result["reasoning"] = value
        elif key == "selected_indices":
            try:
                parsed = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                continue
            if isinstance(parsed, (list, tuple)):
                indices = []
                for item in parsed:
                    try:
                        indices.append(int(item))
                    except (TypeError, ValueError):
                        continue
                result["selected_indices"] = indices

    return result


def select_by_indices(items: List[Any], indices: List[int]) -> List[Any]:
    """Map 1-indexed LLM selections onto ``items``, dropping out-of-range values."""
    picked = []
    for index in indices:
        if 1 <= index <= len(items):
            picked.append(items[index - 1])
    return picked


def parse_key_values(content: str, keys: Dict[str, type]) -> Dict[str, Any]:
    """Parse simple ``key: value`` lines, coercing the listed keys.

    Later occurrences win, matching the original decider's line-by-line scan.
    """
    parsed: Dict[str, Any] = {}
    for line in strip_code_fence(content).strip().split("\n"):
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if key not in keys:
            continue
        caster = keys[key]
        if caster is str:
            parsed[key] = value
            continue
        try:
            parsed[key] = caster(value)
        except (TypeError, ValueError):
            continue
    return parsed
