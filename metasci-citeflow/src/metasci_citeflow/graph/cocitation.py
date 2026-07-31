"""Co-citation analysis.

Two papers are co-cited when a third cites both.  A work that many of your search hits
all cite is very likely foundational to the topic even though keyword search never
surfaces it — which is precisely the gap keyword retrieval leaves.

Order matters here: CiteFlow computes co-citation **immediately after the initial search
and before any expansion**, then uses the result to decide *which* papers to expand
references from.  Running it after a reference fetch instead (as the previous port's
skill documentation described) inverts cause and effect: the co-citation signal is then
dominated by whatever was just fetched rather than guiding what to fetch.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def paper_key(paper: Any) -> str:
    """Preferred identity for graph work: OpenAlex id, else corpus id."""
    if isinstance(paper, dict):
        return str(paper.get("openalex_id") or paper.get("corpus_id") or paper.get("id") or "")
    return str(getattr(paper, "openalex_id", None) or getattr(paper, "corpus_id", "") or "")


def reference_ids(paper: Any) -> List[str]:
    if isinstance(paper, dict):
        refs = paper.get("referenced_works") or paper.get("reference_ids") or []
    else:
        refs = getattr(paper, "reference_ids", None) or []
    return [str(ref) for ref in refs if ref]


def collect_co_citations(
    papers: Sequence[Any], *, min_count: int = 2
) -> Tuple[Dict[str, int], Dict[str, List[str]]]:
    """Count how many of ``papers`` cite each referenced work.

    Returns ``(counts, citing_map)`` for works meeting ``min_count``.  A paper citing the
    same work twice counts once.
    """
    counts: Dict[str, int] = defaultdict(int)
    citing: Dict[str, List[str]] = defaultdict(list)

    for paper in papers:
        source = paper_key(paper)
        if not source:
            continue
        for ref in dict.fromkeys(reference_ids(paper)):
            counts[ref] += 1
            citing[ref].append(source)

    qualified = {ref: count for ref, count in counts.items() if count >= min_count}
    return qualified, {ref: citing[ref] for ref in qualified}


def bucket_co_citations(
    counts: Dict[str, int], *, strong: Tuple[int, int] = (3, 10)
) -> Tuple[List[str], List[str]]:
    """Split co-cited works into the strong and weak buckets used for seed selection.

    Strong is ``strong[0] <= n <= strong[1]``; weak is exactly 2.  The upper bound on the
    strong bucket matters: a work co-cited by very many papers is usually a general
    classic or survey whose own references sprawl beyond the topic.
    """
    low, high = strong
    strong_ids = [ref for ref, count in counts.items() if low <= count <= high]
    weak_ids = [ref for ref, count in counts.items() if count == 2]
    strong_ids.sort(key=lambda ref: counts[ref], reverse=True)
    weak_ids.sort(key=lambda ref: counts[ref], reverse=True)
    return strong_ids, weak_ids


def apply_year_floor(
    papers: Sequence[Dict[str, Any]], year_floor: Optional[int]
) -> List[Dict[str, Any]]:
    """Drop papers older than ``year_floor``; papers with no year are kept."""
    if not year_floor:
        return list(papers)
    kept = []
    for paper in papers:
        year = paper.get("year") or paper.get("publication_year")
        if year is None or year >= year_floor:
            kept.append(paper)
    return kept


def select_papers_to_expand(
    co_cited_ids: Sequence[str],
    citing_map: Dict[str, List[str]],
    search_ranks: Dict[str, int],
    *,
    max_citing_papers: int,
) -> List[str]:
    """Choose which store papers to fetch references from.

    Walks the co-cited works in order and, for each, takes its citing papers best-first
    by original search rank, until the budget is filled.  Expanding the papers that cite
    the strongest co-cited works keeps the reference haul inside the topic.
    """
    selected: List[str] = []
    seen = set()

    for ref in co_cited_ids:
        citers = citing_map.get(ref, [])
        ordered = sorted(citers, key=lambda pid: search_ranks.get(pid, 10**6))
        for citer in ordered:
            if citer in seen:
                continue
            seen.add(citer)
            selected.append(citer)
            if len(selected) >= max_citing_papers:
                return selected

    return selected


def in_domain_citation_counts(papers: Sequence[Any]) -> Dict[str, int]:
    """How many store papers cite each store paper."""
    known = {paper_key(paper) for paper in papers}
    known.discard("")
    counts: Dict[str, int] = defaultdict(int)
    for paper in papers:
        for ref in dict.fromkeys(reference_ids(paper)):
            if ref in known:
                counts[ref] += 1
    return dict(counts)


def in_domain_score(n_domain: int, total_citations: int) -> Optional[float]:
    """``s_dom = n_dom * (n_dom / |C(p)|)^2``.

    Squaring the in-domain share sharply favours papers cited *mostly* by this topic over
    broadly-cited works that happen to pick up a few citations from it.
    """
    if not total_citations:
        return None
    share = n_domain / total_citations
    return n_domain * (share**2)


def score_store_in_domain(papers: Iterable[Any]) -> int:
    """Write in-domain counts and scores onto store records. Returns papers updated."""
    papers = list(papers)
    for paper in papers:
        paper.in_domain_citation_count = 0
        paper.in_domain_citation_score = None

    counts = in_domain_citation_counts(papers)
    by_key = {paper_key(paper): paper for paper in papers}

    updated = 0
    for key, count in counts.items():
        record = by_key.get(key)
        if record is None:
            continue
        record.in_domain_citation_count = count
        record.in_domain_citation_score = in_domain_score(count, record.citation_count or 0)
        updated += 1
    return updated


def network_stats(papers: Sequence[Any]) -> Dict[str, Any]:
    """In-domain connectivity of the store — the main convergence signal.

    ``in_domain_ratio`` rising across rounds means expansion is staying on topic; two
    consecutive falls mean it is drifting and expansion should stop or change direction.
    """
    known = {paper_key(paper) for paper in papers}
    known.discard("")
    total_refs = 0
    in_domain_refs = 0
    for paper in papers:
        for ref in reference_ids(paper):
            total_refs += 1
            if ref in known:
                in_domain_refs += 1

    counts = in_domain_citation_counts(papers)
    return {
        "total_papers": len(known),
        "total_references": total_refs,
        "in_domain_references": in_domain_refs,
        "in_domain_ratio": round(in_domain_refs / total_refs, 4) if total_refs else 0.0,
        "papers_with_in_domain_citations": len(counts),
        "total_in_domain_citations": sum(counts.values()),
    }
