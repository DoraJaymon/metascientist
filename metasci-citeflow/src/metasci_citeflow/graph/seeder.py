"""Seed selection off the co-citation buckets.

Two strategies run in sequence against a shared budget:

* **Strategy 1** works the *strong* bucket (co-cited by 3-10 store papers). These are the
  papers the topic's literature agrees are central.
* **Strategy 2** only runs if strategy 1 came up short, and works the *weak* bucket
  (co-cited exactly twice) with the budget decremented by whatever strategy 1 found.

The budget — ``min_seeds`` and ``min_total_citations`` — is what stops the run from
expanding off one or two thin seeds. ``enforce_limits`` decides whether meeting it stops
the batch loop early (cheaper, fewer LLM calls) or every batch is processed regardless
(broader, more expensive); the two evaluated parameter regimes differ on exactly this.

Note the two distinct citation ceilings: candidates above ``max_citation_exclude``
(5000) are dropped before ranking, and the selector separately refuses anything above
``hard_max_cited_by`` (8000). Both existed in the original.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from metasci_citeflow.llm.seed_selector import SeedSelector, citation_count

logger = logging.getLogger(__name__)


async def call_with_retry(
    fn: Callable[[], Any],
    *,
    sleep: Callable[[float], Any],
    max_retries: int = 5,
    initial_wait: float = 5.0,
    max_wait: float = 90.0,
) -> Any:
    """Retry an LLM call with exponential backoff, re-raising the last error."""
    wait = initial_wait
    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001 - provider errors vary
            last_error = exc
            if attempt == max_retries - 1:
                break
            logger.warning(
                "Seed selection failed (attempt %d/%d): %s; retrying in %.0fs",
                attempt + 1,
                max_retries,
                exc,
                wait,
            )
            await sleep(wait)
            wait = min(wait * 2, max_wait)
    raise last_error  # type: ignore[misc]


class Seeder:
    """Chooses expansion seeds from co-citation buckets using the LLM selector."""

    def __init__(
        self,
        llm: Any,
        *,
        query: str,
        profile: Any,
        sleep: Callable[[float], Any],
        model: Optional[str] = None,
    ) -> None:
        self.query = query
        self.profile = profile
        self.sleep = sleep
        self.selector = SeedSelector(
            llm,
            model=model or profile.models.seed,
            temperature=profile.seed_llm.temperature,
        )

    async def select_seeds_with_llm(
        self,
        candidates: Sequence[Dict[str, Any]],
        *,
        min_seeds: int,
        min_total_citations: int,
        enforce_limits: bool,
    ) -> Dict[str, Any]:
        """Run the selector over candidates in batches, honouring the citation budget."""
        settings = self.profile.seed_llm
        pool = [
            paper
            for paper in candidates
            if citation_count(paper) <= settings.hard_max_cited_by
        ]
        if not pool:
            return {"seeds": [], "batches": 0, "total_citations": 0, "reasoning": []}

        batch_size = settings.batch_size
        batches = [pool[start : start + batch_size] for start in range(0, len(pool), batch_size)]

        seeds: List[Dict[str, Any]] = []
        reasoning: List[str] = []
        total_citations = 0
        seen_ids = set()
        used_batches = 0

        for batch in batches:
            used_batches += 1
            result = await call_with_retry(
                lambda batch=batch: self.selector.select(
                    self.query, batch, max_papers=batch_size
                ),
                sleep=self.sleep,
                max_retries=settings.max_retries,
                initial_wait=settings.initial_wait,
                max_wait=settings.max_wait,
            )
            if result.get("reasoning"):
                reasoning.append(result["reasoning"])

            for paper in result.get("selected_papers", []):
                key = paper.get("openalex_id") or paper.get("corpus_id")
                if not key or key in seen_ids:
                    continue
                seen_ids.add(key)
                seeds.append(paper)
                total_citations += citation_count(paper)

            if (
                enforce_limits
                and len(seeds) >= min_seeds
                and total_citations >= min_total_citations
            ):
                break

        return {
            "seeds": seeds,
            "batches": used_batches,
            "total_citations": total_citations,
            "reasoning": reasoning,
        }

    async def select_from_co_citations(
        self,
        strong: Sequence[Dict[str, Any]],
        weak: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Run strategy 1, then strategy 2 against the remaining budget."""
        config = self.profile.refs.co_seed_selection
        enforce = self.profile.seed_llm.enforce_limits

        strategies: List[int] = []
        seeds: List[Dict[str, Any]] = []
        reasoning: List[str] = []
        total_citations = 0
        batches = 0

        if len(strong) >= config.min_papers:
            strategies.append(1)
            first = await self.select_seeds_with_llm(
                strong[:30],
                min_seeds=config.min_seeds,
                min_total_citations=config.min_total_citations,
                enforce_limits=enforce,
            )
            seeds.extend(first["seeds"])
            reasoning.extend(first["reasoning"])
            total_citations += first["total_citations"]
            batches += first["batches"]

        need_more = (
            len(seeds) < config.min_seeds or total_citations < config.min_total_citations
        )
        if need_more and weak:
            strategies.append(2)
            chosen = {p.get("openalex_id") or p.get("corpus_id") for p in seeds}
            remaining = [
                paper
                for paper in weak[:20]
                if (paper.get("openalex_id") or paper.get("corpus_id")) not in chosen
            ]
            if remaining:
                second = await self.select_seeds_with_llm(
                    remaining,
                    # Budget is decremented by what strategy 1 already found.
                    min_seeds=max(0, config.min_seeds - len(seeds)),
                    min_total_citations=max(0, config.min_total_citations - total_citations),
                    enforce_limits=enforce,
                )
                seeds.extend(second["seeds"])
                reasoning.extend(second["reasoning"])
                total_citations += second["total_citations"]
                batches += second["batches"]

        return {
            "seeds": seeds,
            "total_seed_citations": total_citations,
            "strategies_used": strategies,
            "batches": batches,
            "reasoning": reasoning,
            "budget": {
                "min_seeds": config.min_seeds,
                "min_total_citations": config.min_total_citations,
                "met": len(seeds) >= config.min_seeds
                and total_citations >= config.min_total_citations,
            },
        }


def prepare_candidates(
    records: Sequence[Any],
    *,
    max_citation_exclude: int,
    year_floor: Optional[int],
    exclude_seeds: bool = True,
) -> List[Dict[str, Any]]:
    """Filter and quality-rank co-cited records before they reach the LLM."""
    from metasci_citeflow.ranking import rank_by_quality

    kept = []
    for record in records:
        if record is None:
            continue
        if exclude_seeds and getattr(record, "is_seed", False):
            continue
        if (record.citation_count or 0) > max_citation_exclude:
            continue
        year = record.year
        if year_floor and year is not None and year < year_floor:
            continue
        kept.append(record)

    return rank_by_quality(kept)
