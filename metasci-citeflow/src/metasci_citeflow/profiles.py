"""Named parameter presets for CiteFlow runs.

The original algorithm was driven by large YAML config files (one per benchmark
query).  Every query's config shared the same *structural* parameters and differed
only in the query-specific fields (query text, structured_keywords, search_queries,
discriminative_terms) which are now produced at runtime by ``cf.query.analyze``.

What remains — weights, thresholds, budgets — is captured here as named profiles so
a run can be reproduced exactly (`profile="acadeepr-run1"`) while still allowing
per-parameter overrides for experimentation::

    resolve("acadeepr-run1", **{"refs.top_k_co_cited": 10})

Provenance for each preset is recorded in its ``description``.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Mapping, Tuple, Union

# ``mid_sort_weights`` was absent from the run_my_2/run_my_3 configs, which means the
# mid-loop ranking ran with no weights at all.  That is a real (accidental) behaviour of
# the evaluated runs, so it is preserved — but named, rather than shipped as a silent {}.
PASSTHROUGH = "passthrough"
Weights = Union[Dict[str, Any], Literal["passthrough"]]


@dataclass(frozen=True)
class InitSearch:
    """Phase 1 keyword search."""

    year: Tuple[int, int] = (2015, 2023)
    limit: int = 50
    queries_used: int = 2  # pipeline uses search_queries[:2]


@dataclass(frozen=True)
class CoSeedSelection:
    """Budget governing seed selection off the co-citation buckets."""

    min_papers: int = 3  # strategy-1 gate: need this many strong co-cited papers
    max_citation_exclude: int = 5000  # drop broader-than-topic papers before ranking
    min_total_citations: int = 500  # seed citation budget
    min_seeds: int = 2


@dataclass(frozen=True)
class RefsParams:
    """Phase 2 backward (references) expansion, guided by co-citation."""

    max_per_seed: int = 100  # limit_per_work for fetch_refs
    top_k_co_cited: int = 10
    max_citing_papers: int = 15
    co_seed_selection: CoSeedSelection = field(default_factory=CoSeedSelection)


@dataclass(frozen=True)
class SeedLLM:
    """LLM seed selection (SeedSelector)."""

    max_select: int = 6  # prompt instructs "at most 6"
    batch_size: int = 10  # SeedSelector.select truncates to 10 papers per call
    hard_max_cited_by: int = 8000  # pre-filter inside select_seeds_with_llm
    enforce_limits: bool = True  # stop batching once the citation budget is met
    temperature: float = 0.5
    max_retries: int = 5
    initial_wait: float = 5.0
    max_wait: float = 90.0


@dataclass(frozen=True)
class LoopParams:
    """Phase 3 forward-expansion loop.

    ``rounds`` is the faithful default; recipes that let the agent decide when to stop
    ignore it and drive the loop from the signals on ``cf.store.stats``.
    """

    rounds: int = 3
    top_papers: int = 100  # ranked[:100] kept as the distribution population
    judge_batches: Tuple[Tuple[int, int], ...] = ((0, 15), (15, 30))
    seed_candidate_pool: int = 30  # ranked[:30] handed to the seed LLM
    relevance_max_select: int = 4  # RelevanceSelector prompt cap


@dataclass(frozen=True)
class CoCitation:
    min_count: int = 2
    year_floor: int = 2011
    strong: Tuple[int, int] = (3, 10)  # "strong" bucket bounds, inclusive


@dataclass(frozen=True)
class FilterParams:
    max_citations: int | None = None
    year_range: Tuple[int, int] | None = None


@dataclass(frozen=True)
class Models:
    """Models per decision point.

    The batch configs named ``gemini-flash-latest``, which was that gateway's alias;
    ``gemini-2.5-flash`` is the same model and matches AcaDeepR's own in-code defaults.
    Override per profile if your gateway exposes different ids.
    """

    analyzer: str = "gemini-2.5-flash"
    seed: str = "gemini-2.5-flash"
    judge: str = "gemini-2.5-flash"
    decider: str = "gemini-2.5-flash"


@dataclass(frozen=True)
class CiteFlowProfile:
    name: str
    description: str

    init_search: InitSearch = field(default_factory=InitSearch)
    year_upper: int = 2023
    year_end: int = 2023

    refs: RefsParams = field(default_factory=RefsParams)
    seed_llm: SeedLLM = field(default_factory=SeedLLM)
    loop: LoopParams = field(default_factory=LoopParams)
    cocitation: CoCitation = field(default_factory=CoCitation)

    filter_params_cite: FilterParams = field(default_factory=FilterParams)
    filter_params: FilterParams = field(default_factory=FilterParams)

    mid_sort_weights: Weights = field(default_factory=dict)
    final_sort_weights_1: Dict[str, Any] = field(default_factory=dict)
    final_sort_weights_2: Dict[str, Any] = field(default_factory=dict)

    final_max_papers: int = 1200
    models: Models = field(default_factory=Models)

    # Whether Phase 2 (co-citation guided references expansion) runs at all.
    # run_my_3 set start_from_phase1 + from_phase2, which skipped it entirely.
    skip_refs_expansion: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


_MULTIPLICATIVE_FINAL_1 = {
    "relevance_mode": "multiplicative",
    "keyword_scale": 0.8,
    "embedding_scale": 1.0,
    "combined_relevance": 0.5,
    "citation_count": 0.1,
    "recency": 0.2,
}
_MULTIPLICATIVE_FINAL_2 = {
    "relevance_mode": "multiplicative",
    "keyword_scale": 0.5,
    "embedding_scale": 1.2,
    "combined_relevance": 0.5,
    "citation_count": 0.1,
    "recency": 0.2,
}


def _build_profiles() -> Dict[str, CiteFlowProfile]:
    acadeepr_run1 = CiteFlowProfile(
        name="acadeepr-run1",
        description=(
            "Full pipeline as run for the 47-query batch evaluation "
            "(AcaDeepR inputConfig/run_my_1/*.yaml). Phase 1-4 including "
            "co-citation guided references expansion."
        ),
        init_search=InitSearch(year=(2015, 2023), limit=50, queries_used=2),
        refs=RefsParams(
            max_per_seed=100,
            top_k_co_cited=20,
            max_citing_papers=12,
            co_seed_selection=CoSeedSelection(
                min_papers=3,
                max_citation_exclude=5000,
                min_total_citations=600,
                min_seeds=2,
            ),
        ),
        seed_llm=SeedLLM(enforce_limits=True),
        filter_params_cite=FilterParams(max_citations=7000, year_range=(2016, 2023)),
        filter_params=FilterParams(max_citations=8000, year_range=(2016, 2023)),
        mid_sort_weights={
            "keyword_match_score": 0.3,
            "in_domain_citation_score": 0.2,
            "relevance": 0.8,
            "citation_count": 0.3,
            "recency": 0.2,
        },
        final_sort_weights_1=dict(_MULTIPLICATIVE_FINAL_1),
        final_sort_weights_2=dict(_MULTIPLICATIVE_FINAL_2),
    )

    acadeepr_run3 = CiteFlowProfile(
        name="acadeepr-run3",
        description=(
            "Ablation regime (AcaDeepR inputConfig/run_my_3/*.yaml): skips the "
            "references expansion phase entirely (start_from_phase1 + from_phase2), "
            "disables the seed-batch early stop, and runs the mid-loop ranking "
            "unweighted."
        ),
        init_search=InitSearch(year=(2015, 2023), limit=50, queries_used=2),
        seed_llm=SeedLLM(enforce_limits=False),
        filter_params_cite=FilterParams(max_citations=7500, year_range=(2015, 2023)),
        filter_params=FilterParams(max_citations=8000, year_range=(2016, 2023)),
        mid_sort_weights=PASSTHROUGH,
        final_sort_weights_1=dict(_MULTIPLICATIVE_FINAL_1),
        final_sort_weights_2=dict(_MULTIPLICATIVE_FINAL_2),
        skip_refs_expansion=True,
    )

    semantic12 = CiteFlowProfile(
        name="semantic12",
        description=(
            "Earlier reference config (AcaDeepR inputConfig/semantic_12_20260115_00.yaml) "
            "using additive rather than multiplicative final relevance."
        ),
        init_search=InitSearch(year=(2015, 2023), limit=50, queries_used=2),
        refs=RefsParams(
            max_per_seed=100,
            top_k_co_cited=10,
            max_citing_papers=12,
            co_seed_selection=CoSeedSelection(
                min_papers=3,
                max_citation_exclude=5000,
                min_total_citations=500,
                min_seeds=2,
            ),
        ),
        filter_params_cite=FilterParams(max_citations=8000, year_range=(2016, 2023)),
        filter_params=FilterParams(max_citations=8000, year_range=(2016, 2023)),
        mid_sort_weights={
            "keyword_match_score": 0.2,
            "in_domain_citation_score": 0.2,
            "relevance": 0.8,
            "citation_count": 0.3,
            "recency": 0.2,
        },
        final_sort_weights_1={
            "keyword_match_score": 0.5,
            "relevance": 0.5,
            "citation_count": 0.1,
            "recency": 0.2,
        },
        final_sort_weights_2={
            "keyword_match_score": 0.2,
            "relevance": 0.7,
            "citation_count": 0.1,
            "recency": 0.2,
        },
    )

    profiles = {p.name: p for p in (acadeepr_run1, acadeepr_run3, semantic12)}
    profiles["default"] = dataclasses.replace(acadeepr_run1, name="default")
    return profiles


PROFILES: Dict[str, CiteFlowProfile] = _build_profiles()


class UnknownProfileError(KeyError):
    pass


class UnknownOverrideError(KeyError):
    pass


def _apply_override(obj: Any, parts: list[str], value: Any, full_path: str) -> Any:
    """Return a copy of ``obj`` with the dotted ``parts`` path set to ``value``."""
    head, rest = parts[0], parts[1:]

    if not dataclasses.is_dataclass(obj):
        raise UnknownOverrideError(
            f"Cannot apply override {full_path!r}: {type(obj).__name__} is not a profile section"
        )

    known = {f.name for f in dataclasses.fields(obj)}
    if head not in known:
        raise UnknownOverrideError(
            f"Unknown profile field {full_path!r} (no field {head!r} on {type(obj).__name__}; "
            f"known fields: {sorted(known)})"
        )

    if rest:
        nested = _apply_override(getattr(obj, head), rest, value, full_path)
        return dataclasses.replace(obj, **{head: nested})

    return dataclasses.replace(obj, **{head: value})


def resolve(profile: str | CiteFlowProfile | None = None, **overrides: Any) -> CiteFlowProfile:
    """Resolve a named profile, applying dotted-path overrides.

    ``resolve("acadeepr-run1", **{"refs.top_k_co_cited": 10, "seed_llm.enforce_limits": False})``
    """
    if isinstance(profile, CiteFlowProfile):
        resolved = profile
    else:
        name = profile or "default"
        try:
            resolved = PROFILES[name]
        except KeyError as exc:
            raise UnknownProfileError(
                f"Unknown profile {name!r}. Available: {sorted(PROFILES)}"
            ) from exc

    for path, value in overrides.items():
        resolved = _apply_override(resolved, path.split("."), value, path)
    return resolved


def list_profiles() -> list[dict[str, str]]:
    return [
        {"name": name, "description": profile.description}
        for name, profile in sorted(PROFILES.items())
    ]


def weights_for(weights: Weights) -> Dict[str, Any]:
    """Normalise a weights field into a dict usable by ``rank_by_importance``."""
    if weights == PASSTHROUGH:
        return {}
    return dict(weights)  # type: ignore[arg-type]
