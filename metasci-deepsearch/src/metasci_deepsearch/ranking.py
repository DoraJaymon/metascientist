"""Importance-based paper ranking.

Ported from AcaDeepR/src/tools/paper_ranking/importance_sorter.py.
Removed: src.* imports.  LLM-based reranker is optional (RERANK_API_TOKEN).
"""

from __future__ import annotations

import logging
import math
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)


def sigmoid(x: float, center: float = 0.0, steepness: float = 1.0) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-steepness * (x - center)))
    except OverflowError:
        return 0.0 if x < center else 1.0


def recency_score(year: int, current_year: Optional[int] = None,
                  center_shift: float = 7.0, steepness: float = 0.7) -> float:
    if current_year is None:
        current_year = datetime.now().year
    if not year or year <= 0:
        return 0.0
    if year >= current_year:
        return 1.0
    return sigmoid(year, center=current_year - center_shift, steepness=steepness)


def centrality_score(citation_count: int, center: int = 50, steepness: float = 1.8) -> float:
    if not citation_count or citation_count <= 0:
        return 0.0
    return sigmoid(math.log(citation_count + 1), center=math.log(center + 1), steepness=steepness)


async def rerank_papers(
    query: str,
    papers: List[Dict[str, Any]],
    api_token: Optional[str] = None,
    model: str = "BAAI/bge-reranker-v2-m3",
    api_url: str = "https://yunwu.ai/v1/rerank",
) -> Dict[str, float]:
    """Call an external reranker API and return {paper_id: score}."""
    if not papers or not api_token:
        return {}
    try:
        documents, paper_ids = [], []
        for p in papers:
            pid = p.get("paper_id") or p.get("corpus_id", "")
            title = p.get("title", "")
            abstract = p.get("abstract", "")
            doc = f"{title}. {abstract}" if abstract else title
            if doc and pid:
                documents.append(doc)
                paper_ids.append(pid)
        if not documents:
            return {}

        headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
        payload = {"model": model, "query": query, "documents": documents, "top_n": len(documents)}

        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload, headers=headers, timeout=30) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
                results = data.get("results", [])
                raw = [r.get("relevance_score", 0) for r in results]
                max_s, min_s = max(raw, default=1.0), min(raw, default=0.0)
                use_as_is = 0.0 <= min_s and max_s <= 1.0
                scores: Dict[str, float] = {}
                for r in results:
                    idx = r.get("index", -1)
                    s = r.get("relevance_score", 0)
                    if 0 <= idx < len(paper_ids):
                        scores[paper_ids[idx]] = float(s) if use_as_is else float(s) / max_s if max_s else 0.0
                return scores
    except Exception as exc:
        logger.warning("Reranker error: %s", exc)
        return {}


class ImportanceSorter:
    """Fast metadata-based paper sorter (Phase 1 ranking).

    Strategies:
    - ``"precise"`` — relevance-heavy (0.7 / 0.1 / 0.2)
    - ``"balanced"`` — 0.5 / 0.2 / 0.3
    - ``"impact"`` — citation-heavy (0.3 / 0.1 / 0.6)
    """

    STRATEGY_WEIGHTS = {
        "precise":  {"relevance": 0.7, "recency": 0.1, "centrality": 0.2},
        "balanced": {"relevance": 0.5, "recency": 0.2, "centrality": 0.3},
        "impact":   {"relevance": 0.3, "recency": 0.1, "centrality": 0.6},
    }

    def __init__(
        self,
        strategy: str = "precise",
        use_reranker: bool = False,
        rerank_token: Optional[str] = None,
        rerank_model: str = "BAAI/bge-reranker-v2-m3",
        current_year: Optional[int] = None,
    ) -> None:
        self.strategy = strategy
        self.use_reranker = use_reranker
        self.rerank_token = rerank_token or os.getenv("RERANK_API_TOKEN")
        self.rerank_model = rerank_model
        self.current_year = current_year or datetime.now().year
        self.weights = self.STRATEGY_WEIGHTS.get(strategy, self.STRATEGY_WEIGHTS["precise"])

    async def sort_papers(
        self,
        papers: List[Dict[str, Any]],
        query: Optional[str] = None,
        query_list: Optional[List[str]] = None,
        seed_relevance: float = 0.5,
    ) -> List[Dict[str, Any]]:
        if not papers:
            return []

        rerank_scores: Dict[str, float] = {}
        if self.use_reranker and self.rerank_token:
            if query_list and len(query_list) > 1:
                all_scores = [
                    await rerank_papers(q, papers, self.rerank_token, self.rerank_model)
                    for q in query_list
                ]
                for p in papers:
                    pid = p.get("paper_id") or p.get("corpus_id", "")
                    if pid:
                        rerank_scores[pid] = max(s.get(pid, 0) for s in all_scores)
            elif query:
                rerank_scores = await rerank_papers(query, papers, self.rerank_token, self.rerank_model)

        # Build reciprocal-rank fallback from search_rank field
        rankable = sorted(
            [(p.get("paper_id") or p.get("corpus_id", ""), float(p["search_rank"]))
             for p in papers if p.get("search_rank")],
            key=lambda x: x[1],
        )
        fallback = {pid: 1.0 / (i + 1) for i, (pid, _) in enumerate(rankable)}

        scored = []
        for p in papers:
            pid = p.get("paper_id") or p.get("corpus_id", "")
            year = p.get("year")
            cc = p.get("citation_count", 0)
            rec = recency_score(year, self.current_year) if year else 0.5
            cen = centrality_score(cc)
            rel = rerank_scores.get(pid) if pid in rerank_scores else fallback.get(pid, seed_relevance / 3)
            sort_score = (
                self.weights["relevance"] * rel
                + self.weights["recency"] * rec
                + self.weights["centrality"] * cen
            )
            copy = p.copy()
            copy["_sort_score"] = sort_score
            copy["_relevance_score"] = rel
            copy["_recency_score"] = rec
            copy["_centrality_score"] = cen
            scored.append(copy)

        scored.sort(key=lambda x: x["_sort_score"], reverse=True)
        return scored
