"""``cf.*`` tool registry.

Tools are atomic and carry no workflow assumptions: none of them knows how many
expansion rounds a run should take or which direction to expand next.  Ordering is the
caller's job — either a recipe document under the ``metasci-citeflow`` skill, or an
agent driving the loop from the signals reported by ``cf.store.stats``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from metasci_universe.schemas.common import MetaSciResult

from metasci_citeflow import profiles as profiles_mod
from metasci_citeflow.deps import CiteFlowDeps, resolve_deps
from metasci_citeflow.errors import ProviderUnavailable
from metasci_citeflow.session import Session
from metasci_citeflow import schemas as S

ToolHandler = Callable[[Any, Optional[CiteFlowDeps]], Awaitable[Dict[str, Any]]]


@dataclass(frozen=True)
class CiteFlowTool:
    name: str
    description: str
    input_model: type
    handler: ToolHandler
    examples: List[str]

    def to_card(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputs": self.input_model.model_json_schema(),
            "examples": self.examples,
        }


def _root(session_dir: Optional[str]) -> Optional[Path]:
    return Path(session_dir) if session_dir else None


def _stats(session: Session) -> Dict[str, Any]:
    """Store statistics plus the coverage signals an agent needs to decide what to do next."""
    papers = session.store.get_all_papers()
    total = len(papers)
    base = session.store.get_stats()

    with_openalex = sum(1 for p in papers if p.openalex_id)
    with_abstract = sum(1 for p in papers if (p.abstract or "").strip())
    with_embedding = sum(1 for p in papers if p.embedding_sim is not None)
    with_keyword = sum(1 for p in papers if p.keyword_match_score is not None)

    def _ratio(count: int) -> float:
        return round(count / total, 4) if total else 0.0

    base.update(
        {
            "seeds": sum(1 for p in papers if p.is_seed),
            "judged": len(session.judged_ids),
            "with_openalex_id": with_openalex,
            "with_abstract": with_abstract,
            "openalex_coverage": _ratio(with_openalex),
            "abstract_coverage": _ratio(with_abstract),
            "embedding_sim_coverage": _ratio(with_embedding),
            "keyword_score_coverage": _ratio(with_keyword),
        }
    )
    return base


# ── handlers ──────────────────────────────────────────────────────────────────


async def _session_open(req: S.SessionOpenRequest, deps: Optional[CiteFlowDeps]) -> Dict[str, Any]:
    session = Session.open(
        req.session_id,
        query=req.query,
        profile=req.profile,
        overrides=req.overrides,
        root=_root(req.session_dir),
    )
    if req.query and session.query != req.query:
        session.set_query(req.query)
    return {
        "session_id": session.session_id,
        "path": str(session.dir),
        "profile": session.profile.name,
        "query": session.query,
        "stats": _stats(session),
    }


async def _session_info(req: S.SessionInfoRequest, deps: Optional[CiteFlowDeps]) -> Dict[str, Any]:
    session = Session.open(req.session_id, root=_root(req.session_dir))
    return {
        "session_id": session.session_id,
        "path": str(session.dir),
        "profile": session.profile.name,
        "query": session.query,
        "analysis": session.analysis,
        "rounds_summary": session.rounds_summary(),
        "stats": _stats(session),
    }


async def _session_export(req: S.SessionExportRequest, deps: Optional[CiteFlowDeps]) -> Dict[str, Any]:
    session = Session.open(req.session_id, root=_root(req.session_dir))
    session.save()
    return {"store_path": str(session.store_path), "session_path": str(session.ledger_path)}


async def _profiles_list(req: S.ProfilesListRequest, deps: Optional[CiteFlowDeps]) -> Dict[str, Any]:
    return {"profiles": profiles_mod.list_profiles()}


async def _profiles_show(req: S.ProfilesShowRequest, deps: Optional[CiteFlowDeps]) -> Dict[str, Any]:
    profile = profiles_mod.resolve(req.name)
    return {"profile": profile.to_dict()}


async def _query_analyze(req: S.QueryAnalyzeRequest, deps: Optional[CiteFlowDeps]) -> Dict[str, Any]:
    from metasci_citeflow.llm.query_analyzer import SlotBasedQueryAnalyzer, analysis_from_config

    session = Session.open(req.session_id, root=_root(req.session_dir))

    if req.from_yaml:
        import yaml

        with open(req.from_yaml, encoding="utf-8") as handle:
            config = yaml.load(handle, Loader=yaml.FullLoader)
        analysis = analysis_from_config(config)
        if analysis.get("query"):
            session.set_query(analysis["query"])
    else:
        query = req.query or session.query
        if not query:
            raise ValueError("cf.query.analyze needs a query (pass one or set it on the session)")
        session.set_query(query)
        resolved = resolve_deps(deps)
        analyzer = SlotBasedQueryAnalyzer(
            resolved.require_llm(), model=req.model or session.profile.models.analyzer
        )
        analysis = await analyzer.analyze_all(query)

    session.set_analysis(analysis)
    return {
        "session_id": session.session_id,
        "query": analysis.get("query"),
        "structured_keywords": analysis.get("structured_keywords", []),
        "search_queries": analysis.get("search_queries", []),
        "discriminative_terms": analysis.get("discriminative_terms", {}),
        "rerank_query": analysis.get("rerank_query", ""),
        "reasoning": analysis.get("reasoning", {}),
        "parse_error": analysis.get("parse_error"),
    }


async def _papers_search(req: S.PapersSearchRequest, deps: Optional[CiteFlowDeps]) -> Dict[str, Any]:
    from metasci_citeflow.papers import merge_search_results, resolve_to_openalex

    session = Session.open(req.session_id, root=_root(req.session_dir))
    profile = session.profile
    resolved_deps = resolve_deps(deps)

    analysis = session.analysis or {}
    queries = req.queries or list(analysis.get("search_queries") or [])
    if not queries:
        raise ValueError(
            "cf.papers.search needs search queries; run cf.query.analyze first or pass queries."
        )
    queries = queries[: profile.init_search.queries_used]

    limit = req.limit or profile.init_search.limit
    year = req.year
    if year is None and profile.init_search.year:
        year = f"{profile.init_search.year[0]}-{profile.init_search.year[1]}"

    per_query: List[tuple] = []
    per_query_report: List[Dict[str, Any]] = []
    diagnostics: List[str] = []
    provider = "semantic_scholar"

    try:
        s2 = resolved_deps.require_s2()
        for query in queries:
            papers = await s2.search(query, limit=limit, year=year)
            per_query.append((query, papers))
            per_query_report.append({"query": query, "found": len(papers)})
    except ProviderUnavailable as exc:
        # The original pipeline had the same fallback: prefer Semantic Scholar's keyword
        # recall, but keep going on OpenAlex rather than starting from an empty store.
        diagnostics.append(f"Semantic Scholar unavailable ({exc}); fell back to OpenAlex search.")
        provider = "openalex"
        per_query, per_query_report = [], []
        openalex = resolved_deps.require_openalex()
        for query in queries:
            papers = await openalex.search(query, limit=limit, year=year)
            per_query.append((query, papers))
            per_query_report.append({"query": query, "found": len(papers)})

    merged = merge_search_results(per_query)

    unresolved: List[Dict[str, Any]] = []
    if req.resolve_openalex and merged and provider != "openalex":
        merged, unresolved = await resolve_to_openalex(merged, resolved_deps.require_openalex())

    new_records = session.store.add_papers(
        merged, source="search", keywords=" | ".join(queries), api_name=provider
    )
    paper_ids = [paper.get("openalex_id") or paper.get("corpus_id") for paper in merged]
    paper_ids = [pid for pid in paper_ids if pid]

    session.record_round(
        round_num=0,
        phase="search",
        expanded_ids=paper_ids,
        new_ids=[record.openalex_id or record.corpus_id for record in new_records],
        params={"queries": queries, "limit": limit, "year": year},
    )

    resolved_count = sum(1 for paper in merged if paper.get("openalex_id"))
    return {
        "session_id": session.session_id,
        "provider": provider,
        "per_query": per_query_report,
        "merged": len(merged),
        "added": len(new_records),
        "resolved": resolved_count,
        "unresolved": unresolved,
        "openalex_coverage": round(resolved_count / len(merged), 4) if merged else 0.0,
        "paper_ids": paper_ids,
        "total": len(session.store.get_all_papers()),
        "diagnostics": diagnostics,
    }


async def _papers_repair(req: S.PapersRepairRequest, deps: Optional[CiteFlowDeps]) -> Dict[str, Any]:
    from metasci_citeflow.papers import backfill_openalex

    session = Session.open(req.session_id, root=_root(req.session_dir))
    records = (
        session.store.get_records_by_ids(req.paper_ids)
        if req.paper_ids
        else session.store.get_all_papers()
    )

    resolved_count, abstracts_filled, updates = await backfill_openalex(
        records, resolve_deps(deps).require_openalex()
    )

    for update in updates:
        record = session.store.get_record(update["corpus_id"])
        if record is None:
            continue
        record.openalex_id = update["openalex_id"]
        record.reference_ids = update["reference_ids"]
        if "abstract" in update:
            record.abstract = update["abstract"]
        session.store._openalex_index[str(update["openalex_id"])] = record.corpus_id
    session.save()

    still_missing = sum(1 for p in session.store.get_all_papers() if not p.openalex_id)
    return {
        "session_id": session.session_id,
        "resolved": resolved_count,
        "abstracts_filled": abstracts_filled,
        "still_missing": still_missing,
        "stats": _stats(session),
    }


async def _co_cite(req: S.CoCiteRequest, deps: Optional[CiteFlowDeps]) -> Dict[str, Any]:
    from metasci_citeflow.graph import cocitation as cc

    session = Session.open(req.session_id, root=_root(req.session_dir))
    profile = session.profile
    min_count = req.min_count or profile.cocitation.min_count

    records = (
        session.store.get_records_by_ids(req.paper_ids)
        if req.paper_ids
        else session.store.get_all_papers()
    )
    counts, citing_map = cc.collect_co_citations(records, min_count=min_count)
    strong_ids, weak_ids = cc.bucket_co_citations(counts, strong=profile.cocitation.strong)

    ordered = sorted(counts, key=lambda ref: counts[ref], reverse=True)
    known = {cc.paper_key(record) for record in records}
    missing = [ref for ref in ordered if ref not in known][: req.max_hydrate]

    added = 0
    fetched = 0
    if req.hydrate and missing:
        works = await resolve_deps(deps).require_openalex().get_by_ids(missing)
        hydrated = [work for work in works if work]
        fetched = len(hydrated)
        added = len(session.store.add_papers(hydrated, source="citation", api_name="openalex"))

    search_ranks = {
        cc.paper_key(record): record.search_rank
        for record in records
        if record.search_rank is not None
    }
    # citing_map is O(papers x refs) and useless to an agent as text; only
    # expand_refs_guided consumes it, so it lives in the ledger not the payload.
    session.set_cocitation(
        {
            "counts": counts,
            "citing_map": citing_map,
            "search_ranks": search_ranks,
            "ordered": ordered,
            "strong": strong_ids,
            "weak": weak_ids,
            "min_count": min_count,
        }
    )

    def _summary(ref: str) -> Dict[str, Any]:
        record = session.store.get_record(ref)
        return {
            "openalex_id": ref,
            "co_citation_count": counts[ref],
            "title": (record.title if record else "")[:160],
            "year": record.year if record else None,
            "cited_by_count": record.citation_count if record else None,
            "in_store": record is not None,
        }

    return {
        "session_id": session.session_id,
        "co_cited": [_summary(ref) for ref in ordered[:50]],
        "co_cited_total": len(ordered),
        "strong_bucket": len(strong_ids),
        "weak_bucket": len(weak_ids),
        "fetched": fetched,
        "added": added,
        "min_count": min_count,
        "total": len(session.store.get_all_papers()),
    }


async def _expand_refs_guided(
    req: S.ExpandRefsGuidedRequest, deps: Optional[CiteFlowDeps]
) -> Dict[str, Any]:
    from metasci_citeflow.graph import cocitation as cc

    session = Session.open(req.session_id, root=_root(req.session_dir))
    profile = session.profile
    payload = session.cocitation
    if not payload:
        raise ValueError("Run cf.citations.co_cite before cf.citations.expand_refs_guided")

    top_k = req.top_k_co_cited or profile.refs.top_k_co_cited
    max_citing = req.max_citing_papers or profile.refs.max_citing_papers
    limit_per_work = req.limit_per_work or profile.refs.max_per_seed

    source_ids = cc.select_papers_to_expand(
        payload.get("ordered", [])[:top_k],
        payload.get("citing_map", {}),
        payload.get("search_ranks", {}),
        max_citing_papers=max_citing,
    )
    if not source_ids:
        return {
            "session_id": session.session_id,
            "source_ids": [],
            "refs_fetched": 0,
            "added": 0,
            "total": len(session.store.get_all_papers()),
        }

    refs_by_source = await resolve_deps(deps).require_openalex().batch_get_references(
        source_ids, limit_per_work=limit_per_work
    )
    all_refs = [paper for refs in refs_by_source.values() for paper in refs]

    new_records = session.store.add_papers(
        all_refs, source="citation", parent_ids=source_ids, api_name="openalex"
    )
    expanded_ids = [paper.get("openalex_id") for paper in all_refs if paper.get("openalex_id")]

    session.record_round(
        round_num=0,
        phase="refs",
        source_ids=source_ids,
        expanded_ids=list(dict.fromkeys(expanded_ids)),
        new_ids=[record.openalex_id or record.corpus_id for record in new_records],
        params={
            "top_k_co_cited": top_k,
            "max_citing_papers": max_citing,
            "limit_per_work": limit_per_work,
        },
    )

    return {
        "session_id": session.session_id,
        "source_ids": source_ids,
        "refs_fetched": len(all_refs),
        "added": len(new_records),
        "total": len(session.store.get_all_papers()),
    }


async def _seeds_select_refs(
    req: S.SeedsSelectRefsRequest, deps: Optional[CiteFlowDeps]
) -> Dict[str, Any]:
    from metasci_citeflow.graph.seeder import Seeder, prepare_candidates

    session = Session.open(req.session_id, root=_root(req.session_dir))
    profile = session.profile
    payload = session.cocitation
    if not payload:
        raise ValueError("Run cf.citations.co_cite before cf.seeds.select_refs")

    query = session.query or ""
    if not query:
        raise ValueError("Session has no query; run cf.query.analyze first")

    config = profile.refs.co_seed_selection
    strong = prepare_candidates(
        [session.store.get_record(ref) for ref in payload.get("strong", [])],
        max_citation_exclude=config.max_citation_exclude,
        year_floor=profile.cocitation.year_floor,
    )
    weak = prepare_candidates(
        [session.store.get_record(ref) for ref in payload.get("weak", [])],
        max_citation_exclude=config.max_citation_exclude,
        year_floor=profile.cocitation.year_floor,
    )

    resolved_deps = resolve_deps(deps)
    seeder = Seeder(
        resolved_deps.require_llm(),
        query=query,
        profile=profile,
        sleep=resolved_deps.sleep,
    )
    result = await seeder.select_from_co_citations(strong, weak)

    seed_ids = [
        paper.get("openalex_id") or paper.get("corpus_id") for paper in result["seeds"]
    ]
    seed_ids = [sid for sid in seed_ids if sid]
    tag = req.tag or f"seed_r{req.round}_refs"
    session.store.mark_as_seeds(seed_ids, tag=tag)

    session.record_round(
        round_num=req.round,
        phase="seeds_refs",
        seed_ids=seed_ids,
        params={
            "strategies_used": result["strategies_used"],
            "budget": result["budget"],
            "enforce_limits": profile.seed_llm.enforce_limits,
        },
        candidates={"strong": len(strong), "weak": len(weak)},
    )

    return {
        "session_id": session.session_id,
        "seed_ids": seed_ids,
        "seeds": [
            {
                "openalex_id": paper.get("openalex_id"),
                "title": (paper.get("title") or "")[:160],
                "year": paper.get("year"),
                "cited_by_count": paper.get("cited_by_count") or paper.get("citation_count"),
            }
            for paper in result["seeds"]
        ],
        "total_seed_citations": result["total_seed_citations"],
        "strategies_used": result["strategies_used"],
        "budget": result["budget"],
        "candidates": {"strong": len(strong), "weak": len(weak)},
        "llm_batches": result["batches"],
        "reasoning": result["reasoning"],
    }


async def _seeds_mark(req: S.SeedsMarkRequest, deps: Optional[CiteFlowDeps]) -> Dict[str, Any]:
    session = Session.open(req.session_id, root=_root(req.session_dir))
    marked = session.store.mark_as_seeds(req.paper_ids, tag=req.tag)
    session.save()
    return {
        "session_id": session.session_id,
        "marked": marked,
        "total_seeds": sum(1 for p in session.store.get_all_papers() if p.is_seed),
    }


async def _eval_score(req: S.EvalScoreRequest, deps: Optional[CiteFlowDeps]) -> Dict[str, Any]:
    from metasci_citeflow.eval import Benchmark, evaluate_ranking, store_coverage

    session = Session.open(req.session_id, root=_root(req.session_dir))
    query = Benchmark.load(req.benchmark_path).get(req.query_id)
    papers = session.store.get_all_papers()

    if req.ranked_paper_ids is None:
        result = store_coverage(papers, query)
        result["session_id"] = session.session_id
        result["store_papers"] = len(papers)
        result["ranking_scored"] = False
        return result

    ranked = session.store.get_records_by_ids(req.ranked_paper_ids)
    metrics = evaluate_ranking(ranked, query, store_papers=papers)
    payload = metrics.to_dict()
    payload["session_id"] = session.session_id
    payload["store_papers"] = len(papers)
    payload["ranking_scored"] = True
    return payload


async def _eval_compare(req: S.EvalCompareRequest, deps: Optional[CiteFlowDeps]) -> Dict[str, Any]:
    from metasci_citeflow.eval import Benchmark, store_coverage

    benchmark = Benchmark.load(req.benchmark_path)
    rows: List[Dict[str, Any]] = []

    for session_id in req.session_ids:
        session = Session.open(session_id, root=_root(req.session_dir))
        papers = session.store.get_all_papers()
        targets = req.query_ids or [
            qid for qid in benchmark.query_ids() if qid == session.ledger.get("query_id")
        ]
        for query_id in targets:
            if query_id not in benchmark:
                continue
            coverage = store_coverage(papers, benchmark.get(query_id))
            rows.append(
                {
                    "session_id": session_id,
                    "profile": session.profile.name,
                    "store_papers": len(papers),
                    **coverage,
                }
            )

    return {"rows": rows}


def _targets(session: Session, paper_ids: Optional[List[str]]) -> List[Any]:
    return (
        session.store.get_records_by_ids(paper_ids)
        if paper_ids
        else session.store.get_all_papers()
    )


async def _store_autoscore(req: S.AutoscoreRequest, deps: Optional[CiteFlowDeps]) -> Dict[str, Any]:
    from metasci_citeflow.scoring.autoscore import autoscore

    session = Session.open(req.session_id, root=_root(req.session_dir))
    analysis = session.analysis or {}
    resolved = resolve_deps(deps)

    try:
        reranker = resolved.require_reranker()
    except Exception:
        # Missing token/deps must not abort scoring; autoscore reports it as a diagnostic
        # and still writes the two free signals.
        reranker = None

    report = await autoscore(
        session.store,
        records=_targets(session, req.paper_ids),
        rerank_query=analysis.get("rerank_query", ""),
        terms=analysis.get("discriminative_terms") or {},
        reranker=reranker,
        max_papers=req.max_papers or session.profile.final_max_papers,
        force_sim=req.force_sim,
    )
    session.save()
    report["session_id"] = session.session_id
    return report


async def _score_relevance(
    req: S.ScoreRelevanceRequest, deps: Optional[CiteFlowDeps]
) -> Dict[str, Any]:
    from metasci_citeflow.scoring.reranker import score_relevance

    session = Session.open(req.session_id, root=_root(req.session_dir))
    analysis = session.analysis or {}
    query_text = req.query_text or analysis.get("rerank_query") or session.query or ""
    if not query_text:
        raise ValueError("No rerank query; run cf.query.analyze or pass query_text.")

    scores, report = await score_relevance(
        _targets(session, req.paper_ids),
        query_text,
        resolve_deps(deps).require_reranker(),
        force=req.force,
    )
    if scores:
        session.store.batch_update_scores(scores, field="embedding_sim")
    session.save()
    report["session_id"] = session.session_id
    report["query_text"] = query_text
    return report


async def _score_keywords(
    req: S.ScoreKeywordsRequest, deps: Optional[CiteFlowDeps]
) -> Dict[str, Any]:
    from metasci_citeflow.scoring.keywords import score_records

    session = Session.open(req.session_id, root=_root(req.session_dir))
    analysis = session.analysis or {}
    terms = req.terms or analysis.get("discriminative_terms") or {}
    if not terms:
        raise ValueError("No discriminative terms; run cf.query.analyze or pass terms.")

    scores, report = score_records(_targets(session, req.paper_ids), terms, force=req.force)
    if scores:
        session.store.batch_update_scores(scores, field="keyword_match_score")
    session.save()
    report["session_id"] = session.session_id
    return report


async def _papers_filter(req: S.PapersFilterRequest, deps: Optional[CiteFlowDeps]) -> Dict[str, Any]:
    from metasci_citeflow.filters import apply_filters

    session = Session.open(req.session_id, root=_root(req.session_dir))
    records = _targets(session, req.paper_ids)

    max_citations, min_citations, year_range = req.max_citations, req.min_citations, None
    if req.year_range:
        year_range = (req.year_range[0], req.year_range[1])
    if req.profile_key:
        preset = getattr(session.profile, req.profile_key, None)
        if preset is None:
            raise ValueError(f"Unknown profile filter key: {req.profile_key}")
        max_citations = max_citations if max_citations is not None else preset.max_citations
        year_range = year_range or preset.year_range

    kept, reasons = apply_filters(
        records,
        max_citations=max_citations,
        min_citations=min_citations,
        year_range=year_range,
    )
    paper_ids = [r.openalex_id or r.corpus_id for r in kept]
    return {
        "session_id": session.session_id,
        "paper_ids": [pid for pid in paper_ids if pid],
        "kept": len(kept),
        "dropped": len(records) - len(kept),
        "drop_reasons": reasons,
        "filters_used": {
            "max_citations": max_citations,
            "min_citations": min_citations,
            "year_range": list(year_range) if year_range else None,
        },
    }


async def _store_rank(req: S.StoreRankRequest, deps: Optional[CiteFlowDeps]) -> Dict[str, Any]:
    from metasci_citeflow.profiles import weights_for

    session = Session.open(req.session_id, root=_root(req.session_dir))
    records = _targets(session, req.paper_ids)

    weights = req.weights
    if weights is None:
        key = req.profile_key or "final_sort_weights_1"
        preset = getattr(session.profile, key, None)
        if preset is None:
            raise ValueError(f"Unknown profile weight key: {key}")
        weights = weights_for(preset)

    ranked = session.store.rank_by_importance(
        papers=records,
        weights=weights,
        # embedding_sim is the primary relevance source; search_rank is the fallback for
        # papers the reranker never scored, and 0.02 the floor for everything else.
        relevance_priority=["embedding_sim", "search_rank", 0.02],
    )

    judged = set(session.judged_ids)
    if req.boost_judged and judged:
        for record in ranked:
            key = record.openalex_id or record.corpus_id
            if key in judged:
                record.importance_score = (record.importance_score or 0.0) + 0.1
        ranked.sort(key=lambda r: r.importance_score or 0.0, reverse=True)

    if req.dedupe_by_title:
        seen: Dict[str, Any] = {}
        for record in ranked:
            title = " ".join((record.title or "").lower().split())
            if not title:
                seen[f"__notitle__{id(record)}"] = record
            elif title not in seen:
                seen[title] = record
        ranked = sorted(seen.values(), key=lambda r: r.importance_score or 0.0, reverse=True)

    top = ranked[: req.top_k]
    session.save()
    return {
        "session_id": session.session_id,
        "papers": [
            {
                "openalex_id": r.openalex_id,
                "corpus_id": r.corpus_id,
                "title": (r.title or "")[:160],
                "year": r.year,
                "cited_by_count": r.citation_count,
                "importance_score": round(r.importance_score or 0.0, 4),
                "embedding_sim": r.embedding_sim,
                "keyword_match_score": r.keyword_match_score,
                "in_domain_citation_score": r.in_domain_citation_score,
                "is_seed": r.is_seed,
            }
            for r in top
        ],
        "paper_ids": [r.openalex_id or r.corpus_id for r in top],
        "returned": len(top),
        "total": len(ranked),
        "weights_used": weights,
        "boost_judged": bool(req.boost_judged and judged),
    }


async def _judge_relevance(
    req: S.JudgeRelevanceRequest, deps: Optional[CiteFlowDeps]
) -> Dict[str, Any]:
    from metasci_citeflow.llm.relevance_selector import RelevanceSelector, judge_batches

    session = Session.open(req.session_id, root=_root(req.session_dir))
    analysis = session.analysis or {}
    query = session.query or ""
    if not query:
        raise ValueError("Session has no query; run cf.query.analyze first")

    records = session.store.get_records_by_ids(req.paper_ids)
    papers = [record.to_dict() for record in records]
    batches = (
        [tuple(b) for b in req.batches] if req.batches else session.profile.loop.judge_batches
    )

    selector = RelevanceSelector(
        resolve_deps(deps).require_llm(), model=session.profile.models.judge
    )
    result = await judge_batches(
        selector,
        query,
        papers,
        batches=batches,
        structured_keywords=analysis.get("structured_keywords") or [],
    )

    newly = session.add_judged(result["judged_ids"])
    session.store.add_tags(result["judged_ids"], "llm_judged")
    session.save()

    return {
        "session_id": session.session_id,
        "judged_ids": result["judged_ids"],
        "newly_judged": newly,
        "total_judged": len(session.judged_ids),
        "judged": [
            {"openalex_id": p.get("openalex_id"), "title": (p.get("title") or "")[:140]}
            for p in result["selected_papers"]
        ],
        "reasoning": result["reasoning"],
    }


async def _store_distributions(
    req: S.DistributionsRequest, deps: Optional[CiteFlowDeps]
) -> Dict[str, Any]:
    from metasci_citeflow.llm.params_decider import citation_distribution, year_distribution

    session = Session.open(req.session_id, root=_root(req.session_dir))
    papers = [r.to_dict() for r in session.store.get_records_by_ids(req.paper_ids)]
    return {
        "session_id": session.session_id,
        "papers": len(papers),
        "citation_distribution": citation_distribution(papers),
        "year_distribution": {str(k): v for k, v in year_distribution(papers).items()},
    }


async def _decide_params(req: S.DecideParamsRequest, deps: Optional[CiteFlowDeps]) -> Dict[str, Any]:
    from metasci_citeflow.llm.params_decider import CitationParamsDecider

    session = Session.open(req.session_id, root=_root(req.session_dir))
    decider = CitationParamsDecider(
        resolve_deps(deps).require_llm(), model=session.profile.models.decider
    )
    decision = await decider.decide(
        total_seed_citations=req.total_seed_citations,
        citation_distribution=req.citation_distribution,
        year_distribution={int(k): v for k, v in req.year_distribution.items()},
        year_end=req.year_end or session.profile.year_end,
    )
    decision["session_id"] = session.session_id
    return decision


async def _seeds_select_citations(
    req: S.SeedsSelectCitationsRequest, deps: Optional[CiteFlowDeps]
) -> Dict[str, Any]:
    """The per-round seed pick: score, filter, rank, judge, then choose seeds."""
    from metasci_citeflow.filters import apply_filters
    from metasci_citeflow.graph.seeder import Seeder
    from metasci_citeflow.llm.relevance_selector import RelevanceSelector, judge_batches
    from metasci_citeflow.profiles import weights_for
    from metasci_citeflow.scoring.autoscore import autoscore

    session = Session.open(req.session_id, root=_root(req.session_dir))
    profile = session.profile
    analysis = session.analysis or {}
    query = session.query or ""
    if not query:
        raise ValueError("Session has no query; run cf.query.analyze first")

    # Candidate pool: what the previous round newly reached, not the whole store.
    if req.paper_ids:
        candidate_ids = req.paper_ids
    else:
        source_round = req.from_round if req.from_round is not None else req.round - 1
        row = session.get_round(source_round)
        if row is None:
            raise ValueError(
                f"No round {source_round} in the ledger; run an expansion first or pass paper_ids."
            )
        candidate_ids = row.get("expanded_ids") or []
    if not candidate_ids:
        return {
            "session_id": session.session_id,
            "seed_ids": [],
            "total_seed_citations": 0,
            "top_paper_ids": [],
            "judged_ids": [],
            "note": "no candidates from the source round",
        }

    resolved = resolve_deps(deps)
    records = session.store.get_records_by_ids(candidate_ids)

    try:
        reranker = resolved.require_reranker()
    except Exception:
        reranker = None
    await autoscore(
        session.store,
        records=records,
        rerank_query=analysis.get("rerank_query", ""),
        terms=analysis.get("discriminative_terms") or {},
        reranker=reranker,
        max_papers=profile.final_max_papers,
    )

    # Papers already used as seeds must not be re-expanded.
    fresh = [r for r in records if not r.is_seed]
    filtered, drop_reasons = apply_filters(
        fresh,
        max_citations=profile.filter_params_cite.max_citations,
        year_range=profile.filter_params_cite.year_range,
    )

    ranked = session.store.rank_by_importance(
        papers=filtered,
        weights=weights_for(profile.mid_sort_weights),
        relevance_priority=["embedding_sim", "search_rank", 0.02],
    )
    top_papers = [r.to_dict() for r in ranked[: profile.loop.top_papers]]

    selector = RelevanceSelector(resolved.require_llm(), model=profile.models.judge)
    judged = await judge_batches(
        selector,
        query,
        top_papers,
        batches=profile.loop.judge_batches,
        structured_keywords=analysis.get("structured_keywords") or [],
    )
    session.add_judged(judged["judged_ids"])

    seeder = Seeder(
        resolved.require_llm(), query=query, profile=profile, sleep=resolved.sleep
    )
    config = profile.refs.co_seed_selection
    picked = await seeder.select_seeds_with_llm(
        top_papers[: profile.loop.seed_candidate_pool],
        min_seeds=config.min_seeds,
        min_total_citations=config.min_total_citations,
        enforce_limits=profile.seed_llm.enforce_limits,
    )

    seed_ids = [p.get("openalex_id") or p.get("corpus_id") for p in picked["seeds"]]
    seed_ids = [s for s in seed_ids if s]
    session.store.mark_as_seeds(seed_ids, tag=f"seed_r{req.round}_citations")

    session.record_round(
        round_num=req.round,
        phase="seeds_citations",
        seed_ids=seed_ids,
        params={"candidates": len(candidate_ids), "drop_reasons": drop_reasons},
    )

    return {
        "session_id": session.session_id,
        "seed_ids": seed_ids,
        "seeds": [
            {
                "openalex_id": p.get("openalex_id"),
                "title": (p.get("title") or "")[:140],
                "cited_by_count": p.get("cited_by_count") or p.get("citation_count"),
            }
            for p in picked["seeds"]
        ],
        "total_seed_citations": picked["total_citations"],
        "top_paper_ids": [r.openalex_id or r.corpus_id for r in ranked[: profile.loop.top_papers]],
        "judged_ids": judged["judged_ids"],
        "candidates": len(candidate_ids),
        "after_filter": len(filtered),
        "drop_reasons": drop_reasons,
        "reasoning": picked["reasoning"],
    }


async def _fetch_forward(req: S.FetchForwardRequest, deps: Optional[CiteFlowDeps]) -> Dict[str, Any]:
    from metasci_citeflow.providers.openalex_graph import FIELD_IDS

    session = Session.open(req.session_id, root=_root(req.session_dir))
    profile = session.profile

    seed_ids = req.seed_ids
    if not seed_ids:
        row = session.get_round(req.round, "seeds_citations") or session.get_round(
            req.round - 1, "seeds_refs"
        )
        seed_ids = (row or {}).get("seed_ids") or []
    if not seed_ids:
        return {
            "session_id": session.session_id,
            "seeds": 0,
            "fetched": 0,
            "added": 0,
            "note": "no seeds for this round",
        }

    year_end = req.year_end or profile.year_end
    year_range = (req.year_start, year_end) if req.year_start or year_end else None
    field_id = FIELD_IDS.get((req.field or "").lower()) if req.field else None

    citations = await resolve_deps(deps).require_openalex().get_citations(
        seed_ids,
        year_range=year_range,
        min_cited_by=req.min_citations,
        field_id=field_id,
        max_per_work=req.max_per_seed,
    )
    all_papers = [paper for papers in citations.values() for paper in papers]

    new_records = session.store.add_papers(
        all_papers, source="citation", parent_ids=seed_ids, api_name="openalex"
    )
    expanded_ids = list(
        dict.fromkeys(p["openalex_id"] for p in all_papers if p.get("openalex_id"))
    )

    session.record_round(
        round_num=req.round,
        phase="citations",
        seed_ids=seed_ids,
        expanded_ids=expanded_ids,
        new_ids=[r.openalex_id or r.corpus_id for r in new_records],
        params={
            "year_range": list(year_range) if year_range else None,
            "min_citations": req.min_citations,
            "field": req.field,
        },
    )

    return {
        "session_id": session.session_id,
        "seeds": len(seed_ids),
        "fetched": len(all_papers),
        "expanded_unique": len(expanded_ids),
        "added": len(new_records),
        "total": len(session.store.get_all_papers()),
        "per_seed": {seed: len(papers) for seed, papers in citations.items()},
    }


async def _rounds_list(req: S.RoundsListRequest, deps: Optional[CiteFlowDeps]) -> Dict[str, Any]:
    session = Session.open(req.session_id, root=_root(req.session_dir))
    return {"rounds": session.rounds_summary()}


async def _rounds_get(req: S.RoundsGetRequest, deps: Optional[CiteFlowDeps]) -> Dict[str, Any]:
    session = Session.open(req.session_id, root=_root(req.session_dir))
    row = session.get_round(req.round, req.phase)
    if row is None:
        return {"found": False, "round": None}
    return {"found": True, **row}


async def _store_stats(req: S.StoreStatsRequest, deps: Optional[CiteFlowDeps]) -> Dict[str, Any]:
    session = Session.open(req.session_id, root=_root(req.session_dir))
    stats = _stats(session)
    stats["rounds_summary"] = session.rounds_summary()
    return stats


# ── registry ──────────────────────────────────────────────────────────────────

TOOLS: Dict[str, CiteFlowTool] = {
    tool.name: tool
    for tool in [
        CiteFlowTool(
            name="cf.session.open",
            description=(
                "Create a CiteFlow session or reattach to an existing one. Sessions are "
                "file-backed, so every other cf.* tool can run in a separate process."
            ),
            input_model=S.SessionOpenRequest,
            handler=_session_open,
            examples=[
                'cf.session.open {"query": "factual consistency metrics for summarization"}',
                'cf.session.open {"profile": "acadeepr-run1", "overrides": {"refs.top_k_co_cited": 10}}',
            ],
        ),
        CiteFlowTool(
            name="cf.session.info",
            description="Report a session's profile, query analysis, round history and store stats.",
            input_model=S.SessionInfoRequest,
            handler=_session_info,
            examples=['cf.session.info {"session_id": "cf_1a2b3c4d5e"}'],
        ),
        CiteFlowTool(
            name="cf.session.export",
            description="Flush a session to disk and report the artifact paths.",
            input_model=S.SessionExportRequest,
            handler=_session_export,
            examples=['cf.session.export {"session_id": "cf_1a2b3c4d5e"}'],
        ),
        CiteFlowTool(
            name="cf.profiles.list",
            description="List the named parameter presets, with provenance.",
            input_model=S.ProfilesListRequest,
            handler=_profiles_list,
            examples=["cf.profiles.list {}"],
        ),
        CiteFlowTool(
            name="cf.profiles.show",
            description="Show every resolved parameter of one preset.",
            input_model=S.ProfilesShowRequest,
            handler=_profiles_show,
            examples=['cf.profiles.show {"name": "acadeepr-run1"}'],
        ),
        CiteFlowTool(
            name="cf.query.analyze",
            description=(
                "Turn a research question into structured keywords, Semantic Scholar "
                "search queries and weighted discriminative terms, storing them on the "
                "session. Everything downstream (search, reranking, keyword scoring) "
                "reads these. Pass from_yaml to pin a known-good analysis instead."
            ),
            input_model=S.QueryAnalyzeRequest,
            handler=_query_analyze,
            examples=[
                'cf.query.analyze {"session_id": "cf_1a2b3c4d5e"}',
                'cf.query.analyze {"session_id": "cf_1a2b", "from_yaml": "inputConfig/run_my_1/semantic_5.yaml"}',
            ],
        ),
        CiteFlowTool(
            name="cf.papers.search",
            description=(
                "Run the session's search queries against Semantic Scholar, merge and "
                "de-duplicate, then resolve every hit to an OpenAlex work id. The "
                "resolution step is what makes citation expansion possible at all - "
                "check the reported openalex_coverage before expanding."
            ),
            input_model=S.PapersSearchRequest,
            handler=_papers_search,
            examples=[
                'cf.papers.search {"session_id": "cf_1a2b3c4d5e"}',
                'cf.papers.search {"session_id": "cf_1a2b", "queries": ["factual alignment"], "limit": 50}',
            ],
        ),
        CiteFlowTool(
            name="cf.papers.repair",
            description=(
                "Retry OpenAlex resolution and abstract backfill for store papers that "
                "are still missing them. Idempotent; run this when coverage is low "
                "rather than expanding on an incomplete store."
            ),
            input_model=S.PapersRepairRequest,
            handler=_papers_repair,
            examples=['cf.papers.repair {"session_id": "cf_1a2b3c4d5e"}'],
        ),
        CiteFlowTool(
            name="cf.citations.co_cite",
            description=(
                "Find works that many store papers all cite. Run this straight after "
                "cf.papers.search and BEFORE any expansion: the result decides which "
                "papers are worth pulling references from. A strong_bucket below 3 means "
                "the search results share too little common ground to expand from."
            ),
            input_model=S.CoCiteRequest,
            handler=_co_cite,
            examples=['cf.citations.co_cite {"session_id": "cf_1a2b3c4d5e"}'],
        ),
        CiteFlowTool(
            name="cf.citations.expand_refs_guided",
            description=(
                "Backward expansion. Walks the co-cited works best-first and pulls "
                "references from the store papers citing them, ordered by original "
                "search rank, until max_citing_papers is reached."
            ),
            input_model=S.ExpandRefsGuidedRequest,
            handler=_expand_refs_guided,
            examples=['cf.citations.expand_refs_guided {"session_id": "cf_1a2b3c4d5e"}'],
        ),
        CiteFlowTool(
            name="cf.seeds.select_refs",
            description=(
                "Pick expansion seeds from the co-citation buckets using the LLM. Asks "
                "whether a paper answering this query would actually cite each candidate, "
                "and keeps going until a seed-count and citation budget is met. Selecting "
                "nothing is a valid answer - check budget.met rather than assuming seeds."
            ),
            input_model=S.SeedsSelectRefsRequest,
            handler=_seeds_select_refs,
            examples=['cf.seeds.select_refs {"session_id": "cf_1a2b3c4d5e"}'],
        ),
        CiteFlowTool(
            name="cf.seeds.mark",
            description="Mark specific papers as seeds (for user-supplied starting points).",
            input_model=S.SeedsMarkRequest,
            handler=_seeds_mark,
            examples=['cf.seeds.mark {"session_id": "cf_1a2b", "paper_ids": ["W123"]}'],
        ),
        CiteFlowTool(
            name="cf.eval.score",
            description=(
                "Score a session against the paper-finder benchmark. Without "
                "ranked_paper_ids it reports ground-truth store coverage - whether the "
                "papers were found at all, which is the ceiling on recall and the only "
                "meaningful metric before a final ranking exists."
            ),
            input_model=S.EvalScoreRequest,
            handler=_eval_score,
            examples=[
                'cf.eval.score {"session_id": "cf_1a2b", "query_id": "semantic_5"}',
            ],
        ),
        CiteFlowTool(
            name="cf.eval.compare",
            description="Compare ground-truth coverage across sessions, for A/B runs.",
            input_model=S.EvalCompareRequest,
            handler=_eval_compare,
            examples=[
                'cf.eval.compare {"session_ids": ["cf_a", "cf_b"], "query_ids": ["semantic_5"]}'
            ],
        ),
        CiteFlowTool(
            name="cf.store.autoscore",
            description=(
                "Compute all three relevance signals at once: in-domain citation "
                "concentration, cross-encoder semantic relevance, and discriminative-term "
                "matching. Only the semantic signal costs API calls, so max_papers caps "
                "it; check the reported coverage and diagnostics before ranking."
            ),
            input_model=S.AutoscoreRequest,
            handler=_store_autoscore,
            examples=['cf.store.autoscore {"session_id": "cf_1a2b3c4d5e"}'],
        ),
        CiteFlowTool(
            name="cf.score.relevance",
            description=(
                "Score papers against the query with the BAAI/bge-reranker cross-encoder. "
                "Requires RERANKER_API_TOKEN. Skips already-scored papers unless force."
            ),
            input_model=S.ScoreRelevanceRequest,
            handler=_score_relevance,
            examples=['cf.score.relevance {"session_id": "cf_1a2b"}'],
        ),
        CiteFlowTool(
            name="cf.score.keywords",
            description=(
                "Score papers by rarity-weighted discriminative terms (noisy-OR). Reports "
                "whether spaCy lemmas or the weaker whitespace fallback were used - "
                "scores from the two modes are not comparable."
            ),
            input_model=S.ScoreKeywordsRequest,
            handler=_score_keywords,
            examples=['cf.score.keywords {"session_id": "cf_1a2b"}'],
        ),
        CiteFlowTool(
            name="cf.papers.filter",
            description=(
                "Filter papers by citation ceiling and year window. Use "
                "profile_key='filter_params_cite' mid-loop and 'filter_params' for the "
                "final set. Papers with an unknown year are kept."
            ),
            input_model=S.PapersFilterRequest,
            handler=_papers_filter,
            examples=['cf.papers.filter {"session_id": "cf_1a2b", "profile_key": "filter_params"}'],
        ),
        CiteFlowTool(
            name="cf.store.rank",
            description=(
                "Rank papers with a weighted blend of the scored signals. profile_key "
                "picks a validated preset (mid_sort_weights / final_sort_weights_1 / _2); "
                "weights overrides it outright. Run cf.store.autoscore first or relevance "
                "falls back to search rank."
            ),
            input_model=S.StoreRankRequest,
            handler=_store_rank,
            examples=[
                'cf.store.rank {"session_id": "cf_1a2b", "profile_key": "final_sort_weights_1", "top_k": 100}'
            ],
        ),
        CiteFlowTool(
            name="cf.papers.judge_relevance",
            description=(
                "Mark which ranked candidates plausibly answer the query. Judged papers "
                "form a set (not a score) that gives a +0.1 rank boost. At most 4 per "
                "batch and an empty result is valid - do not treat that as failure."
            ),
            input_model=S.JudgeRelevanceRequest,
            handler=_judge_relevance,
            examples=['cf.papers.judge_relevance {"session_id": "cf_1a2b", "paper_ids": ["W1","W2"]}'],
        ),
        CiteFlowTool(
            name="cf.store.distributions",
            description=(
                "Citation and year histograms for a paper set, shaped for "
                "cf.citations.decide_params. Compute these over the ranked top papers, "
                "NOT over the seeds - the decider takes seed citations separately."
            ),
            input_model=S.DistributionsRequest,
            handler=_store_distributions,
            examples=['cf.store.distributions {"session_id": "cf_1a2b", "paper_ids": ["W1"]}'],
        ),
        CiteFlowTool(
            name="cf.citations.decide_params",
            description=(
                "Choose year_start and min_citations for the next forward fetch from the "
                "current distributions. The reply is clamped in Python (year >= 2010, "
                "min_citations <= 5); check the 'clamped' flag."
            ),
            input_model=S.DecideParamsRequest,
            handler=_decide_params,
            examples=[
                'cf.citations.decide_params {"session_id": "cf_1a2b", "total_seed_citations": 800, "citation_distribution": {"0-50": 10}, "year_distribution": {"2021": 5}}'
            ],
        ),
        CiteFlowTool(
            name="cf.seeds.select_citations",
            description=(
                "Pick the next round's expansion seeds. Scores and filters the previous "
                "round's newly reached papers, ranks them, judges the top for relevance, "
                "then asks the seed LLM to choose. Returns top_paper_ids for the "
                "distributions step and seed_ids for the fetch."
            ),
            input_model=S.SeedsSelectCitationsRequest,
            handler=_seeds_select_citations,
            examples=['cf.seeds.select_citations {"session_id": "cf_1a2b", "round": 2}'],
        ),
        CiteFlowTool(
            name="cf.citations.fetch_forward",
            description=(
                "Forward expansion: fetch papers citing the seeds, filtered server-side "
                "by year, citation count and optionally field, with full pagination. "
                "This is the main recall engine - each round's expanded_ids feed the next "
                "round's seed selection."
            ),
            input_model=S.FetchForwardRequest,
            handler=_fetch_forward,
            examples=[
                'cf.citations.fetch_forward {"session_id": "cf_1a2b", "round": 2, "year_start": 2018, "min_citations": 2}'
            ],
        ),
        CiteFlowTool(
            name="cf.rounds.list",
            description="Summarise each expansion round: phase, seeds used, papers expanded and newly added.",
            input_model=S.RoundsListRequest,
            handler=_rounds_list,
            examples=['cf.rounds.list {"session_id": "cf_1a2b3c4d5e"}'],
        ),
        CiteFlowTool(
            name="cf.rounds.get",
            description=(
                "Fetch one round's full record, including the exact paper ids that round "
                "expanded — this is what seeds the next round."
            ),
            input_model=S.RoundsGetRequest,
            handler=_rounds_get,
            examples=['cf.rounds.get {"session_id": "cf_1a2b3c4d5e", "round": "last"}'],
        ),
        CiteFlowTool(
            name="cf.store.stats",
            description=(
                "Store statistics plus the signals that drive expansion decisions: "
                "in-domain ratio, per-round yield, and OpenAlex/abstract/score coverage."
            ),
            input_model=S.StoreStatsRequest,
            handler=_store_stats,
            examples=['cf.store.stats {"session_id": "cf_1a2b3c4d5e"}'],
        ),
    ]
}


def list_tools() -> List[str]:
    return sorted(TOOLS)


def describe_tool(name: str) -> Dict[str, Any]:
    return _get_tool(name).to_card()


def tool_schema(name: str) -> Dict[str, Any]:
    return _get_tool(name).input_model.model_json_schema()


def _get_tool(name: str) -> CiteFlowTool:
    try:
        return TOOLS[name]
    except KeyError as exc:
        raise KeyError(f"Unknown CiteFlow tool: {name}") from exc


async def run_tool(
    name: str,
    arguments: Optional[Dict[str, Any]] = None,
    *,
    deps: Optional[CiteFlowDeps] = None,
) -> MetaSciResult:
    """Validate a payload against the tool's model, then dispatch."""
    tool = _get_tool(name)
    payload = arguments or {}
    request = tool.input_model(**payload)
    data = await tool.handler(request, deps)
    return MetaSciResult(
        command=name,
        input=request.model_dump(mode="json"),
        data=data,
        metadata={"tool": name},
    )
