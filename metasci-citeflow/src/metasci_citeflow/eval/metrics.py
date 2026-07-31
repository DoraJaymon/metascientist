"""Retrieval metrics, ported to match the original evaluator exactly.

Two of these deviate from textbook definitions.  Both are preserved deliberately, because
the published numbers were produced with them and changing either would make comparisons
meaningless:

* ``precision@k`` is normalised by ``min(k, |GT|)`` rather than ``k``. With a median
  ground-truth size of 1, dividing by k would cap precision@20 at 0.05 for a perfect run.
* ``DCG`` discounts by ``1/sqrt(i)`` rather than ``1/log2(i+1)``.

``store_coverage`` is the metric to watch before a final ranking exists: it asks whether
the pipeline ever *found* the ground-truth papers, independent of how it ordered them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from metasci_citeflow.eval.benchmark import BenchmarkQuery, normalise_id


def paper_ids(paper: Any) -> Set[str]:
    """Every identifier a prediction can be matched on."""
    if isinstance(paper, dict):
        values = [paper.get("openalex_id"), paper.get("corpus_id"), paper.get("id")]
    else:
        values = [
            getattr(paper, "openalex_id", None),
            getattr(paper, "corpus_id", None),
        ]
    return {normalise_id(v) for v in values if v} - {""}


def matched_positions(
    ranked: Sequence[Any], truth_sets: Sequence[Set[str]]
) -> List[int]:
    """1-based positions of ground-truth papers in the ranking.

    Each ground-truth paper contributes at most one position — its first appearance —
    so duplicate records of the same paper cannot inflate the score.
    """
    positions: List[int] = []
    for truth in truth_sets:
        for index, paper in enumerate(ranked, start=1):
            if paper_ids(paper) & truth:
                positions.append(index)
                break
    return sorted(positions)


def recall_at_k(positions: Sequence[int], num_truth: int, k: int) -> float:
    if num_truth == 0:
        return 0.0
    return sum(1 for pos in positions if pos <= k) / num_truth


def precision_at_k(positions: Sequence[int], num_truth: int, k: int) -> float:
    if k == 0 or num_truth == 0:
        return 0.0
    hits = sum(1 for pos in positions if pos <= k)
    return hits / min(k, num_truth)


def mrr(positions: Sequence[int]) -> float:
    return 1.0 / min(positions) if positions else 0.0


def mean_average_precision(positions: Sequence[int], num_truth: int) -> float:
    if not positions or num_truth == 0:
        return 0.0
    return sum(rank / pos for rank, pos in enumerate(sorted(positions), start=1)) / num_truth


def _dcg(relevances: Sequence[int], k: int) -> float:
    total = 0.0
    for index, relevance in enumerate(relevances[:k], start=1):
        total += relevance if index == 1 else relevance / (index**0.5)
    return total


def ndcg_at_k(positions: Sequence[int], num_truth: int, num_predicted: int, k: int) -> float:
    if num_truth == 0 or num_predicted == 0:
        return 0.0
    relevances = [0] * num_predicted
    for pos in positions:
        if pos <= num_predicted:
            relevances[pos - 1] = 1
    ideal = [1] * min(num_truth, num_predicted) + [0] * max(0, num_predicted - num_truth)
    denominator = _dcg(ideal, k)
    return _dcg(relevances, k) / denominator if denominator else 0.0


@dataclass
class RankingMetrics:
    query_id: str
    num_ground_truth: int
    num_predicted: int
    num_matched: int
    num_ground_truth_in_store: int
    ground_truth_store_coverage: float
    overall_precision: float
    overall_recall: float
    recall_at_20: float
    recall_at_50: float
    recall_at_100: float
    precision_at_20: float
    mrr: float
    map_score: float
    ndcg_at_20: float
    gt_positions: List[Optional[int]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query_id": self.query_id,
            "num_ground_truth": self.num_ground_truth,
            "num_predicted": self.num_predicted,
            "num_matched": self.num_matched,
            "num_ground_truth_in_store": self.num_ground_truth_in_store,
            "ground_truth_store_coverage": round(self.ground_truth_store_coverage, 4),
            "overall_precision": round(self.overall_precision, 4),
            "overall_recall": round(self.overall_recall, 4),
            "recall@20": round(self.recall_at_20, 4),
            "recall@50": round(self.recall_at_50, 4),
            "recall@100": round(self.recall_at_100, 4),
            "precision@20": round(self.precision_at_20, 4),
            "mrr": round(self.mrr, 4),
            "map": round(self.map_score, 4),
            "ndcg@20": round(self.ndcg_at_20, 4),
            "gt_positions": self.gt_positions,
        }


def store_coverage(store_papers: Iterable[Any], query: BenchmarkQuery) -> Dict[str, Any]:
    """How many ground-truth papers the pipeline found, regardless of ranking.

    This is the meaningful signal before a final ranking exists: a paper that never
    entered the store can never be ranked, so coverage is the ceiling on recall.
    """
    present: Set[str] = set()
    for paper in store_papers:
        present |= paper_ids(paper)

    truth_sets = query.id_sets()
    found = [bool(truth & present) for truth in truth_sets]
    total = len(truth_sets)
    return {
        "query_id": query.query_id,
        "num_ground_truth": total,
        "num_ground_truth_in_store": sum(found),
        "ground_truth_store_coverage": round(sum(found) / total, 4) if total else 0.0,
        "missing_titles": [
            title for title, hit in zip(query.titles(), found) if not hit
        ],
    }


def evaluate_ranking(
    ranked: Sequence[Any],
    query: BenchmarkQuery,
    *,
    store_papers: Optional[Iterable[Any]] = None,
) -> RankingMetrics:
    """Score a ranked prediction list against one benchmark query."""
    truth_sets = query.id_sets()
    num_truth = len(truth_sets)
    num_predicted = len(ranked)

    positions = matched_positions(ranked, truth_sets)
    num_matched = len(positions)

    coverage = store_coverage(store_papers if store_papers is not None else ranked, query)

    per_paper: List[Optional[int]] = []
    for truth in truth_sets:
        hit = next(
            (i for i, paper in enumerate(ranked, start=1) if paper_ids(paper) & truth), None
        )
        per_paper.append(hit)

    return RankingMetrics(
        query_id=query.query_id,
        num_ground_truth=num_truth,
        num_predicted=num_predicted,
        num_matched=num_matched,
        num_ground_truth_in_store=coverage["num_ground_truth_in_store"],
        ground_truth_store_coverage=coverage["ground_truth_store_coverage"],
        overall_precision=num_matched / num_predicted if num_predicted else 0.0,
        overall_recall=num_matched / num_truth if num_truth else 0.0,
        recall_at_20=recall_at_k(positions, num_truth, 20),
        recall_at_50=recall_at_k(positions, num_truth, 50),
        recall_at_100=recall_at_k(positions, num_truth, 100),
        precision_at_20=precision_at_k(positions, num_truth, 20),
        mrr=mrr(positions),
        map_score=mean_average_precision(positions, num_truth),
        ndcg_at_20=ndcg_at_k(positions, num_truth, num_predicted, 20),
        gt_positions=per_paper,
    )
