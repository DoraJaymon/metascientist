"""Phase 1 keyword search, and the Semantic Scholar -> OpenAlex bridge.

This module owns the invariant the rest of the pipeline depends on: **every paper in the
store should carry an OpenAlex work id**.  Semantic Scholar has the better keyword recall
for natural-language research questions, but returns no OpenAlex id, and the citation
graph is keyed entirely on OpenAlex.  Without the bridge, co-citation finds nothing,
seed candidates come back empty and reference fetches silently return nothing — the
failure is quiet, which is what made it survive unnoticed in the previous port.

Resolution order is DOI -> MAG -> title.  MAG is a genuine identifier that Semantic
Scholar returns and OpenAlex indexes, so it is preferred over fuzzy title matching.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


def merge_search_results(
    per_query: Sequence[Tuple[str, Sequence[Dict[str, Any]]]]
) -> List[Dict[str, Any]]:
    """Merge multi-query results, de-duplicating and stamping provenance.

    ``search_rank`` is the position in the *merged* list (0-based), matching the original
    ``init_search_merged``.  It later decides which citing papers get picked during
    references expansion, so the base matters.
    """
    merged: List[Dict[str, Any]] = []
    seen: Dict[str, int] = {}

    for query_index, (query, papers) in enumerate(per_query):
        for paper in papers:
            key = str(
                paper.get("openalex_id")
                or paper.get("corpus_id")
                or paper.get("paper_id")
                or ""
            )
            if not key:
                continue
            if key in seen:
                continue
            record = dict(paper)
            record["search_rank"] = len(merged)
            record["_search_query_index"] = query_index
            record["_search_query"] = query
            seen[key] = len(merged)
            merged.append(record)

    return merged


def resolution_queries(papers: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Build DOI/MAG/title lookup keys for the OpenAlex bridge."""
    queries: List[Dict[str, str]] = []
    for paper in papers:
        query: Dict[str, str] = {}
        if paper.get("doi"):
            query["doi"] = str(paper["doi"])
        if paper.get("mag_id"):
            query["mag"] = str(paper["mag_id"])
        if paper.get("title"):
            query["title"] = str(paper["title"])
        queries.append(query)
    return queries


def merge_openalex_into(
    s2_paper: Dict[str, Any], oa_paper: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Fold an OpenAlex work into its Semantic Scholar counterpart.

    OpenAlex wins for graph fields (id, references, citation count); Semantic Scholar's
    abstract is kept when OpenAlex has none.  The S2 ``corpus_id`` is preserved so the
    record keeps one stable primary key across the whole run — the benchmark's ground
    truth is matched on both corpus_id and openalex_id, so losing either costs recall.
    """
    merged = dict(s2_paper)
    if not oa_paper:
        return merged

    merged["openalex_id"] = oa_paper.get("openalex_id")
    merged["reference_ids"] = list(oa_paper.get("reference_ids") or [])
    merged["referenced_works"] = list(oa_paper.get("referenced_works") or [])
    merged["reference_count"] = oa_paper.get("reference_count") or merged.get("reference_count", 0)

    for field in ("year", "publication_year", "venue", "doi", "mag_id"):
        if not merged.get(field) and oa_paper.get(field):
            merged[field] = oa_paper[field]

    if (oa_paper.get("cited_by_count") or 0) > (merged.get("cited_by_count") or 0):
        merged["citation_count"] = oa_paper["cited_by_count"]
        merged["cited_by_count"] = oa_paper["cited_by_count"]

    if not (merged.get("abstract") or "").strip() and oa_paper.get("abstract"):
        merged["abstract"] = oa_paper["abstract"]

    if not merged.get("authors") and oa_paper.get("authors"):
        merged["authors"] = oa_paper["authors"]

    merged["_source"] = "semantic_scholar+openalex"
    return merged


async def resolve_to_openalex(
    papers: Sequence[Dict[str, Any]], openalex: Any
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Resolve papers to OpenAlex works.

    Returns ``(resolved_papers, unresolved_summaries)``.  Papers that cannot be resolved
    are kept — they still count for keyword relevance — but they can never take part in
    citation expansion, so they are reported explicitly rather than dropped silently.
    """
    if not papers:
        return [], []

    pending = [paper for paper in papers if not paper.get("openalex_id")]
    if not pending:
        return list(papers), []

    works = await openalex.resolve_many(resolution_queries(pending))
    by_key = {id(paper): work for paper, work in zip(pending, works)}

    resolved: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []
    for paper in papers:
        if paper.get("openalex_id"):
            resolved.append(dict(paper))
            continue
        work = by_key.get(id(paper))
        merged = merge_openalex_into(paper, work)
        resolved.append(merged)
        if not merged.get("openalex_id"):
            unresolved.append(
                {
                    "corpus_id": paper.get("corpus_id"),
                    "title": (paper.get("title") or "")[:120],
                    "doi": paper.get("doi"),
                    "has_mag": bool(paper.get("mag_id")),
                }
            )

    return resolved, unresolved


async def backfill_openalex(
    records: Sequence[Any], openalex: Any
) -> Tuple[int, int, List[Dict[str, Any]]]:
    """Retry OpenAlex resolution for store records that still lack an id.

    Returns ``(resolved_count, abstracts_filled, updates)`` where ``updates`` carries the
    fields to write back onto each record.
    """
    pending = [record for record in records if not record.openalex_id]
    if not pending:
        return 0, 0, []

    queries: List[Dict[str, str]] = []
    for record in pending:
        query: Dict[str, str] = {}
        if record.doi:
            query["doi"] = str(record.doi)
        if record.title:
            query["title"] = str(record.title)
        queries.append(query)

    works = await openalex.resolve_many(queries)

    updates: List[Dict[str, Any]] = []
    resolved_count = 0
    abstracts_filled = 0
    for record, work in zip(pending, works):
        if not work:
            continue
        update: Dict[str, Any] = {
            "corpus_id": record.corpus_id,
            "openalex_id": work.get("openalex_id"),
            "reference_ids": list(work.get("reference_ids") or []),
        }
        resolved_count += 1
        if not (record.abstract or "").strip() and work.get("abstract"):
            update["abstract"] = work["abstract"]
            abstracts_filled += 1
        updates.append(update)

    return resolved_count, abstracts_filled, updates
