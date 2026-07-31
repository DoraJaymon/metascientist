"""Ranking helpers over CuraLib's weighted scorer."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

# Used to order candidate seeds before they are shown to the LLM. Deliberately ignores
# relevance: at this point relevance has already been established (the candidates come
# from co-citation), so what is left to judge is whether a paper is substantial and
# recent enough to be worth expanding from.
QUALITY_WEIGHTS: Dict[str, float] = {"relevance": 0.0, "citation_count": 0.6, "recency": 0.4}


def rank_by_quality(records: Sequence[Any]) -> List[Dict[str, Any]]:
    """Rank records by citation weight and recency, returning plain dicts."""
    from metasci_universe.memory.curalib import PaperStore

    scored = PaperStore().rank_by_importance(papers=list(records), weights=QUALITY_WEIGHTS)
    if not scored:
        # rank_by_importance resolves dicts against its own store; PaperRecords pass
        # through untouched, so an empty result means nothing was rankable.
        scored = list(records)
    return [record.to_dict() for record in scored]
