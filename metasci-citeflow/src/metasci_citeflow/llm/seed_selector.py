"""LLM seed selection — deciding which papers to expand the citation graph from.

The judgement the prompt asks for is deliberately narrow: *would a paper that answers
this research question actually cite this one as a key reference?*  That is a much
stronger filter than topical similarity, and it is why seeds are chosen by an LLM rather
than by a score.  A plausible-but-wrong seed floods the store with a few hundred
off-topic references; the prompt therefore also states that returning an empty list is
acceptable.

Batching matters: the underlying prompt renders at most ``batch_size`` papers per call
(the original truncated silently at 10), so larger candidate pools are chunked.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from metasci_citeflow.llm.client import load_prompts
from metasci_citeflow.llm.parsers import parse_indexed_selection, select_by_indices

logger = logging.getLogger(__name__)

PROMPTS_FILE = "seed_selector_prompts_v2.yaml"
ABSTRACT_CHARS = 500


def citation_count(paper: Dict[str, Any]) -> int:
    for field in ("citation_count", "cited_by_count", "citationCount"):
        value = paper.get(field)
        if value:
            return int(value)
    return 0


def format_papers_block(papers: Sequence[Dict[str, Any]]) -> str:
    """Render candidates 1-indexed, matching the prompt's expected input shape."""
    lines: List[str] = []
    for index, paper in enumerate(papers, start=1):
        lines.append(f"{index}. {paper.get('title') or 'Untitled'}")
        lines.append(f"   Citation Count: {citation_count(paper)}")
        abstract = (paper.get("abstract") or "").strip()
        if abstract:
            if len(abstract) > ABSTRACT_CHARS:
                abstract = abstract[:ABSTRACT_CHARS] + "..."
            lines.append(f"   Abstract: {abstract}")
        lines.append("")
    return "\n".join(lines)


class SeedSelector:
    """One LLM call over one batch of candidate seeds."""

    def __init__(self, llm: Any, model: Optional[str] = None, temperature: float = 0.5) -> None:
        self.llm = llm
        self.model = model
        self.temperature = temperature
        self.prompts = load_prompts(PROMPTS_FILE)

    async def select(
        self, query: str, papers: Sequence[Dict[str, Any]], *, max_papers: int = 10
    ) -> Dict[str, Any]:
        if not papers:
            return {"reasoning": "No candidate papers provided.", "selected_indices": [], "selected_papers": []}

        candidates = list(papers[:max_papers])
        config = self.prompts["seed_selection"]
        raw = await self.llm.complete(
            system=config["system"],
            user=config["user"].format(query=query, papers_block=format_papers_block(candidates)),
            model=self.model,
            temperature=self.temperature,
            prompt_key="seed_selection",
        )

        parsed = parse_indexed_selection(raw)
        parsed["selected_papers"] = select_by_indices(candidates, parsed["selected_indices"])
        return parsed
