"""Query planning helpers for private works retrieval."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from metasci_provider.schemas import WorkQueryPlan, WorksSearchServiceRequest


@dataclass
class QueryPlanResult:
    plan: WorkQueryPlan
    filters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.model_dump(mode="json"),
            "filters": self.filters,
        }


def plan_works_search(request: WorksSearchServiceRequest) -> QueryPlanResult:
    diagnostics: list[str] = []
    dominant_filter = _dominant_filter(request)
    use_source_fact = bool(request.source_id or request.source_name) and dominant_filter == "source_year"
    use_topic_fact = bool(request.topic_id or request.topic_name) and dominant_filter == "topic_year"
    use_api_count = bool(request.provider == "api" or request.query)
    use_db_count = request.allow_db_count and not use_api_count
    use_db_fetch = request.provider in {"database", "auto"} and not request.query
    use_api_fetch = request.provider in {"api", "auto"} and bool(request.query)

    if request.query and (request.source_id or request.source_name or request.topic_id or request.topic_name):
        diagnostics.append("combined keyword + structured query detected; planner should use candidate-set narrowing")

    if request.include and "authors" in request.include:
        diagnostics.append("authors enrichment requested explicitly")
    if request.include and "references" in request.include:
        diagnostics.append("references enrichment requested explicitly")

    plan = WorkQueryPlan(
        route=request.provider,
        count_route="api" if use_api_count else "database" if use_db_count else "none",
        dominant_filter=dominant_filter,
        use_source_fact=use_source_fact,
        use_topic_fact=use_topic_fact,
        use_api_count=use_api_count,
        use_db_count=use_db_count,
        use_db_fetch=use_db_fetch,
        use_api_fetch=use_api_fetch,
        candidate_filters=_candidate_filters(request, dominant_filter),
        secondary_filters=_secondary_filters(request, dominant_filter),
        include=list(request.include),
        include_raw=list(request.include_raw),
        diagnostics=diagnostics,
    )
    return QueryPlanResult(plan=plan, filters=request.model_dump(mode="json"))


def _dominant_filter(request: WorksSearchServiceRequest) -> str:
    if request.query and not any([request.source_id, request.source_name, request.topic_id, request.topic_name, request.author_id, request.author_name, request.institution_id, request.institution_name]):
        return "keyword"
    if request.source_id or request.source_name:
        return "source_year"
    if request.topic_id or request.topic_name:
        return "topic_year"
    if request.author_id or request.author_name:
        return "author"
    if request.institution_id or request.institution_name:
        return "institution"
    return "mixed"


def _candidate_filters(request: WorksSearchServiceRequest, dominant_filter: str) -> list[str]:
    filters: list[str] = []
    if dominant_filter == "source_year" and (request.source_id or request.source_name):
        filters.append("source_id")
    if dominant_filter == "topic_year" and (request.topic_id or request.topic_name):
        filters.append("topic_id")
    if request.author_id or request.author_name:
        filters.append("author_id")
    if request.institution_id or request.institution_name:
        filters.append("institution_id")
    return filters


def _secondary_filters(request: WorksSearchServiceRequest, dominant_filter: str) -> list[str]:
    filters: list[str] = []
    if request.query:
        filters.append("query")
    if request.from_year is not None or request.to_year is not None:
        filters.append("year_range")
    if request.country_code:
        filters.append("country_code")
    if request.work_type:
        filters.append("work_type")
    if request.is_oa is not None:
        filters.append("is_oa")
    if request.min_cited_by_count is not None or request.max_cited_by_count is not None:
        filters.append("cited_by_count")
    if dominant_filter not in {"source_year", "topic_year"} and (request.source_id or request.source_name):
        filters.append("source_id")
    if dominant_filter not in {"topic_year"} and (request.topic_id or request.topic_name):
        filters.append("topic_id")
    if request.author_id or request.author_name:
        filters.append("author_id")
    if request.institution_id or request.institution_name:
        filters.append("institution_id")
    return filters
