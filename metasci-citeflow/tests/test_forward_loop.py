from __future__ import annotations

import asyncio

import pytest

from metasci_citeflow import registry
from metasci_citeflow.deps import CiteFlowDeps
from metasci_citeflow.llm.params_decider import (
    CitationParamsDecider,
    citation_distribution,
    clamp_decision,
    fallback_min_citations,
    year_distribution,
)
from metasci_citeflow.llm.relevance_selector import (
    RelevanceSelector,
    format_keywords_block,
    judge_batches,
)
from metasci_citeflow.session import Session, clear_cache
from fakes import FakeLLM, FakeOpenAlex, FakeReranker, RecordingSleep, oa_work


@pytest.fixture(autouse=True)
def _isolated_cache():
    clear_cache()
    yield
    clear_cache()


def reply(indices) -> str:
    return f"reasoning: these answer the question\nselected_indices: {list(indices)}"


def paper(oa_id: str, *, cited_by: int = 100, year: int = 2020) -> dict:
    return {
        "openalex_id": oa_id,
        "corpus_id": oa_id,
        "title": f"Paper {oa_id}",
        "abstract": f"Abstract {oa_id}",
        "year": year,
        "publication_year": year,
        "cited_by_count": cited_by,
        "citation_count": cited_by,
    }


# ---------------------------------------------------------------------------
# Relevance judging
# ---------------------------------------------------------------------------


def test_keywords_block_renders_head_plus_modifier() -> None:
    assert format_keywords_block([("alignment", "factual"), ("metric",)]) == (
        "- alignment + factual\n- metric"
    )
    assert "No structured keywords" in format_keywords_block([])


def test_judge_runs_two_slices_and_dedupes() -> None:
    llm = FakeLLM({"relevance_selection": [reply([1, 2]), reply([1])]})
    selector = RelevanceSelector(llm, model="m")
    papers = [paper(f"W{i}") for i in range(30)]

    result = asyncio.run(judge_batches(selector, "q", papers))

    # Two calls of 15 rather than one of 30: the prompt caps at 4 selections per call.
    assert len(llm.calls_for("relevance_selection")) == 2
    assert result["judged_ids"] == ["W0", "W1", "W15"]


def test_judge_accepts_selecting_nothing() -> None:
    llm = FakeLLM({"relevance_selection": [reply([]), reply([])]})
    selector = RelevanceSelector(llm, model="m")

    result = asyncio.run(judge_batches(selector, "q", [paper(f"W{i}") for i in range(30)]))

    assert result["judged_ids"] == []


def test_judge_skips_empty_slices() -> None:
    llm = FakeLLM({"relevance_selection": [reply([1])]})
    selector = RelevanceSelector(llm, model="m")

    result = asyncio.run(judge_batches(selector, "q", [paper("W1")]))

    # Only the first slice has papers; the second must not fire a call.
    assert len(llm.calls) == 1
    assert result["judged_ids"] == ["W1"]


# ---------------------------------------------------------------------------
# Distributions
# ---------------------------------------------------------------------------


def test_citation_distribution_reports_every_bin() -> None:
    dist = citation_distribution([paper("W1", cited_by=10), paper("W2", cited_by=2000)])

    assert dist == {"0-50": 1, "51-100": 0, "101-500": 0, "501-1000": 0, "1000+": 1}


def test_citation_bin_boundaries() -> None:
    for count, expected in [(50, "0-50"), (51, "51-100"), (100, "51-100"), (101, "101-500"),
                            (500, "101-500"), (501, "501-1000"), (1000, "501-1000"), (1001, "1000+")]:
        dist = citation_distribution([paper("W", cited_by=count)])
        assert dist[expected] == 1, f"{count} should land in {expected}"


def test_year_distribution_skips_unknown_years() -> None:
    papers = [paper("W1", year=2020), paper("W2", year=2020), {"openalex_id": "W3"}]
    assert year_distribution(papers) == {2020: 2}


# ---------------------------------------------------------------------------
# Params decider and its clamps
# ---------------------------------------------------------------------------


def test_decider_parses_a_well_formed_reply() -> None:
    llm = FakeLLM(
        {
            "citation_params_decision": [
                "reasoning: recent concentration\nyear_start: 2019\nmin_citations: 2"
            ]
        }
    )
    decider = CitationParamsDecider(llm, model="m")

    decision = asyncio.run(
        decider.decide(
            total_seed_citations=800,
            citation_distribution={"0-50": 10},
            year_distribution={2021: 5},
            year_end=2023,
        )
    )

    assert decision["year_start"] == 2019
    assert decision["min_citations"] == 2
    assert decision["clamped"] is False


def test_out_of_range_answers_are_clamped() -> None:
    # The prompt says min_citations <= 5, but models drift; an unclamped 50 would gut recall.
    high = clamp_decision(
        {"year_start": 2030, "min_citations": 50}, total_seed_citations=100, year_end=2023
    )
    assert high["year_start"] == 2022  # capped at year_end - 1
    assert high["min_citations"] == 5
    assert high["clamped"] is True

    low = clamp_decision(
        {"year_start": 1990, "min_citations": -3}, total_seed_citations=100, year_end=2023
    )
    assert low["year_start"] == 2010
    assert low["min_citations"] == 0


def test_unparseable_reply_falls_back_by_seed_citations() -> None:
    decision = clamp_decision({}, total_seed_citations=6000, year_end=2023)

    assert decision["year_start"] == 2017
    assert decision["min_citations"] == 3
    assert decision["clamped"] is True

    assert fallback_min_citations(1000) == 0
    assert fallback_min_citations(3000) == 1
    assert fallback_min_citations(9000) == 3


# ---------------------------------------------------------------------------
# Forward fetch
# ---------------------------------------------------------------------------


def _loop_session(tmp_path):
    session = Session.create(query="factual alignment", profile="acadeepr-run1", root=tmp_path)
    session.set_analysis(
        {
            "rerank_query": "factual alignment metric",
            "discriminative_terms": {"factuality": 9},
            "structured_keywords": [["alignment", "factual"]],
            "search_queries": ["factual alignment"],
        }
    )
    return session


def test_fetch_forward_passes_filters_and_records_the_round(tmp_path) -> None:
    session = _loop_session(tmp_path)
    session.store.add_papers([oa_work("SEED", cited_by=300, year=2020)], source="search")
    session.save()

    oa = FakeOpenAlex(
        citations={
            "SEED": [
                oa_work("C1", year=2021, cited_by=10),
                oa_work("C_old", year=2016, cited_by=10),
                oa_work("C_low", year=2021, cited_by=1),
            ]
        }
    )

    result = asyncio.run(
        registry.run_tool(
            "cf.citations.fetch_forward",
            {
                "session_id": session.session_id,
                "round": 2,
                "seed_ids": ["SEED"],
                "year_start": 2018,
                "min_citations": 5,
                "session_dir": str(tmp_path),
            },
            deps=CiteFlowDeps(openalex=oa),
        )
    )

    assert result.data["fetched"] == 1  # year and citation filters applied server-side
    assert result.data["added"] == 1
    call = oa.citation_calls[0]
    assert call["year_range"] == (2018, 2023)
    assert call["min_cited_by"] == 5

    row = Session.open(session.session_id, root=tmp_path).get_round(2, "citations")
    assert row["expanded_ids"] == ["C1"]
    assert row["params"]["min_citations"] == 5


def test_fetch_forward_reports_no_seeds_rather_than_failing(tmp_path) -> None:
    session = _loop_session(tmp_path)

    result = asyncio.run(
        registry.run_tool(
            "cf.citations.fetch_forward",
            {"session_id": session.session_id, "round": 2, "session_dir": str(tmp_path)},
            deps=CiteFlowDeps(openalex=FakeOpenAlex()),
        )
    )

    assert result.data["seeds"] == 0
    assert "note" in result.data


def test_fetch_forward_maps_field_names_to_openalex_ids(tmp_path) -> None:
    session = _loop_session(tmp_path)
    session.store.add_papers([oa_work("SEED")], source="search")
    session.save()
    oa = FakeOpenAlex(citations={"SEED": []})

    asyncio.run(
        registry.run_tool(
            "cf.citations.fetch_forward",
            {
                "session_id": session.session_id,
                "round": 2,
                "seed_ids": ["SEED"],
                "field": "computer science",
                "session_dir": str(tmp_path),
            },
            deps=CiteFlowDeps(openalex=oa),
        )
    )

    assert oa.citation_calls[0]["field_id"] == "fields/17"


# ---------------------------------------------------------------------------
# The per-round seed pick
# ---------------------------------------------------------------------------


def test_select_citations_seeds_from_the_previous_round(tmp_path) -> None:
    session = _loop_session(tmp_path)
    session.store.add_papers(
        [oa_work(f"C{i}", cited_by=200, year=2021) for i in range(5)], source="citation"
    )
    session.record_round(
        round_num=1, phase="citations", expanded_ids=[f"C{i}" for i in range(5)]
    )
    session.save()

    llm = FakeLLM(
        {
            "relevance_selection": [reply([1]), reply([])],
            "seed_selection": [reply([1, 2])],
        }
    )
    result = asyncio.run(
        registry.run_tool(
            "cf.seeds.select_citations",
            {"session_id": session.session_id, "round": 2, "session_dir": str(tmp_path)},
            deps=CiteFlowDeps(llm=llm, reranker=FakeReranker(), sleep=RecordingSleep()),
        )
    )

    assert result.data["candidates"] == 5
    assert len(result.data["seed_ids"]) == 2
    assert result.data["judged_ids"]
    assert result.data["top_paper_ids"]

    reloaded = Session.open(session.session_id, root=tmp_path)
    for seed in result.data["seed_ids"]:
        assert reloaded.store.get_record(seed).is_seed is True


def test_select_citations_excludes_existing_seeds(tmp_path) -> None:
    session = _loop_session(tmp_path)
    session.store.add_papers(
        [oa_work("C1", cited_by=200, year=2021), oa_work("C2", cited_by=200, year=2021)],
        source="citation",
    )
    session.store.mark_as_seeds(["C1"], tag="seed_r1")
    session.record_round(round_num=1, phase="citations", expanded_ids=["C1", "C2"])
    session.save()

    llm = FakeLLM({"relevance_selection": [reply([])], "seed_selection": [reply([1])]})
    result = asyncio.run(
        registry.run_tool(
            "cf.seeds.select_citations",
            {"session_id": session.session_id, "round": 2, "session_dir": str(tmp_path)},
            deps=CiteFlowDeps(llm=llm, reranker=FakeReranker(), sleep=RecordingSleep()),
        )
    )

    # C1 was already expanded from, so only C2 can be picked again.
    assert result.data["seed_ids"] == ["C2"]


def test_select_citations_without_candidates_is_a_no_op(tmp_path) -> None:
    session = _loop_session(tmp_path)
    session.record_round(round_num=1, phase="citations", expanded_ids=[])
    session.save()

    result = asyncio.run(
        registry.run_tool(
            "cf.seeds.select_citations",
            {"session_id": session.session_id, "round": 2, "session_dir": str(tmp_path)},
            deps=CiteFlowDeps(llm=FakeLLM({}), reranker=FakeReranker()),
        )
    )

    assert result.data["seed_ids"] == []
    assert "note" in result.data


def test_select_citations_requires_a_source_round(tmp_path) -> None:
    session = _loop_session(tmp_path)

    with pytest.raises(ValueError):
        asyncio.run(
            registry.run_tool(
                "cf.seeds.select_citations",
                {"session_id": session.session_id, "round": 2, "session_dir": str(tmp_path)},
                deps=CiteFlowDeps(llm=FakeLLM({}), reranker=FakeReranker()),
            )
        )


def test_distributions_tool_shapes_input_for_the_decider(tmp_path) -> None:
    session = _loop_session(tmp_path)
    session.store.add_papers(
        [oa_work("W1", cited_by=10, year=2021), oa_work("W2", cited_by=2000, year=2022)],
        source="search",
    )
    session.save()

    result = asyncio.run(
        registry.run_tool(
            "cf.store.distributions",
            {
                "session_id": session.session_id,
                "paper_ids": ["W1", "W2"],
                "session_dir": str(tmp_path),
            },
        )
    )

    assert result.data["citation_distribution"]["0-50"] == 1
    assert result.data["citation_distribution"]["1000+"] == 1
    # Year keys are strings so the payload survives a JSON round trip into decide_params.
    assert result.data["year_distribution"] == {"2021": 1, "2022": 1}
