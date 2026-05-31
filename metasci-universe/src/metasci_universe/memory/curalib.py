"""CuraLib — curated paper library for iterative academic search.

CuraLib is a structured memory layer that sits between raw paper data and the
LLM.  Instead of flooding the agent with hundreds of raw papers, it pre-computes
relevance metrics, maintains citation relationships, and tracks exploration state
so the LLM can focus purely on high-level decisions.

Ported from AcaDeepR/src/utils/paper_store.py (original: CiteFlow, SIGIR'26).
Adapted for metasci-universe: removed light-agent decorators and src.* imports.
Pure stdlib + dataclasses only — no LLM or heavy ML deps.

Usage::

    from metasci_universe.memory.curalib import PaperStore, PaperRecord

    store = PaperStore()
    store.add_papers([{"corpus_id": "12345", "title": "Attention is all you need",
                       "year": 2017, "citation_count": 50000}])
    ranked = store.rank_by_importance()
    store.save_to_json("papers.json")
    store2 = PaperStore.load_from_json("papers.json")
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set, Union

logger = logging.getLogger(__name__)


# ============================================================================
# Data model
# ============================================================================


@dataclass
class PaperRecord:
    """Complete record for a single paper."""

    # --- Unique identifiers ---
    corpus_id: str          # Primary key: Semantic Scholar Corpus ID (or openalex_id when S2 unavailable)
    paper_id: Optional[str] = None          # Semantic Scholar Paper ID
    openalex_id: Optional[str] = None       # OpenAlex Work ID
    doi: Optional[str] = None

    # --- Basic metadata ---
    title: str = ""
    abstract: str = ""
    year: Optional[int] = None
    authors: List[str] = field(default_factory=list)
    venue: str = ""
    url: str = ""

    # --- Ranking signals ---
    citation_count: int = 0
    reference_count: int = 0
    influential_citation_count: int = 0
    search_rank: Optional[int] = None      # Position in keyword-search results (fallback relevance)

    # --- Scores (multi-source) ---
    llm_score: Optional[float] = None
    llm_rationale: str = ""
    embedding_sim: Optional[float] = None  # Primary relevance score
    embedding_sim1: Optional[float] = None
    embedding_sim2: Optional[float] = None
    importance_score: Optional[float] = None
    keyword_match_score: Optional[float] = None

    # In-domain citation network scores
    in_domain_citation_count: Optional[int] = None
    in_domain_citation_score: Optional[float] = None

    # Per-dimension scores (for debugging/analysis)
    _relevance_score: Optional[float] = None
    _recency_score: Optional[float] = None
    _centrality_score: Optional[float] = None
    _venue_score: Optional[float] = None

    # --- Discovery history ---
    discovery_history: List[Dict[str, Any]] = field(default_factory=list)
    # Each record: {"round": int, "source": str, "keywords": str|None,
    #               "parent_ids": list|None, "search_rank": int|None}

    # --- Citation relationships ---
    parent_paper_ids: Set[str] = field(default_factory=set)
    citations: List[Dict[str, Any]] = field(default_factory=list)
    references: List[Dict[str, Any]] = field(default_factory=list)
    reference_ids: List[str] = field(default_factory=list)
    citation_ids: List[str] = field(default_factory=list)
    reference_dois: List[str] = field(default_factory=list)
    citation_dois: List[str] = field(default_factory=list)

    # --- Status ---
    is_evaluated: bool = False
    is_seed: bool = False
    tags: List[str] = field(default_factory=list)

    # --- Convenience properties (derived from discovery_history) ---

    @property
    def source(self) -> str:
        """First-discovery source."""
        if self.discovery_history:
            return self.discovery_history[0].get("source", "search")
        return "search"

    @property
    def discovered_round(self) -> int:
        if self.discovery_history:
            return self.discovery_history[0].get("round", 0)
        return 0

    @property
    def source_keywords(self) -> List[str]:
        keywords: List[str] = []
        for record in self.discovery_history:
            if record.get("source") == "search" and record.get("keywords"):
                kw = record["keywords"]
                if kw not in keywords:
                    keywords.append(kw)
        return keywords

    def to_dict(self) -> Dict[str, Any]:
        return {
            "corpus_id": self.corpus_id,
            "paper_id": self.paper_id,
            "openalex_id": self.openalex_id,
            "doi": self.doi,
            "title": self.title,
            "abstract": self.abstract,
            "year": self.year,
            "authors": self.authors,
            "venue": self.venue,
            "url": self.url,
            "citation_count": self.citation_count,
            "reference_count": self.reference_count,
            "influential_citation_count": self.influential_citation_count,
            "search_rank": self.search_rank,
            "llm_score": self.llm_score,
            "llm_rationale": self.llm_rationale,
            "embedding_sim": self.embedding_sim,
            "embedding_sim1": self.embedding_sim1,
            "embedding_sim2": self.embedding_sim2,
            "importance_score": self.importance_score,
            "keyword_match_score": self.keyword_match_score,
            "in_domain_citation_count": self.in_domain_citation_count,
            "in_domain_citation_score": self.in_domain_citation_score,
            "_relevance_score": self._relevance_score,
            "_recency_score": self._recency_score,
            "_centrality_score": self._centrality_score,
            "_venue_score": self._venue_score,
            "source": self.source,
            "source_keywords": self.source_keywords,
            "is_evaluated": self.is_evaluated,
            "is_seed": self.is_seed,
            "tags": self.tags,
            "parent_paper_ids": list(self.parent_paper_ids),
            "discovery_history": self.discovery_history,
            # Alias fields for OpenAlex / S2 API compatibility
            "publication_year": self.year,
            "cited_by_count": self.citation_count,
            "references": self.references,
            "citations": self.citations,
            "reference_ids": self.reference_ids,
            "citation_ids": self.citation_ids,
            "reference_dois": self.reference_dois,
            "citation_dois": self.citation_dois,
        }


# ============================================================================
# PaperStore
# ============================================================================


class PaperStore:
    """Curated paper store with automatic deduplication, multi-source scoring,
    source tracking, flexible ranking, and JSON persistence.

    This is CuraLib — the central context manager described in the CiteFlow
    paper (SIGIR'26).  All metric computation happens here; the LLM only
    receives pre-sorted, pre-filtered candidate lists.
    """

    def __init__(self) -> None:
        self._papers: Dict[str, PaperRecord] = {}
        self._keyword_index: Dict[str, Set[str]] = {}
        self._api_index: Dict[str, Set[str]] = {}
        self._openalex_index: Dict[str, str] = {}
        self._current_round: int = 0

    # -------------------------------------------------------------------------
    # Add papers
    # -------------------------------------------------------------------------

    def add_papers(
        self,
        papers: List[Union[Any, Dict[str, Any]]],
        source: Literal["search", "citation", "manual"] = "search",
        keywords: Optional[str] = None,
        parent_ids: Optional[List[str]] = None,
        api_name: str = "openalex",
    ) -> List[PaperRecord]:
        """Add papers with automatic deduplication.

        Deduplication is corpus_id-first, with openalex_id as a secondary key.
        Returns only the *newly added* records (existing ones are updated in place).
        """
        new_records: List[PaperRecord] = []

        for paper in papers:
            openalex_id = self._extract_openalex_id(paper)
            corpus_id = self._extract_corpus_id(paper)

            if not openalex_id and not corpus_id:
                continue

            search_rank: Optional[int] = None
            if hasattr(paper, "search_rank"):
                search_rank = paper.search_rank
            elif isinstance(paper, dict):
                search_rank = paper.get("search_rank")

            existing_corpus_id: Optional[str] = None

            if openalex_id and openalex_id in self._openalex_index:
                existing_corpus_id = self._openalex_index[openalex_id]

            if not existing_corpus_id and corpus_id and corpus_id in self._papers:
                existing_corpus_id = corpus_id

            discovery_record = {
                "round": self._current_round,
                "source": source,
                "keywords": keywords if source == "search" else None,
                "parent_ids": parent_ids if source == "citation" else None,
                "search_rank": search_rank,
            }

            if existing_corpus_id:
                existing = self._papers[existing_corpus_id]
                if parent_ids:
                    existing.parent_paper_ids.update(parent_ids)
                if openalex_id and not existing.openalex_id:
                    existing.openalex_id = openalex_id
                    self._openalex_index[openalex_id] = existing_corpus_id
                existing.discovery_history.append(discovery_record)
                if keywords:
                    self._keyword_index.setdefault(keywords, set()).add(existing_corpus_id)
            else:
                if not corpus_id and openalex_id:
                    corpus_id = openalex_id

                record = self._paper_to_record(paper, parent_ids)
                record.discovery_history = [discovery_record]

                self._papers[corpus_id] = record
                new_records.append(record)

                if record.openalex_id:
                    self._openalex_index[str(record.openalex_id)] = corpus_id
                if keywords:
                    self._keyword_index.setdefault(keywords, set()).add(corpus_id)
                self._api_index.setdefault(api_name, set()).add(corpus_id)

        logger.info("Added %d new papers (total: %d)", len(new_records), len(self._papers))
        return new_records

    # -------------------------------------------------------------------------
    # Score management
    # -------------------------------------------------------------------------

    def update_scores(
        self,
        scores: List[Dict[str, Any]],
        score_type: Literal["llm", "embedding", "importance"],
    ) -> int:
        """Batch-update scores. Returns count of successfully updated papers."""
        updated = 0
        for item in scores:
            paper_id = item.get("openalex_id") or item.get("corpus_id") or item.get("paper_id", "")
            record = self._find_paper_by_id(paper_id)
            if not record:
                continue
            score = float(item.get("score", 0))
            if score_type == "llm":
                record.llm_score = score
                record.llm_rationale = item.get("rationale", "")
                record.is_evaluated = True
            elif score_type == "embedding":
                record.embedding_sim = score
            elif score_type == "importance":
                record.importance_score = score
            updated += 1
        return updated

    def batch_update_scores(self, scores: Dict[str, float], field: str = "keyword_match_score") -> int:
        """Update a single score field for multiple papers at once."""
        valid_fields = {
            "keyword_match_score", "embedding_sim", "embedding_sim1", "embedding_sim2",
            "llm_score", "importance_score", "venue_score", "in_domain_citation_score",
        }
        if field not in valid_fields:
            logger.warning("Unsupported field: %s", field)
            return 0
        updated = 0
        for paper_id, score in scores.items():
            record = self._find_paper_by_id(paper_id)
            if record:
                setattr(record, field, score)
                updated += 1
        return updated

    # -------------------------------------------------------------------------
    # Retrieval
    # -------------------------------------------------------------------------

    def get_paper(self, paper_id: str) -> Optional[Dict[str, Any]]:
        record = self._find_paper_by_id(paper_id)
        return record.to_dict() if record else None

    def get_papers_by_ids(self, paper_ids: List[str]) -> List[Dict[str, Any]]:
        return [p for p in (self.get_paper(pid) for pid in paper_ids) if p]

    def get_record(self, paper_id: str) -> Optional[PaperRecord]:
        return self._find_paper_by_id(paper_id)

    def get_records_by_ids(self, paper_ids: Optional[List[str]] = None) -> List[PaperRecord]:
        if paper_ids is None:
            return list(self._papers.values())
        return [r for r in (self._find_paper_by_id(pid) for pid in paper_ids) if r]

    def get_all_papers(self, as_dict: bool = False) -> Union[List[PaperRecord], List[Dict[str, Any]]]:
        papers = list(self._papers.values())
        return [p.to_dict() for p in papers] if as_dict else papers

    def get_top_k(
        self,
        k: int,
        score_type: Literal["llm", "embedding", "importance"] = "llm",
        filter_evaluated: bool = True,
    ) -> List[Dict[str, Any]]:
        papers = list(self._papers.values())
        if filter_evaluated and score_type == "llm":
            papers = [p for p in papers if p.is_evaluated]

        def _key(p: PaperRecord) -> float:
            if score_type == "llm":
                return p.llm_score or 0.0
            if score_type == "embedding":
                return p.embedding_sim or 0.0
            return p.importance_score or 0.0

        papers.sort(key=_key, reverse=True)
        return [p.to_dict() for p in papers[:k]]

    def get_all_scored(self, score_type: str = "llm") -> List[Dict[str, Any]]:
        if score_type == "llm":
            scored = sorted(
                [p for p in self._papers.values() if p.is_evaluated],
                key=lambda x: x.llm_score or 0, reverse=True,
            )
        elif score_type == "embedding":
            scored = sorted(
                [p for p in self._papers.values() if p.embedding_sim is not None],
                key=lambda x: x.embedding_sim or 0, reverse=True,
            )
        else:
            scored = sorted(
                [p for p in self._papers.values() if p.importance_score is not None],
                key=lambda x: x.importance_score or 0, reverse=True,
            )
        return [p.to_dict() for p in scored]

    # -------------------------------------------------------------------------
    # Ranking
    # -------------------------------------------------------------------------

    @staticmethod
    def _sigmoid(x: float, center: float = 0.0, steepness: float = 1.0) -> float:
        try:
            return 1.0 / (1.0 + math.exp(-steepness * (x - center)))
        except OverflowError:
            return 0.0 if x < center else 1.0

    @staticmethod
    def _recency_score(year: int, current_year: Optional[int] = None,
                       center_shift: float = 7.0, steepness: float = 0.7) -> float:
        if current_year is None:
            current_year = datetime.now().year
        if not year or year <= 0:
            return 0.0
        if year >= current_year:
            return 1.0
        return PaperStore._sigmoid(year, center=current_year - center_shift, steepness=steepness)

    @staticmethod
    def _centrality_score(citation_count: int, center: int = 50, steepness: float = 1.8) -> float:
        if not citation_count or citation_count <= 0:
            return 0.0
        return PaperStore._sigmoid(
            math.log(citation_count + 1),
            center=math.log(center + 1),
            steepness=steepness,
        )

    def rank_by_importance(
        self,
        papers: Optional[List[Union[PaperRecord, Dict[str, Any]]]] = None,
        weights: Optional[Dict[str, float]] = None,
        relevance_priority: Optional[List[Union[str, float]]] = None,
    ) -> List[PaperRecord]:
        """Rank papers using a weighted combination of relevance, centrality, recency, etc.

        Args:
            papers: Papers to rank (PaperRecord or dict). None → all papers in store.
            weights: Score dimension weights.  Supported keys:
                relevance / embedding_sim, centrality / citation_count, recency,
                venue_score, llm_score, keyword_match_score, in_domain_citation_score.
                Set relevance_mode="multiplicative" for the CiteFlow formula
                ``(1 + α·s_kw) × (1 + α·s_emb) − 1``.
            relevance_priority: Ordered list of relevance sources with optional float fallback,
                e.g. ``['embedding_sim', 'search_rank', 0.05]``.
        """
        if weights is None:
            weights = {"relevance": 0.4, "centrality": 0.3, "recency": 0.3}
        if relevance_priority is None:
            relevance_priority = ["embedding_sim", 0.02]

        if papers is None:
            paper_records = list(self._papers.values())
        else:
            paper_records = []
            for p in papers:
                if isinstance(p, PaperRecord):
                    paper_records.append(p)
                elif isinstance(p, dict):
                    pid = p.get("openalex_id") or p.get("corpus_id") or p.get("paper_id", "")
                    rec = self._find_paper_by_id(pid)
                    if rec:
                        paper_records.append(rec)

        current_year = datetime.now().year
        relevance_mode = weights.get("relevance_mode", "additive")
        kw_scale = weights.get("keyword_scale", 0.7)
        emb_scale = weights.get("embedding_scale", 1.0)
        HIGH_REL_THRESHOLD = 0.93
        HIGH_REL_BOOST = 0.3

        for record in paper_records:
            score = 0.0

            # Resolve relevance score from priority list
            embedding_sim: float = 0.02
            for item in relevance_priority:
                if isinstance(item, (int, float)):
                    embedding_sim = float(item)
                    break
                if item == "embedding_sim" and record.embedding_sim is not None:
                    embedding_sim = record.embedding_sim
                    break
                elif item == "embedding_sim1" and record.embedding_sim1 is not None:
                    embedding_sim = record.embedding_sim1
                    break
                elif item == "embedding_sim2" and record.embedding_sim2 is not None:
                    embedding_sim = record.embedding_sim2
                    break
                elif item == "search_rank" and record.search_rank is not None:
                    embedding_sim = 1.0 / max(record.search_rank, 1)
                    break

            keyword_score = record.keyword_match_score or 0.0
            boost_emb = embedding_sim >= HIGH_REL_THRESHOLD
            boost_kw = keyword_score >= HIGH_REL_THRESHOLD

            if boost_emb and "high_embedding_sim" not in record.tags:
                record.tags.append("high_embedding_sim")
            if boost_kw and "high_keyword_match" not in record.tags:
                record.tags.append("high_keyword_match")

            if relevance_mode == "multiplicative":
                # CiteFlow formula: (1 + α·s_kw) × (1 + α·s_emb) − 1
                emb_s = emb_scale + (HIGH_REL_BOOST if boost_emb else 0)
                kw_s = kw_scale + (HIGH_REL_BOOST if boost_kw else 0)
                combined = (1 + kw_s * keyword_score) * (1 + emb_s * embedding_sim) - 1
                record._relevance_score = embedding_sim
                score += weights.get("combined_relevance", 0.5) * combined
            else:
                rel_w = weights.get("relevance") or weights.get("embedding_sim")
                if rel_w:
                    record._relevance_score = embedding_sim
                    score += (rel_w + (HIGH_REL_BOOST if boost_emb else 0)) * embedding_sim
                if "keyword_match_score" in weights and record.keyword_match_score is not None:
                    kw_w = weights["keyword_match_score"]
                    score += (kw_w + (HIGH_REL_BOOST if boost_kw else 0)) * record.keyword_match_score

            cen_w = weights.get("centrality") or weights.get("citation_count")
            if cen_w:
                cen = self._centrality_score(record.citation_count)
                record._centrality_score = cen
                score += cen_w * cen

            if "recency" in weights:
                rec = self._recency_score(record.year, current_year) if record.year else 0.0
                record._recency_score = rec
                score += weights["recency"] * rec

            if "venue_score" in weights:
                vs = 0.5 if record.venue else 0.0
                record._venue_score = vs
                score += weights["venue_score"] * vs

            if "llm_score" in weights and record.llm_score is not None:
                score += weights["llm_score"] * record.llm_score

            if "in_domain_citation_score" in weights and record.in_domain_citation_score is not None:
                score += weights["in_domain_citation_score"] * record.in_domain_citation_score

            record.importance_score = score

        paper_records.sort(key=lambda x: x.importance_score or 0, reverse=True)
        return paper_records

    def get_fine_grained_ranking(
        self,
        llm_score_threshold: float = 0.3,
        embedding_threshold: float = 0.2,
    ) -> List[Dict[str, Any]]:
        """Three-tier ranking: LLM-scored → embedding-scored → others."""
        all_papers = list(self._papers.values())
        tier1 = sorted(
            [p for p in all_papers if p.llm_score is not None and p.llm_score >= llm_score_threshold],
            key=lambda x: x.llm_score or 0, reverse=True,
        )
        t1_ids = {p.corpus_id for p in tier1}
        tier2 = sorted(
            [p for p in all_papers
             if p.corpus_id not in t1_ids
             and p.embedding_sim is not None
             and p.embedding_sim >= embedding_threshold],
            key=lambda x: x.embedding_sim or 0, reverse=True,
        )
        t2_ids = {p.corpus_id for p in tier2}
        tier3 = sorted(
            [p for p in all_papers if p.corpus_id not in t1_ids and p.corpus_id not in t2_ids],
            key=lambda x: (
                1 if x._relevance_score is not None else 0,
                x._relevance_score or 0,
                x._centrality_score or 0,
                x._recency_score or 0,
            ),
            reverse=True,
        )
        return [p.to_dict() for p in tier1 + tier2 + tier3]

    # -------------------------------------------------------------------------
    # Citation graph helpers
    # -------------------------------------------------------------------------

    def update_citations_and_references(
        self,
        paper_id: str,
        citations: Optional[List[Dict[str, Any]]] = None,
        references: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        record = self._find_paper_by_id(paper_id)
        if not record:
            return
        if citations is not None:
            record.citations = citations
        if references is not None:
            record.references = references

    def get_citations(self, paper_id: str) -> List[Dict[str, Any]]:
        r = self._find_paper_by_id(paper_id)
        return r.citations if r else []

    def get_references(self, paper_id: str) -> List[Dict[str, Any]]:
        r = self._find_paper_by_id(paper_id)
        return r.references if r else []

    def get_reference_ids(self, paper_id: str) -> List[str]:
        return [str(r.get("corpusId", "")) for r in self.get_references(paper_id) if r.get("corpusId")]

    def get_citation_ids(self, paper_id: str) -> List[str]:
        return [str(c.get("corpusId", "")) for c in self.get_citations(paper_id) if c.get("corpusId")]

    # -------------------------------------------------------------------------
    # Tag management
    # -------------------------------------------------------------------------

    def mark_as_seeds(self, paper_ids: Union[str, List[str]], tag: Optional[str] = None) -> int:
        if isinstance(paper_ids, str):
            paper_ids = [paper_ids]
        count = 0
        for pid in paper_ids:
            r = self._find_paper_by_id(pid)
            if r:
                r.is_seed = True
                if tag and tag not in r.tags:
                    r.tags.append(tag)
                count += 1
        return count

    def add_tags(self, paper_ids: Union[str, List[str]], tags: Union[str, List[str]]) -> int:
        if isinstance(paper_ids, str):
            paper_ids = [paper_ids]
        if isinstance(tags, str):
            tags = [tags]
        count = 0
        for pid in paper_ids:
            r = self._find_paper_by_id(pid)
            if r:
                for t in tags:
                    if t not in r.tags:
                        r.tags.append(t)
                count += 1
        return count

    def get_papers_by_tag(self, tags: Union[str, List[str]], match_all: bool = False) -> List[PaperRecord]:
        if isinstance(tags, str):
            tags = [tags]
        result = []
        for p in self._papers.values():
            if match_all and all(t in p.tags for t in tags):
                result.append(p)
            elif not match_all and any(t in p.tags for t in tags):
                result.append(p)
        return result

    # -------------------------------------------------------------------------
    # Statistics
    # -------------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        papers = list(self._papers.values())
        return {
            "total_papers": len(papers),
            "evaluated_count": sum(1 for p in papers if p.is_evaluated),
            "search_papers": sum(1 for p in papers if p.source == "search"),
            "citation_papers": sum(1 for p in papers if p.source == "citation"),
            "keywords_used": list(self._keyword_index.keys()),
            "current_round": self._current_round,
            "avg_citation_count": sum(p.citation_count for p in papers) / len(papers) if papers else 0,
        }

    def advance_round(self) -> None:
        self._current_round += 1

    def is_evaluated(self, paper_id: str) -> bool:
        r = self._find_paper_by_id(paper_id)
        return r.is_evaluated if r else False

    def get_unevaluated_ids(self, paper_ids: List[str]) -> List[str]:
        return [
            self._find_paper_by_id(pid).corpus_id
            for pid in paper_ids
            if (r := self._find_paper_by_id(pid)) and not r.is_evaluated
        ]

    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------

    def save_to_json(self, path: str) -> None:
        data = {
            "papers": {cid: rec.to_dict() for cid, rec in self._papers.items()},
            "current_round": self._current_round,
            "keyword_index": {k: list(v) for k, v in self._keyword_index.items()},
            "saved_at": datetime.now().isoformat(),
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        logger.info("Saved %d papers to %s", len(self._papers), path)

    @classmethod
    def load_from_json(cls, path: str) -> "PaperStore":
        if not Path(path).exists():
            raise FileNotFoundError(f"PaperStore file not found: {path}")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        store = cls()
        store._current_round = data.get("current_round", 0)
        store._keyword_index = {k: set(v) for k, v in data.get("keyword_index", {}).items()}
        store._api_index = {k: set(v) for k, v in data.get("api_index", {}).items()}

        def _norm_cit_list(items: List[Any]) -> List[Dict[str, Any]]:
            if not items:
                return []
            if isinstance(items[0], str):
                return [{"corpusId": str(i), "paperId": "", "title": "", "year": None,
                         "citationCount": 0, "venue": "", "fieldsOfStudy": []} for i in items]
            return items

        for corpus_id, d in data.get("papers", {}).items():
            parent_ids = set(d.get("parent_paper_ids", []))
            discovery_history = d.get("discovery_history", [])
            if not discovery_history:
                # Back-compat: reconstruct from legacy flat fields
                src = d.get("source", "search")
                rnd = d.get("discovered_round", 0)
                kws = d.get("source_keywords", [])
                if src == "search" and kws:
                    for kw in kws:
                        discovery_history.append({"round": rnd, "source": "search",
                                                   "keywords": kw, "parent_ids": None,
                                                   "search_rank": d.get("search_rank")})
                else:
                    discovery_history.append({"round": rnd, "source": src,
                                               "keywords": None,
                                               "parent_ids": list(parent_ids) if src == "citation" else None,
                                               "search_rank": d.get("search_rank")})

            record = PaperRecord(
                corpus_id=corpus_id,
                paper_id=d.get("paper_id"),
                openalex_id=d.get("openalex_id"),
                doi=d.get("doi"),
                title=d.get("title", ""),
                abstract=d.get("abstract", ""),
                year=d.get("year"),
                authors=d.get("authors", []),
                venue=d.get("venue", ""),
                url=d.get("url", ""),
                citation_count=d.get("citation_count", 0),
                reference_count=d.get("reference_count", 0),
                influential_citation_count=d.get("influential_citation_count", 0),
                search_rank=d.get("search_rank"),
                llm_score=d.get("llm_score"),
                llm_rationale=d.get("llm_rationale", ""),
                embedding_sim=d.get("embedding_sim"),
                embedding_sim1=d.get("embedding_sim1"),
                embedding_sim2=d.get("embedding_sim2"),
                importance_score=d.get("importance_score"),
                keyword_match_score=d.get("keyword_match_score"),
                in_domain_citation_count=d.get("in_domain_citation_count"),
                in_domain_citation_score=d.get("in_domain_citation_score"),
                _relevance_score=d.get("_relevance_score"),
                _recency_score=d.get("_recency_score"),
                _centrality_score=d.get("_centrality_score"),
                _venue_score=d.get("_venue_score"),
                parent_paper_ids=parent_ids,
                discovery_history=discovery_history,
                citations=_norm_cit_list(d.get("citations", [])),
                references=_norm_cit_list(d.get("references", [])),
                reference_ids=d.get("reference_ids", []),
                citation_ids=d.get("citation_ids", []),
                reference_dois=d.get("reference_dois", []),
                citation_dois=d.get("citation_dois", []),
                is_evaluated=d.get("is_evaluated", False),
                is_seed=d.get("is_seed", False),
                tags=d.get("tags", []),
            )
            store._papers[corpus_id] = record
            if record.openalex_id:
                store._openalex_index[str(record.openalex_id)] = corpus_id

        logger.info("Loaded %d papers from %s", len(store._papers), path)
        return store

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _find_paper_by_id(self, paper_id: str) -> Optional[PaperRecord]:
        if paper_id in self._papers:
            return self._papers[paper_id]
        # Fallback: linear scan on openalex_id
        if paper_id in self._openalex_index:
            cid = self._openalex_index[paper_id]
            return self._papers.get(cid)
        return None

    def _extract_corpus_id(self, paper: Any) -> Optional[str]:
        if hasattr(paper, "external_info"):
            return str(paper.external_info.get("corpusId", "")).strip() or None
        if isinstance(paper, dict):
            v = paper.get("corpusId") or paper.get("corpus_id", "")
            return str(v).strip() or None
        return None

    def _extract_openalex_id(self, paper: Any) -> Optional[str]:
        if hasattr(paper, "external_info"):
            v = paper.external_info.get("openalex_id", "")
            return str(v).strip() or None
        if isinstance(paper, dict):
            v = paper.get("openalex_id", "")
            return str(v).strip() or None
        return None

    def _extract_citation_info(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "corpusId": str(item.get("corpusId", "")) or None,
            "paperId": item.get("paperId", ""),
            "title": item.get("title", ""),
            "year": item.get("year"),
            "citationCount": item.get("citationCount", 0),
            "venue": item.get("venue", ""),
            "fieldsOfStudy": item.get("fieldsOfStudy", []),
        }

    def _paper_to_record(self, paper: Any, parent_ids: Optional[List[str]]) -> PaperRecord:
        """Convert a Paper object or dict to PaperRecord."""
        if hasattr(paper, "title"):
            # Paper dataclass (from semantic_scholar_tools)
            corpus_id = self._extract_corpus_id(paper) or ""
            ei = paper.external_info if hasattr(paper, "external_info") and paper.external_info else {}
            refs_raw = ei.get("references", [])
            cits_raw = ei.get("citations", [])
            references = [self._extract_citation_info(r) for r in refs_raw if r.get("corpusId") or r.get("paperId")]
            citations = [self._extract_citation_info(c) for c in cits_raw if c.get("corpusId") or c.get("paperId")]
            reference_ids = [str(r["corpusId"] or r["paperId"]) for r in references if r.get("corpusId") or r.get("paperId")]
            citation_ids = [str(c["corpusId"] or c["paperId"]) for c in citations if c.get("corpusId") or c.get("paperId")]
            if not reference_ids and ei.get("referenced_works"):
                reference_ids = ei.get("referenced_works", [])
            return PaperRecord(
                corpus_id=corpus_id,
                paper_id=getattr(paper, "paper_id", None),
                openalex_id=ei.get("openalex_id"),
                doi=getattr(paper, "doi", None) or ei.get("DOI"),
                title=paper.title or "",
                abstract=paper.abstract or "",
                year=paper.year,
                authors=paper.authors or [],
                venue=paper.venue or "",
                url=paper.url or "",
                citation_count=paper.citation_count or 0,
                reference_count=getattr(paper, "reference_count", 0) or ei.get("referenceCount", 0),
                influential_citation_count=ei.get("influentialCitationCount", 0),
                search_rank=getattr(paper, "search_rank", None),
                references=references,
                citations=citations,
                reference_ids=reference_ids,
                citation_ids=citation_ids,
                parent_paper_ids=set(parent_ids) if parent_ids else set(),
                tags=getattr(paper, "tags", []),
            )
        else:
            # dict (from OpenAlex or any provider)
            corpus_id = self._extract_corpus_id(paper) or ""
            ei = paper.get("external_info", {}) or {}
            refs_raw = ei.get("references", [])
            cits_raw = ei.get("citations", [])
            references = [self._extract_citation_info(r) for r in refs_raw if r.get("corpusId") or r.get("paperId")]
            citations = [self._extract_citation_info(c) for c in cits_raw if c.get("corpusId") or c.get("paperId")]
            reference_ids = paper.get("reference_ids") or ei.get("referenced_works") or [
                str(r["corpusId"] or r["paperId"]) for r in references if r.get("corpusId") or r.get("paperId")
            ]
            citation_ids = [
                str(c["corpusId"] or c["paperId"]) for c in citations if c.get("corpusId") or c.get("paperId")
            ]
            return PaperRecord(
                corpus_id=corpus_id,
                paper_id=paper.get("paperId") or paper.get("paper_id"),
                openalex_id=paper.get("openalex_id") or ei.get("openalex_id"),
                doi=paper.get("doi") or ei.get("DOI"),
                title=paper.get("title", ""),
                abstract=paper.get("abstract", ""),
                year=paper.get("year") or paper.get("publication_year"),
                authors=paper.get("authors", []),
                venue=paper.get("venue", ""),
                url=paper.get("url", ""),
                citation_count=paper.get("citation_count") or paper.get("citationCount") or paper.get("cited_by_count") or 0,
                reference_count=paper.get("reference_count") or paper.get("referenceCount") or ei.get("referenceCount") or 0,
                influential_citation_count=ei.get("influentialCitationCount", 0),
                search_rank=paper.get("search_rank"),
                references=references,
                citations=citations,
                reference_ids=reference_ids,
                citation_ids=citation_ids,
                reference_dois=paper.get("reference_dois", []),
                citation_dois=paper.get("citation_dois", []),
                parent_paper_ids=set(parent_ids) if parent_ids else set(),
                tags=paper.get("tags", []),
            )
