"""Pydantic request models — one per ``cf.*`` tool.

Unlike the previous ``_ds()`` registry factory, which forwarded raw payloads straight
into the Python function, every CiteFlow tool validates before dispatch.  That means a
bad payload surfaces as a ``ValidationError`` naming the offending field rather than a
``TypeError`` from deep inside the algorithm.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionOpenRequest(_Base):
    session_id: Optional[str] = Field(
        default=None, description="Reattach to this session; omit to create a new one."
    )
    query: Optional[str] = Field(default=None, description="Research question driving the run.")
    profile: Optional[str] = Field(
        default=None, description="Named parameter preset (see cf.profiles.list)."
    )
    overrides: Dict[str, Any] = Field(
        default_factory=dict,
        description='Dotted-path profile overrides, e.g. {"refs.top_k_co_cited": 10}.',
    )
    session_dir: Optional[str] = Field(
        default=None, description="Root directory for session artifacts."
    )


class SessionInfoRequest(_Base):
    session_id: str
    session_dir: Optional[str] = None


class SessionExportRequest(_Base):
    session_id: str
    path: Optional[str] = None
    session_dir: Optional[str] = None


class ProfilesListRequest(_Base):
    pass


class ProfilesShowRequest(_Base):
    name: str = Field(description="Profile name, e.g. 'acadeepr-run1'.")


class QueryAnalyzeRequest(_Base):
    session_id: str
    query: Optional[str] = Field(
        default=None, description="Research question; defaults to the session's query."
    )
    model: Optional[str] = Field(default=None, description="LLM model override.")
    from_yaml: Optional[str] = Field(
        default=None,
        description=(
            "Path to an original AcaDeepR config. Pins structured_keywords / "
            "search_queries / discriminative_terms instead of generating them, so a run "
            "can be compared against published results without first-turn variance."
        ),
    )
    session_dir: Optional[str] = None


class PapersSearchRequest(_Base):
    session_id: str
    queries: Optional[List[str]] = Field(
        default=None,
        description="Search strings; defaults to the session analysis' search_queries.",
    )
    engine: Optional[str] = Field(
        default=None,
        description=(
            "'s2' | 'openalex'. When set, only that engine is used (no fallback). "
            "When omitted, tries Semantic Scholar first with OpenAlex fallback."
        ),
    )
    limit: Optional[int] = Field(default=None, ge=1, le=1000)
    year: Optional[str] = Field(
        default=None, description="Year range, e.g. '2015-2023'."
    )
    resolve_openalex: bool = Field(
        default=True,
        description=(
            "Resolve results to OpenAlex work ids. Disabling this leaves papers that "
            "cannot take part in citation expansion."
        ),
    )
    top_k_preview: int = Field(
        default=10,
        ge=0,
        le=50,
        description="Number of top papers to include in the response for quick diagnosis.",
    )
    session_dir: Optional[str] = None


class PapersRepairRequest(_Base):
    session_id: str
    paper_ids: Optional[List[str]] = Field(
        default=None, description="Defaults to every store paper missing an OpenAlex id."
    )
    session_dir: Optional[str] = None


class CoCiteRequest(_Base):
    session_id: str
    paper_ids: Optional[List[str]] = Field(
        default=None, description="Defaults to every paper currently in the store."
    )
    min_count: Optional[int] = Field(
        default=None, ge=2, description="Minimum number of store papers co-citing a work."
    )
    hydrate: bool = Field(
        default=True,
        description="Fetch metadata for co-cited works not yet in the store and add them.",
    )
    max_hydrate: int = Field(default=300, ge=0, le=2000)
    session_dir: Optional[str] = None


class ExpandRefsGuidedRequest(_Base):
    session_id: str
    source_ids: Optional[List[str]] = Field(
        default=None,
        description=(
            "Explicit store paper IDs to expand references from. When set, bypasses "
            "the automatic search_rank-based selection. Use this when the agent has "
            "diagnosed which papers are better expansion sources."
        ),
    )
    top_k_co_cited: Optional[int] = Field(default=None, ge=1)
    max_citing_papers: Optional[int] = Field(default=None, ge=1)
    limit_per_work: Optional[int] = Field(default=None, ge=1, le=500)
    session_dir: Optional[str] = None


class SeedsSelectRefsRequest(_Base):
    session_id: str
    round: int = Field(default=0, ge=0)
    tag: Optional[str] = Field(default=None, description="Defaults to 'seed_r{round}_refs'.")
    session_dir: Optional[str] = None


class SeedsMarkRequest(_Base):
    session_id: str
    paper_ids: List[str]
    tag: Optional[str] = None
    session_dir: Optional[str] = None


class EvalScoreRequest(_Base):
    session_id: str
    query_id: str = Field(description="Benchmark query id, e.g. 'semantic_5'.")
    benchmark_path: Optional[str] = None
    ranked_paper_ids: Optional[List[str]] = Field(
        default=None,
        description=(
            "Ranked prediction list. Omit to score store coverage only, which is the "
            "meaningful metric before a final ranking exists."
        ),
    )
    session_dir: Optional[str] = None


class EvalCompareRequest(_Base):
    session_ids: List[str] = Field(min_length=1)
    query_ids: Optional[List[str]] = None
    benchmark_path: Optional[str] = None
    session_dir: Optional[str] = None


class AutoscoreRequest(_Base):
    session_id: str
    paper_ids: Optional[List[str]] = None
    max_papers: Optional[int] = Field(default=None, ge=1)
    force_sim: bool = False
    session_dir: Optional[str] = None


class ScoreRelevanceRequest(_Base):
    session_id: str
    paper_ids: Optional[List[str]] = None
    query_text: Optional[str] = Field(
        default=None, description="Defaults to the analysis' rerank_query."
    )
    force: bool = False
    session_dir: Optional[str] = None


class ScoreKeywordsRequest(_Base):
    session_id: str
    paper_ids: Optional[List[str]] = None
    terms: Optional[Dict[str, int]] = Field(
        default=None, description="Defaults to the analysis' discriminative_terms."
    )
    force: bool = False
    session_dir: Optional[str] = None


class PapersFilterRequest(_Base):
    session_id: str
    paper_ids: Optional[List[str]] = None
    profile_key: Optional[str] = Field(
        default=None,
        description="'filter_params_cite' (mid-loop) or 'filter_params' (final).",
    )
    max_citations: Optional[int] = None
    min_citations: Optional[int] = None
    year_range: Optional[List[int]] = Field(default=None, min_length=2, max_length=2)
    session_dir: Optional[str] = None


class StoreRankRequest(_Base):
    session_id: str
    paper_ids: Optional[List[str]] = None
    profile_key: Optional[str] = Field(
        default=None,
        description="'mid_sort_weights' | 'final_sort_weights_1' | 'final_sort_weights_2'.",
    )
    weights: Optional[Dict[str, Any]] = None
    boost_judged: bool = Field(
        default=True, description="Add +0.1 to papers the relevance judge marked."
    )
    top_k: int = Field(default=100, ge=1, le=5000)
    dedupe_by_title: bool = False
    session_dir: Optional[str] = None


class JudgeRelevanceRequest(_Base):
    session_id: str
    paper_ids: List[str] = Field(description="Ranked candidates; the top slices are judged.")
    batches: Optional[List[List[int]]] = Field(
        default=None, description="Slice bounds, default [[0,15],[15,30]]."
    )
    session_dir: Optional[str] = None


class DistributionsRequest(_Base):
    session_id: str
    paper_ids: List[str]
    session_dir: Optional[str] = None


class DecideParamsRequest(_Base):
    session_id: str
    total_seed_citations: int = Field(ge=0)
    citation_distribution: Dict[str, int]
    year_distribution: Dict[str, int]
    year_end: Optional[int] = None
    session_dir: Optional[str] = None


class SeedsSelectCitationsRequest(_Base):
    session_id: str
    round: int = Field(ge=1)
    from_round: Optional[int] = Field(
        default=None,
        description=(
            "Seed from the papers that round expanded. Defaults to round-1. The original "
            "seeds each round from the previous round's new papers, not the whole store."
        ),
    )
    paper_ids: Optional[List[str]] = None
    session_dir: Optional[str] = None


class FetchForwardRequest(_Base):
    session_id: str
    round: int = Field(ge=1)
    seed_ids: Optional[List[str]] = None
    year_start: Optional[int] = None
    year_end: Optional[int] = None
    min_citations: int = Field(default=0, ge=0)
    field: Optional[str] = Field(
        default=None, description="Restrict to an OpenAlex field, e.g. 'computer science'."
    )
    max_per_seed: Optional[int] = Field(default=None, ge=1)
    session_dir: Optional[str] = None


class RoundsListRequest(_Base):
    session_id: str
    session_dir: Optional[str] = None


class RoundsGetRequest(_Base):
    session_id: str
    round: Union[int, str] = Field(
        default="last", description="Round number, or 'last' for the most recent."
    )
    phase: Optional[str] = Field(
        default=None, description="Filter by phase: 'search' | 'refs' | 'citations'."
    )
    session_dir: Optional[str] = None


class StoreStatsRequest(_Base):
    session_id: str
    session_dir: Optional[str] = None
