"""Atomic tools for deep academic search.

Each function is one tool callable by an agent or skill.
All stateful tools accept a session_id to share a PaperStore across calls.

Tool catalogue
--------------
Session
  ds.session.new()                          → {session_id, stats}

Query
  ds.query.analyze(query, mode?)            → {session_id, keywords, criteria, reasoning}
  ds.query.rewrite(session_id, query, tried_keywords, mode, hint?) → {keywords}

Papers
  ds.papers.search(session_id, keywords, limit?) → {added, total, paper_ids}
  ds.papers.judge(session_id, query, criteria, paper_ids?, top_k?) → {scores, successful_count}

Citations
  ds.citations.fetch_refs(session_id, paper_ids, limit_per_paper?) → {added, total}
  ds.citations.fetch_forward(session_id, paper_ids, year_start?, year_end?, min_citations?) → {added, total}
  ds.citations.co_cite(session_id, min_count?)  → {co_cited_count, added}

Store
  ds.store.stats(session_id)                → {total, evaluated, search, citation, seeds, ...}
  ds.store.seeds.candidates(session_id, n?, min_in_domain?, min_total?) → {candidates}
  ds.store.seeds.mark(session_id, paper_ids) → {marked}
  ds.store.rank(session_id, weights?, top_k?) → {papers}
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from metasci_deepsearch.session import get_session, new_session

logger = logging.getLogger(__name__)

# ── helpers ───────────────────────────────────────────────────────────────────

def _llm_client():
    from openai import AsyncOpenAI
    return AsyncOpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL"),
    )

def _default_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini")


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION
# ═══════════════════════════════════════════════════════════════════════════════

async def session_new() -> Dict[str, Any]:
    """Create a new search session with an empty PaperStore.

    Returns:
        session_id: use this in all subsequent tool calls.
        stats:      initial store stats (all zeros).
    """
    sid, store = new_session()
    return {"session_id": sid, "stats": store.get_stats()}


# ═══════════════════════════════════════════════════════════════════════════════
# QUERY
# ═══════════════════════════════════════════════════════════════════════════════

async def query_analyze(
    query: str,
    mode: str = "simple",
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Parse a research question into search keywords and evaluation criteria.

    Args:
        query:  Natural-language research question.
        mode:   "simple" (keywords + criteria) or "expand" (adds synonyms/variants).
        model:  LLM model override.

    Returns:
        keywords:   Compact keyword string for academic search.
        criteria:   [{text, weight}, ...] evaluation criteria list.
        reasoning:  Why these keywords were chosen.
    """
    from metasci_deepsearch.query_analyzer import QueryAnalyzer
    qa = QueryAnalyzer(model=model or _default_model())
    result = await qa.analyze(query, mode=mode)
    return {
        "keywords": result.get("core_keywords", query),
        "criteria": result.get("criteria", []),
        "reasoning": result.get("reasoning", ""),
        "expand": {
            k: result[k] for k in ("unique_keywords", "expanded_keywords", "synonyms")
            if k in result
        } if mode == "expand" else {},
    }


async def query_rewrite(
    query: str,
    tried_keywords: List[str],
    mode: str = "expand",
    hint: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate new search keywords to continue or correct the search.

    Args:
        query:           Original research question.
        tried_keywords:  All keyword strings used so far (avoid repeats).
        mode:            "expand" (last round succeeded, broaden coverage) or
                         "regenerate" (last round failed, try different angle).
        hint:            Optional instruction to guide the rewrite (e.g. "focus on methods").
        model:           LLM model override.

    Returns:
        keywords:  New keyword string to use next.
        reasoning: Why these keywords were chosen.
    """
    _SYSTEM = "You are an academic search expert. Rewrite search keywords to find more relevant papers."
    tried_str = "; ".join(tried_keywords)

    if mode == "expand":
        user = (
            f"Original query: {query}\n"
            f"Previously tried: {tried_str}\n"
            f"{'Additional guidance: ' + hint + chr(10) if hint else ''}"
            "These searches found relevant papers. Generate NEW complementary keywords "
            "to expand coverage without repeating what was already tried.\n"
            "Output ONLY the keyword string (2-5 terms, no explanation)."
        )
    else:
        user = (
            f"Original query: {query}\n"
            f"Previously tried: {tried_str}\n"
            f"{'Additional guidance: ' + hint + chr(10) if hint else ''}"
            "These searches found few relevant papers. Generate BETTER keywords "
            "targeting the core topic from a different angle.\n"
            "Output ONLY the keyword string (2-5 terms, no explanation)."
        )

    client = _llm_client()
    resp = await client.chat.completions.create(
        model=model or _default_model(),
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user},
        ],
    )
    new_kw = resp.choices[0].message.content.strip().strip('"')
    return {"keywords": new_kw or tried_keywords[-1], "mode": mode}


# ═══════════════════════════════════════════════════════════════════════════════
# PAPERS
# ═══════════════════════════════════════════════════════════════════════════════

async def papers_search(
    session_id: str,
    keywords: str,
    limit: int = 50,
    year_upper_limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Search Semantic Scholar with keywords and add results to the session store.

    Args:
        session_id:       Active session.
        keywords:         Keyword string to search.
        limit:            Max papers to retrieve (default 50, max 200).
        year_upper_limit: Exclude papers published after this year.

    Returns:
        added:      Number of new papers added (dedup applied).
        total:      Total papers in store after this call.
        paper_ids:  List of corpus_ids for the retrieved papers (for use in judge).
    """
    from metasci_deepsearch.providers.semantic_scholar import SemanticScholarSearchClient

    store = get_session(session_id)
    limit = min(limit, 200)

    async with SemanticScholarSearchClient(year_upper_limit=year_upper_limit) as s2:
        raw = await s2.search_papers(keywords, limit=limit)

    for i, p in enumerate(raw):
        p.external_info["search_rank"] = i + 1

    new_records = store.add_papers(
        [p.to_dict() for p in raw],
        source="search",
        keywords=keywords,
        api_name="semantic_scholar",
    )
    paper_ids = [
        r.corpus_id for r in new_records
    ] + [
        p.external_info.get("corpusId") or p.to_dict().get("corpus_id", "")
        for p in raw
        if not any(
            r.corpus_id == (p.external_info.get("corpusId") or "")
            for r in new_records
        )
    ]
    # Simpler: just return all corpus_ids from what was fetched
    all_ids = []
    for p in raw:
        cid = str(p.external_info.get("corpusId") or "") or p.paper_id
        if cid:
            all_ids.append(cid)

    return {
        "added": len(new_records),
        "total": len(store.get_all_papers()),
        "paper_ids": all_ids,
        "keywords_used": keywords,
    }


_JUDGE_SYSTEM = """\
You evaluate whether an academic paper is relevant to a research question.
Score 0–1 where 1 = directly relevant, 0 = unrelated.
Respond with ONLY valid JSON: {"score": <float 0-1>, "rationale": "<one sentence>"}"""

_JUDGE_USER = """\
Research question: {query}

Evaluation criteria:
{criteria_text}

Paper:
Title: {title}
Abstract: {abstract}

Score this paper."""


async def papers_judge(
    session_id: str,
    query: str,
    criteria: List[Dict[str, Any]],
    paper_ids: Optional[List[str]] = None,
    top_k: int = 15,
    concurrency: int = 5,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Score papers for relevance using an LLM judge.

    Args:
        session_id:  Active session.
        query:       Original research question (context for scoring).
        criteria:    Evaluation criteria list from query_analyze.
        paper_ids:   Specific paper IDs to evaluate. If None, uses top_k
                     papers by search_rank / importance_score.
        top_k:       Max papers to evaluate (cost control).
        concurrency: Parallel LLM calls.
        model:       LLM model override.

    Returns:
        scores:           [{paper_id, score, rationale}, ...] sorted by score desc.
        successful_count: Papers scoring above 0.5.
        top_paper_ids:    IDs of papers scoring >= 0.5.
    """
    import json
    store = get_session(session_id)
    criteria_text = "\n".join(f"- [{c['weight']:.2f}] {c['text']}" for c in criteria) if criteria else "(no criteria)"

    # Select papers to evaluate
    if paper_ids:
        records = [store.get_record(pid) for pid in paper_ids if store.get_record(pid)]
        records = records[:top_k]
    else:
        all_records = store.get_all_papers()
        unevaluated = [p for p in all_records if not p.is_evaluated]
        # Sort by search_rank then importance
        unevaluated.sort(key=lambda p: (p.search_rank or 9999, -(p.importance_score or 0)))
        records = unevaluated[:top_k]

    if not records:
        return {"scores": [], "successful_count": 0, "top_paper_ids": []}

    client = _llm_client()
    sem = asyncio.Semaphore(concurrency)
    mdl = model or _default_model()

    async def _eval(record):
        async with sem:
            try:
                resp = await client.chat.completions.create(
                    model=mdl,
                    messages=[
                        {"role": "system", "content": _JUDGE_SYSTEM},
                        {"role": "user", "content": _JUDGE_USER.format(
                            query=query,
                            criteria_text=criteria_text,
                            title=record.title or "",
                            abstract=(record.abstract or "")[:600],
                        )},
                    ],
                    response_format={"type": "json_object"},
                )
                data = json.loads(resp.choices[0].message.content)
                return {
                    "paper_id": record.corpus_id,
                    "score": float(data.get("score", 0)),
                    "rationale": data.get("rationale", ""),
                }
            except Exception as exc:
                logger.debug("Judge failed for %s: %s", record.corpus_id, exc)
                return {"paper_id": record.corpus_id, "score": 0.0, "rationale": "eval_error"}

    results = await asyncio.gather(*[_eval(r) for r in records])
    results = [r for r in results if r]
    results.sort(key=lambda x: x["score"], reverse=True)

    # Write scores back to store
    store.update_scores(
        [{"corpus_id": r["paper_id"], "score": r["score"], "rationale": r["rationale"]}
         for r in results],
        score_type="llm",
    )

    successful = [r for r in results if r["score"] >= 0.5]
    return {
        "scores": results,
        "successful_count": len(successful),
        "top_paper_ids": [r["paper_id"] for r in successful],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CITATIONS
# ═══════════════════════════════════════════════════════════════════════════════

async def citations_fetch_refs(
    session_id: str,
    paper_ids: List[str],
    limit_per_paper: int = 60,
) -> Dict[str, Any]:
    """Fetch referenced works (backward citations) and add to session store.

    Args:
        session_id:      Active session.
        paper_ids:       OpenAlex IDs of papers whose references to fetch.
        limit_per_paper: Max references per paper.

    Returns:
        added:  New papers added to store.
        total:  Total papers in store.
        ref_count: Total references fetched across all papers.
    """
    from metasci_deepsearch.citation_fetcher import CitationFetcher

    store = get_session(session_id)
    fetcher = CitationFetcher()

    refs_data = await fetcher.fetch_refs(paper_ids, limit_per_work=limit_per_paper)
    all_refs = [p for refs in refs_data.values() for p in refs]

    new_records = store.add_papers(all_refs, source="citation", parent_ids=paper_ids, api_name="openalex")
    return {
        "added": len(new_records),
        "total": len(store.get_all_papers()),
        "ref_count": len(all_refs),
        "source_papers": len(paper_ids),
    }


async def citations_fetch_forward(
    session_id: str,
    paper_ids: List[str],
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    min_citations: int = 0,
    max_per_paper: int = 100,
) -> Dict[str, Any]:
    """Fetch forward citations (papers citing these works) and add to session store.

    Args:
        session_id:    Active session.
        paper_ids:     OpenAlex IDs of seed papers.
        year_start:    Only include papers published from this year.
        year_end:      Only include papers published up to this year.
        min_citations: Only include citing papers with at least this many citations.
        max_per_paper: Max citing papers per seed.

    Returns:
        added:     New papers added to store.
        total:     Total papers in store.
        cit_count: Total citations fetched.
    """
    from metasci_deepsearch.citation_fetcher import CitationFetcher

    store = get_session(session_id)
    fetcher = CitationFetcher()

    year_range = (year_start, year_end) if year_start or year_end else None
    cit_data = await fetcher.fetch_citations(
        paper_ids,
        year_range=year_range,
        min_cited_by=min_citations,
        max_per_work=max_per_paper,
    )
    all_cits = [p for cits in cit_data.values() for p in cits]
    new_records = store.add_papers(all_cits, source="citation", parent_ids=paper_ids, api_name="openalex")

    return {
        "added": len(new_records),
        "total": len(store.get_all_papers()),
        "cit_count": len(all_cits),
        "source_papers": len(paper_ids),
    }


async def citations_co_cite(
    session_id: str,
    min_count: int = 2,
) -> Dict[str, Any]:
    """Find papers co-cited by store papers and add them to the session store.

    Co-cited papers are those referenced by multiple papers already in the store —
    they are often foundational works or knowledge hubs for the topic.

    Args:
        session_id: Active session.
        min_count:  Minimum number of store papers that must co-cite a paper.

    Returns:
        co_cited_count: Papers meeting the co-citation threshold.
        added:          New papers added to store.
        total:          Total papers in store.
    """
    from metasci_deepsearch.citation_network import CitationNetwork

    store = get_session(session_id)
    cn = CitationNetwork(store)

    all_papers = [p.to_dict() for p in store.get_all_papers()]
    co_cited, _ = await cn.compute_co_citations_from_papers(
        papers=all_papers,
        min_count=min_count,
        auto_fetch=False,
    )
    new_records = store.add_papers(
        [p for p in co_cited if not p.get("_not_in_store")],
        source="citation",
        api_name="openalex",
    )
    return {
        "co_cited_count": len(co_cited),
        "added": len(new_records),
        "total": len(store.get_all_papers()),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# STORE
# ═══════════════════════════════════════════════════════════════════════════════

async def store_stats(session_id: str) -> Dict[str, Any]:
    """Return statistics about the current session store.

    Returns:
        total:           Total papers in store.
        evaluated:       Papers with LLM scores.
        search_papers:   Papers found via keyword search.
        citation_papers: Papers found via citation expansion.
        seeds:           Papers marked as seeds.
        avg_citation_count: Average citation count.
        keywords_used:   All keyword strings used so far.
        current_round:   Current round counter.
    """
    store = get_session(session_id)
    stats = store.get_stats()
    stats["seeds"] = len([p for p in store.get_all_papers() if p.is_seed])
    return stats


async def store_seeds_candidates(
    session_id: str,
    n: int = 10,
    min_in_domain: int = 1,
    min_total_citations: int = 5,
    exclude_already_seeds: bool = True,
) -> Dict[str, Any]:
    """Find candidate seed papers for citation expansion using in-domain scoring.

    Computes in-domain citation scores (how many store papers cite each paper)
    then ranks candidates by combined domain impact. Call this before
    store_seeds_mark to decide which papers to use as expansion seeds.

    Args:
        session_id:             Active session.
        n:                      Max candidates to return.
        min_in_domain:          Min in-domain citations required.
        min_total_citations:    Min total citation count required.
        exclude_already_seeds:  Skip papers already marked as seeds.

    Returns:
        candidates: [{title, corpus_id, openalex_id, in_domain_citations,
                      total_citations, score, year}, ...]
    """
    from metasci_deepsearch.citation_network import CitationNetwork

    store = get_session(session_id)
    cn = CitationNetwork(store)
    cn.calculate_paper_scores()

    candidates = cn.find_seed_candidates(
        top_k=n,
        min_in_domain=min_in_domain,
        min_total=min_total_citations,
        exclude_seeds=exclude_already_seeds,
    )
    # Strip the paper_record object (not JSON-serialisable)
    return {
        "candidates": [
            {k: v for k, v in c.items() if k != "paper_record"}
            for c in candidates
        ],
        "count": len(candidates),
    }


async def store_seeds_mark(
    session_id: str,
    paper_ids: List[str],
    tag: Optional[str] = None,
) -> Dict[str, Any]:
    """Mark papers as seeds for citation expansion.

    Args:
        session_id: Active session.
        paper_ids:  Corpus IDs or OpenAlex IDs to mark.
        tag:        Optional label (e.g. "seed_r1").

    Returns:
        marked: Number of papers successfully marked.
    """
    store = get_session(session_id)
    marked = store.mark_as_seeds(paper_ids, tag=tag)
    return {"marked": marked, "total_seeds": len([p for p in store.get_all_papers() if p.is_seed])}


async def store_rank(
    session_id: str,
    weights: Optional[Dict[str, float]] = None,
    top_k: int = 100,
) -> Dict[str, Any]:
    """Rank all papers in the store and return the top results.

    Args:
        session_id: Active session.
        weights:    Score dimension weights. Supported keys:
                    relevance, centrality, recency, llm_score,
                    in_domain_citation_score, keyword_match_score.
                    Defaults to {relevance:0.5, centrality:0.25, recency:0.25}.
        top_k:      Max papers to return.

    Returns:
        papers: List of ranked paper dicts with all scores.
        total:  Total papers in store.
    """
    from metasci_deepsearch.citation_network import CitationNetwork

    store = get_session(session_id)

    # Recompute in-domain scores before final ranking
    cn = CitationNetwork(store)
    cn.calculate_paper_scores()

    if weights is None:
        weights = {"relevance": 0.5, "centrality": 0.25, "recency": 0.25}

    # Blend in in-domain score if available
    has_domain = any(
        p.in_domain_citation_score for p in store.get_all_papers()
        if p.in_domain_citation_score
    )
    if has_domain and "in_domain_citation_score" not in weights:
        scale = 0.85
        weights = {k: v * scale for k, v in weights.items()}
        weights["in_domain_citation_score"] = 0.15

    ranked = store.rank_by_importance(weights=weights)
    papers = [p.to_dict() for p in ranked[:top_k]]

    return {
        "papers": papers,
        "total": len(store.get_all_papers()),
        "returned": len(papers),
        "weights_used": weights,
    }
