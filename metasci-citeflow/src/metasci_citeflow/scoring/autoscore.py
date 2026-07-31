"""Composite scoring — the three signals the ranker blends.

``in_domain_citation_score``  graph: how concentrated this paper's citations are inside
                              the current store (cheap, no API calls)
``embedding_sim``             semantic: cross-encoder relevance to the query
``keyword_match_score``       lexical: rarity-weighted discriminative-term matches

Only the semantic signal costs API calls, so it is the one capped by ``max_papers``:
above that, the cap is spent on the papers most likely to matter (ranked by citation
weight and recency) while the two free signals still cover everything.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from metasci_citeflow.graph import cocitation as cc
from metasci_citeflow.scoring import keywords as kw
from metasci_citeflow.scoring import reranker as rr

logger = logging.getLogger(__name__)


def _rank_for_budget(records: Sequence[Any], limit: int) -> List[Any]:
    """Pick which records get the (paid) semantic score when over budget."""
    if len(records) <= limit:
        return list(records)
    from metasci_citeflow.ranking import QUALITY_WEIGHTS
    from metasci_universe.memory.curalib import PaperStore

    ranked = PaperStore().rank_by_importance(papers=list(records), weights=QUALITY_WEIGHTS)
    return ranked[:limit]


async def autoscore(
    store: Any,
    *,
    records: Optional[Sequence[Any]] = None,
    rerank_query: str = "",
    terms: Optional[Dict[str, int]] = None,
    reranker: Any = None,
    max_papers: int = 3000,
    force_sim: bool = False,
) -> Dict[str, Any]:
    """Compute all three signals and write them onto the store."""
    targets = list(records if records is not None else store.get_all_papers())
    report: Dict[str, Any] = {"papers": len(targets), "diagnostics": []}

    # 1. Graph signal - free, always over the whole store so the denominator is right.
    report["in_domain_updated"] = cc.score_store_in_domain(store.get_all_papers())

    # 2. Semantic signal - the only one that costs API calls.
    if rerank_query and reranker is not None:
        budgeted = _rank_for_budget(targets, max_papers)
        try:
            scores, rerank_report = await rr.score_relevance(
                budgeted, rerank_query, reranker, force=force_sim
            )
            if scores:
                store.batch_update_scores(scores, field="embedding_sim")
            report["rerank"] = rerank_report
        except rr.RerankerUnavailable as exc:
            report["rerank"] = {"scored": 0, "error": str(exc)}
            report["diagnostics"].append(f"semantic relevance skipped: {exc}")
    else:
        report["rerank"] = {"scored": 0, "skipped_reason": "no rerank query or client"}

    # 3. Lexical signal - free, covers every target regardless of the rerank budget.
    if terms:
        scores, kw_report = kw.score_records(targets, terms, force=force_sim)
        if scores:
            store.batch_update_scores(scores, field="keyword_match_score")
        report["keywords"] = kw_report
        if kw_report.get("lemmatizer") == "fallback":
            report["diagnostics"].append(
                "spaCy en_core_web_sm missing; keyword scores use whitespace matching "
                "and are not comparable to lemma-matched runs."
            )
    else:
        report["keywords"] = {"scored": 0, "skipped_reason": "no discriminative terms"}

    papers = store.get_all_papers()
    total = len(papers) or 1
    report["coverage"] = {
        "embedding_sim": round(
            sum(1 for p in papers if p.embedding_sim is not None) / total, 4
        ),
        "keyword_match_score": round(
            sum(1 for p in papers if p.keyword_match_score is not None) / total, 4
        ),
        "in_domain": round(
            sum(1 for p in papers if p.in_domain_citation_count) / total, 4
        ),
    }
    return report
