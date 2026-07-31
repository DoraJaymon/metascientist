"""Choosing forward-expansion cut-offs from the shape of the current results.

Each round the LLM sees two distributions — how many citations the high-scoring papers
have, and what years they fall in — plus the seeds' total citation count, and picks a
``year_start`` and ``min_citations`` for the next forward fetch.  The point is
throughput control: seeds with 10,000 combined citations would return an unusable flood
at ``min_citations=0``, while a niche topic needs 0 to return anything at all.

The LLM's answer is always clamped in Python.  The prompt asks for ``min_citations <= 5``
but models drift, and an unclamped 50 would silently gut a round's recall.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Sequence

from metasci_citeflow.llm.client import load_prompts
from metasci_citeflow.llm.parsers import parse_key_values

logger = logging.getLogger(__name__)

PROMPTS_FILE = "citation_params_decider_prompts.yaml"

CITATION_BINS = ("0-50", "51-100", "101-500", "501-1000", "1000+")

YEAR_FLOOR = 2010
DEFAULT_YEAR_START = 2017
MIN_CITATIONS_CEILING = 5


def citation_distribution(papers: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """Bin papers by citation count. All bins are reported, including empty ones."""
    bins = {name: 0 for name in CITATION_BINS}
    for paper in papers:
        count = paper.get("cited_by_count") or paper.get("citation_count") or 0
        if count <= 50:
            bins["0-50"] += 1
        elif count <= 100:
            bins["51-100"] += 1
        elif count <= 500:
            bins["101-500"] += 1
        elif count <= 1000:
            bins["501-1000"] += 1
        else:
            bins["1000+"] += 1
    return bins


def year_distribution(papers: Sequence[Dict[str, Any]]) -> Dict[int, int]:
    counts: Dict[int, int] = {}
    for paper in papers:
        year = paper.get("publication_year") or paper.get("year")
        if year:
            counts[int(year)] = counts.get(int(year), 0) + 1
    return dict(sorted(counts.items()))


def format_distribution(distribution: Dict[Any, int]) -> str:
    return "\n".join(f"  {key}: {value}" for key, value in distribution.items())


def fallback_min_citations(total_seed_citations: int) -> int:
    """Used when the reply cannot be parsed at all."""
    if total_seed_citations <= 2000:
        return 0
    if total_seed_citations <= 5000:
        return 1
    return 3


class CitationParamsDecider:
    """LLM chooser for the next forward-expansion window."""

    def __init__(self, llm: Any, model: Optional[str] = None, temperature: float = 0.3) -> None:
        self.llm = llm
        self.model = model
        self.temperature = temperature
        self.prompts = load_prompts(PROMPTS_FILE)

    async def decide(
        self,
        *,
        total_seed_citations: int,
        citation_distribution: Dict[str, int],
        year_distribution: Dict[int, int],
        year_end: int = 2023,
    ) -> Dict[str, Any]:
        config = self.prompts["citation_params_decision"]
        raw = await self.llm.complete(
            system=config["system"],
            user=config["user"].format(
                year_end=year_end,
                total_seed_citations=total_seed_citations,
                citation_distribution=format_distribution(citation_distribution),
                year_distribution=format_distribution(year_distribution),
            ),
            model=self.model,
            temperature=self.temperature,
            prompt_key="citation_params_decision",
        )

        parsed = parse_key_values(
            raw, {"reasoning": str, "year_start": int, "min_citations": int}
        )
        return clamp_decision(
            parsed, total_seed_citations=total_seed_citations, year_end=year_end
        )


def clamp_decision(
    parsed: Dict[str, Any], *, total_seed_citations: int, year_end: int
) -> Dict[str, Any]:
    """Bound the LLM's answer to a usable window."""
    clamped = False

    raw_year = parsed.get("year_start")
    if isinstance(raw_year, int):
        year_start = max(YEAR_FLOOR, min(raw_year, year_end - 1))
        clamped = clamped or year_start != raw_year
    else:
        year_start = DEFAULT_YEAR_START
        clamped = True

    raw_min = parsed.get("min_citations")
    if isinstance(raw_min, int):
        min_citations = max(0, min(raw_min, MIN_CITATIONS_CEILING))
        clamped = clamped or min_citations != raw_min
    else:
        min_citations = fallback_min_citations(total_seed_citations)
        clamped = True

    return {
        "year_start": year_start,
        "min_citations": min_citations,
        "reasoning": parsed.get("reasoning", ""),
        "raw": {"year_start": raw_year, "min_citations": raw_min},
        "clamped": clamped,
    }
