from __future__ import annotations

from metasci_provider.planner import plan_works_search
from metasci_provider.schemas import WorksSearchServiceRequest


def test_planner_marks_source_year_queries() -> None:
    request = WorksSearchServiceRequest(source_name="Nature Communications", from_year=2022, to_year=2024, limit=200)
    result = plan_works_search(request)

    assert result.plan.dominant_filter == "source_year"
    assert result.plan.use_source_fact is True
    assert "source_id" in result.plan.candidate_filters


def test_planner_keeps_keyword_and_structured_hybrid_notes() -> None:
    request = WorksSearchServiceRequest(
        query="large language model",
        source_name="Nature Communications",
        from_year=2025,
        to_year=2026,
        limit=400,
        include=["authors", "references"],
    )
    result = plan_works_search(request)

    assert result.plan.dominant_filter == "source_year"
    assert result.plan.include == ["authors", "references"]
    assert any("combined keyword + structured query" in note for note in result.plan.diagnostics)
    assert "query" in result.plan.secondary_filters
    assert "year_range" in result.plan.secondary_filters
