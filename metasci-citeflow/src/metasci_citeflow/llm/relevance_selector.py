"""Relevance judging — marking candidate *target* papers.

Distinct from seed selection.  A seed is a paper worth expanding the graph *from*; a
judged paper is a candidate *answer* to the query.  The prompt is deliberately strict
("quality over quantity", at most 4 per batch, empty is acceptable) because the judged
set feeds a rank boost — marking everything would boost nothing.

Note the original has no per-paper 0-1 relevance score.  Judged papers are a **set**;
their only effect on ranking is a flat +0.1 on ``importance_score``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from metasci_citeflow.llm.client import load_prompts
from metasci_citeflow.llm.parsers import parse_indexed_selection, select_by_indices

logger = logging.getLogger(__name__)

PROMPTS_FILE = "relevance_selector_prompts.yaml"
ABSTRACT_CHARS = 500


def format_keywords_block(structured_keywords: Sequence[Sequence[str]]) -> str:
    """Render structured keywords as ``- head + modifier`` lines."""
    if not structured_keywords:
        return "No structured keywords provided."
    lines = []
    for group in structured_keywords:
        parts = [str(part).strip() for part in group if str(part).strip()]
        if parts:
            lines.append("- " + " + ".join(parts))
    return "\n".join(lines) if lines else "No structured keywords provided."


def format_papers_block(papers: Sequence[Dict[str, Any]]) -> str:
    """1-indexed candidate list. Note the label is 'Citations:', unlike the seed prompt."""
    lines: List[str] = []
    for index, paper in enumerate(papers, start=1):
        citations = (
            paper.get("citation_count") or paper.get("cited_by_count") or 0
        )
        lines.append(f"{index}. {paper.get('title') or 'Untitled'}")
        lines.append(f"   Citations: {citations}")
        abstract = (paper.get("abstract") or "").strip()
        if abstract:
            if len(abstract) > ABSTRACT_CHARS:
                abstract = abstract[:ABSTRACT_CHARS] + "..."
            lines.append(f"   Abstract: {abstract}")
        lines.append("")
    return "\n".join(lines)


class RelevanceSelector:
    """One LLM call marking which candidates plausibly answer the query."""

    def __init__(self, llm: Any, model: Optional[str] = None, temperature: float = 0.5) -> None:
        self.llm = llm
        self.model = model
        self.temperature = temperature
        self.prompts = load_prompts(PROMPTS_FILE)

    async def select(
        self,
        query: str,
        papers: Sequence[Dict[str, Any]],
        *,
        structured_keywords: Optional[Sequence[Sequence[str]]] = None,
    ) -> Dict[str, Any]:
        if not papers:
            return {"reasoning": "", "selected_indices": [], "selected_papers": []}

        config = self.prompts["relevance_selection"]
        raw = await self.llm.complete(
            system=config["system"],
            user=config["user"].format(
                query=query,
                keywords_block=format_keywords_block(structured_keywords or []),
                papers_block=format_papers_block(papers),
            ),
            model=self.model,
            temperature=self.temperature,
            prompt_key="relevance_selection",
        )

        parsed = parse_indexed_selection(raw)
        parsed["selected_papers"] = select_by_indices(list(papers), parsed["selected_indices"])
        return parsed


async def judge_batches(
    selector: RelevanceSelector,
    query: str,
    papers: Sequence[Dict[str, Any]],
    *,
    batches: Sequence[Sequence[int]] = ((0, 15), (15, 30)),
    structured_keywords: Optional[Sequence[Sequence[str]]] = None,
) -> Dict[str, Any]:
    """Judge the top candidates in fixed slices.

    Two calls of 15 rather than one of 30: the prompt caps selections at 4, so a single
    large batch would force the model to discard good candidates it cannot report.
    """
    selected: List[Dict[str, Any]] = []
    reasoning: List[str] = []
    judged_ids: List[str] = []  # ordered: rank position carries the judge's preference
    seen = set()

    for start, end in batches:
        slice_ = list(papers[start:end])
        if not slice_:
            continue
        result = await selector.select(
            query, slice_, structured_keywords=structured_keywords
        )
        if result.get("reasoning"):
            reasoning.append(result["reasoning"])
        for paper in result.get("selected_papers", []):
            key = paper.get("openalex_id") or paper.get("corpus_id")
            if key and key not in seen:
                seen.add(key)
                judged_ids.append(key)
                selected.append(paper)

    return {"selected_papers": selected, "reasoning": reasoning, "judged_ids": judged_ids}
