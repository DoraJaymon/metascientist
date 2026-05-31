"""CiteFlow deep_search — minimal but complete pipeline.

Flow (simplified from CiteFlowPipeline):
  1. QueryAnalyzer  → core_keywords + criteria
  2. Iterative keyword search (S2, up to max_search_rounds)  → CuraLib
  3. Citation expansion (OA refs → seed selection → OA citations, 1 round)
  4. In-domain citation scoring + final ranking (recency + centrality + in-domain)
  5. Return MetaSciResult

LLM: uses OPENAI_API_KEY + OPENAI_BASE_URL env vars.
S2 API: optional S2_API_KEY for higher rate limits.
OpenAlex: polite pool via OPENALEX_EMAIL.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Result contract (mirrors MetaSciResult from metasci-universe) ────────────

@dataclass
class DeepSearchResult:
    """Structured result from deep_search()."""
    query: str
    papers: List[Dict[str, Any]] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    diagnostics: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Query: {self.query}",
            f"Papers found: {len(self.papers)}",
        ]
        for k, v in self.stats.items():
            lines.append(f"{k}: {v}")
        if self.diagnostics:
            lines.append("Diagnostics: " + "; ".join(self.diagnostics))
        return "\n".join(lines)

    def to_metasci_result(self):
        """Convert to MetaSciResult for metasci-universe tool registry."""
        try:
            from metasci_universe.schemas.common import MetaSciResult
            return MetaSciResult(
                command="deep_search",
                input={"query": self.query},
                data={"papers": self.papers},
                metadata=self.stats,
                diagnostics=self.diagnostics,
            )
        except ImportError:
            return self


# ── Config ────────────────────────────────────────────────────────────────────

@dataclass
class DeepSearchConfig:
    """Tuning knobs for deep_search()."""
    # Iterative search
    max_search_rounds: int = 3          # Max LLM-guided keyword search rounds
    search_limit_per_round: int = 50    # Papers fetched per S2 search round
    success_threshold: float = 0.5     # LLM score threshold for a "successful" round
    success_rounds_needed: int = 2      # Stop after this many successful rounds

    # LLM paper selection
    llm_eval_top_k: int = 12            # Top papers sent to LLM per round
    concurrent_llm_evals: int = 5       # Concurrent LLM calls for paper scoring

    # Citation expansion
    max_seeds: int = 5                  # Seeds for citation expansion
    max_refs_per_seed: int = 60         # Max refs fetched per seed
    max_citations_per_seed: int = 100   # Max forward citations per seed
    citation_year_range: Optional[tuple] = None  # (start, end) or None

    # Final output
    max_output_papers: int = 100
    final_weights: Dict[str, float] = field(default_factory=lambda: {
        "relevance": 0.6,
        "recency": 0.2,
        "centrality": 0.2,
    })

    # LLM
    model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))

    # Year upper limit for S2 search (None = no limit)
    year_upper_limit: Optional[int] = None


# ── LLM paper evaluator ───────────────────────────────────────────────────────

_EVAL_SYSTEM = """You evaluate whether an academic paper is relevant to a research question.
Score from 0 to 1 where:
  1.0 = directly addresses the question
  0.5 = partially relevant
  0.0 = unrelated
Respond with ONLY a JSON object: {"score": <float>, "rationale": "<one sentence>"}"""

_EVAL_USER = """Research question: {query}

Evaluation criteria:
{criteria_text}

Paper to evaluate:
Title: {title}
Abstract: {abstract}

Score this paper."""


async def _eval_paper(
    client: Any,
    model: str,
    query: str,
    criteria: List[Dict],
    paper: Dict,
    semaphore: asyncio.Semaphore,
) -> Optional[Dict[str, Any]]:
    criteria_text = "\n".join(f"- [{c['weight']:.2f}] {c['text']}" for c in criteria)
    async with semaphore:
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _EVAL_SYSTEM},
                    {"role": "user", "content": _EVAL_USER.format(
                        query=query,
                        criteria_text=criteria_text,
                        title=paper.get("title", ""),
                        abstract=(paper.get("abstract") or "")[:600],
                    )},
                ],
                response_format={"type": "json_object"},
            )
            import json
            data = json.loads(resp.choices[0].message.content)
            return {"score": float(data.get("score", 0)), "rationale": data.get("rationale", "")}
        except Exception as exc:
            logger.debug("LLM eval failed: %s", exc)
            return None


# ── Main pipeline ─────────────────────────────────────────────────────────────

async def deep_search(
    query: str,
    config: Optional[DeepSearchConfig] = None,
    *,
    max_papers: int = 100,
) -> DeepSearchResult:
    """Run a CiteFlow-style deep paper search.

    Args:
        query: Natural-language research question.
        config: Tuning config (uses defaults if None).
        max_papers: Max papers in result (overrides config.max_output_papers).

    Returns:
        DeepSearchResult with ranked paper list and stats.

    Requires env vars:
        OPENAI_API_KEY, OPENAI_BASE_URL (for LLM)
        OPENALEX_EMAIL (for polite OpenAlex pool, optional)
        S2_API_KEY (for higher S2 rate limits, optional)
    """
    if config is None:
        config = DeepSearchConfig()
    config.max_output_papers = max_papers

    diagnostics: List[str] = []

    # ── Imports ──────────────────────────────────────────────────────────────
    from openai import AsyncOpenAI
    from metasci_universe.memory.curalib import PaperStore
    from metasci_deepsearch.query_analyzer import QueryAnalyzer
    from metasci_deepsearch.citation_network import CitationNetwork
    from metasci_deepsearch.citation_fetcher import CitationFetcher
    from metasci_deepsearch.ranking import ImportanceSorter
    from metasci_deepsearch.providers.semantic_scholar import SemanticScholarSearchClient

    llm = AsyncOpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL"),
    )
    store = PaperStore()
    cn = CitationNetwork(store)
    fetcher = CitationFetcher()
    semaphore = asyncio.Semaphore(config.concurrent_llm_evals)

    # ── Phase 1: Query Understanding ─────────────────────────────────────────
    logger.info("[DeepSearch] Phase 1: QueryAnalyzer")
    qa = QueryAnalyzer(model=config.model)
    try:
        analysis = await qa.analyze(query, mode="simple")
    except Exception as exc:
        diagnostics.append(f"QueryAnalyzer failed ({exc}), using raw query as keywords")
        analysis = {"core_keywords": query, "criteria": []}

    core_keywords = analysis.get("core_keywords") or query
    criteria = analysis.get("criteria") or []
    logger.info("  core_keywords: %s", core_keywords)
    logger.info("  criteria: %d items", len(criteria))

    # ── Phase 2: Iterative keyword search (S2) ────────────────────────────────
    logger.info("[DeepSearch] Phase 2: Iterative search (max %d rounds)", config.max_search_rounds)
    successful_rounds = 0
    current_keywords = core_keywords
    keywords_tried: List[str] = []

    async with SemanticScholarSearchClient(year_upper_limit=config.year_upper_limit) as s2:
        for round_num in range(config.max_search_rounds):
            if current_keywords in keywords_tried:
                diagnostics.append(f"Round {round_num}: repeated keywords, skipping")
                break
            keywords_tried.append(current_keywords)
            logger.info("  Round %d — keywords: %s", round_num, current_keywords)

            papers_raw = await s2.search_papers(current_keywords, limit=config.search_limit_per_round)
            if not papers_raw:
                diagnostics.append(f"Round {round_num}: no papers from S2 search")
                break

            # Add to store
            for i, p in enumerate(papers_raw):
                p.external_info["search_rank"] = i + 1
            store.add_papers(
                [p.to_dict() for p in papers_raw],
                source="search",
                keywords=current_keywords,
                api_name="semantic_scholar",
            )
            logger.info("  Round %d: fetched %d papers (store total: %d)",
                        round_num, len(papers_raw), len(store.get_all_papers()))

            # LLM evaluate top-k
            top_papers = [p.to_dict() for p in papers_raw[:config.llm_eval_top_k]]
            eval_tasks = [
                _eval_paper(llm, config.model, query, criteria, p, semaphore)
                for p in top_papers
            ]
            eval_results = await asyncio.gather(*eval_tasks, return_exceptions=True)

            round_successful = False
            scores_to_update = []
            for p, res in zip(top_papers, eval_results):
                if isinstance(res, dict):
                    scores_to_update.append({
                        "corpus_id": p.get("corpus_id", ""),
                        "openalex_id": p.get("openalex_id"),
                        "score": res["score"],
                        "rationale": res.get("rationale", ""),
                    })
                    if res["score"] >= config.success_threshold:
                        round_successful = True

            store.update_scores(scores_to_update, score_type="llm")

            if round_successful:
                successful_rounds += 1
                logger.info("  Round %d: SUCCESS (scored papers > threshold)", round_num)
                if successful_rounds >= config.success_rounds_needed:
                    logger.info("  Reached %d successful rounds, stopping search", successful_rounds)
                    break

            # Rewrite keywords for next round
            if round_num < config.max_search_rounds - 1:
                current_keywords = await _rewrite_keywords(
                    llm, config.model, query, current_keywords, keywords_tried, round_successful
                )

    logger.info("[DeepSearch] Search phase done. Store: %d papers", len(store.get_all_papers()))

    # ── Phase 3: Citation expansion ───────────────────────────────────────────
    logger.info("[DeepSearch] Phase 3: Citation expansion")

    # Select seeds: top-k by LLM score, fallback to importance score
    all_records = store.get_all_papers()
    evaluated = [p for p in all_records if p.llm_score is not None]
    evaluated.sort(key=lambda p: p.llm_score or 0, reverse=True)
    seeds = evaluated[:config.max_seeds]

    if not seeds:
        # No LLM-scored papers — use importance sort fallback
        ranked = store.rank_by_importance(weights={"relevance": 0.4, "centrality": 0.4, "recency": 0.2})
        seeds = ranked[:config.max_seeds]

    seed_ids = [p.openalex_id or p.corpus_id for p in seeds if p.openalex_id or p.corpus_id]
    logger.info("  Seeds selected: %d", len(seed_ids))
    store.mark_as_seeds(seed_ids, tag="seed_r0")

    if seed_ids:
        try:
            # Fetch references
            refs_data = await fetcher.fetch_refs(
                seed_ids,
                limit_per_work=config.max_refs_per_seed,
            )
            all_refs = [p for refs in refs_data.values() for p in refs]
            logger.info("  Refs fetched: %d total", len(all_refs))
            if all_refs:
                store.add_papers(all_refs, source="citation", parent_ids=seed_ids, api_name="openalex")

            # Co-citation analysis to find additional seeds
            co_cited, _ = await cn.compute_co_citations_from_papers(
                papers=[p.to_dict() for p in store.get_all_papers()],
                min_count=2,
                fetcher=fetcher,
                auto_fetch=False,  # keep it simple for first run
                round_num=1,
            )
            logger.info("  Co-cited papers: %d", len(co_cited))
            if co_cited:
                store.add_papers(co_cited[:50], source="citation", api_name="openalex")

            # Fetch forward citations from seeds
            cit_data = await fetcher.fetch_citations(
                seed_ids,
                year_range=config.citation_year_range,
                max_per_work=config.max_citations_per_seed,
                supplement_with_s2=False,
            )
            all_cits = [p for cits in cit_data.values() for p in cits]
            logger.info("  Citations fetched: %d total", len(all_cits))
            if all_cits:
                store.add_papers(all_cits, source="citation", parent_ids=seed_ids, api_name="openalex")

        except Exception as exc:
            diagnostics.append(f"Citation expansion failed: {exc}")
            logger.warning("Citation expansion error: %s", exc, exc_info=True)

    logger.info("[DeepSearch] After expansion. Store: %d papers", len(store.get_all_papers()))

    # ── Phase 4: Scoring & ranking ────────────────────────────────────────────
    logger.info("[DeepSearch] Phase 4: Final scoring and ranking")
    cn.calculate_paper_scores()

    final_weights = {**config.final_weights}
    if any(p.in_domain_citation_score for p in store.get_all_papers()):
        final_weights["in_domain_citation_score"] = 0.15
        # Rescale other weights proportionally
        total = sum(v for k, v in final_weights.items() if k != "in_domain_citation_score")
        scale = 0.85 / total if total else 1.0
        for k in list(final_weights):
            if k != "in_domain_citation_score":
                final_weights[k] *= scale

    ranked = store.rank_by_importance(weights=final_weights)
    top_papers = [p.to_dict() for p in ranked[:config.max_output_papers]]

    stats = {
        **store.get_stats(),
        "successful_search_rounds": successful_rounds,
        "seeds_used": len(seed_ids),
    }

    logger.info("[DeepSearch] Done. Returning %d papers.", len(top_papers))
    return DeepSearchResult(query=query, papers=top_papers, stats=stats, diagnostics=diagnostics)


# ── Keyword rewriter ──────────────────────────────────────────────────────────

_REWRITE_SYS = "You are an academic search expert. Rewrite search keywords to find more relevant papers."
_REWRITE_USER_EXPAND = """Original query: {query}
Previous keywords used: {prev}
These keywords found relevant papers. Generate new, complementary keywords to expand coverage.
Output ONLY the new keyword string (2-5 terms, no explanation)."""
_REWRITE_USER_REGEN = """Original query: {query}
Previous keywords used: {prev}
These keywords found few relevant papers. Generate better keywords targeting the core topic.
Output ONLY the new keyword string (2-5 terms, no explanation)."""


async def _rewrite_keywords(
    client: Any,
    model: str,
    query: str,
    prev_keywords: str,
    all_tried: List[str],
    success: bool,
) -> str:
    template = _REWRITE_USER_EXPAND if success else _REWRITE_USER_REGEN
    prev_str = "; ".join(all_tried)
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _REWRITE_SYS},
                {"role": "user", "content": template.format(query=query, prev=prev_str)},
            ],
        )
        new_kw = resp.choices[0].message.content.strip().strip('"')
        return new_kw if new_kw else prev_keywords
    except Exception as exc:
        logger.debug("Keyword rewrite failed: %s", exc)
        return prev_keywords
