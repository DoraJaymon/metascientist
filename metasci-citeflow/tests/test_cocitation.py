from __future__ import annotations

import asyncio

import pytest

from metasci_citeflow import registry
from metasci_citeflow.deps import CiteFlowDeps
from metasci_citeflow.graph import cocitation as cc
from metasci_citeflow.session import Session, clear_cache
from fakes import FakeOpenAlex, oa_work


@pytest.fixture(autouse=True)
def _isolated_cache():
    clear_cache()
    yield
    clear_cache()


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


def test_collect_counts_only_papers_meeting_min_count() -> None:
    papers = [
        oa_work("W1", refs=["WA", "WB"]),
        oa_work("W2", refs=["WA", "WC"]),
        oa_work("W3", refs=["WA", "WB"]),
    ]

    counts, citing = cc.collect_co_citations(papers, min_count=2)

    assert counts == {"WA": 3, "WB": 2}
    assert citing["WA"] == ["W1", "W2", "W3"]
    assert "WC" not in counts


def test_a_paper_citing_the_same_work_twice_counts_once() -> None:
    counts, citing = cc.collect_co_citations(
        [oa_work("W1", refs=["WA", "WA", "WA"]), oa_work("W2", refs=["WA"])], min_count=2
    )

    assert counts["WA"] == 2
    assert citing["WA"] == ["W1", "W2"]


def test_papers_without_an_id_are_ignored() -> None:
    counts, _ = cc.collect_co_citations(
        [{"referenced_works": ["WA"]}, oa_work("W1", refs=["WA"]), oa_work("W2", refs=["WA"])],
        min_count=2,
    )
    assert counts["WA"] == 2


# ---------------------------------------------------------------------------
# Bucketing
# ---------------------------------------------------------------------------


def test_buckets_split_strong_from_weak() -> None:
    counts = {"a": 2, "b": 3, "c": 10, "d": 11, "e": 5}

    strong, weak = cc.bucket_co_citations(counts, strong=(3, 10))

    # 11 is excluded: a work this widely co-cited is usually a general classic whose own
    # references sprawl outside the topic.
    assert set(strong) == {"b", "c", "e"}
    assert weak == ["a"]
    assert strong[0] == "c"  # ordered by count desc


def test_year_floor_keeps_papers_with_unknown_year() -> None:
    papers = [
        {"openalex_id": "W1", "year": 2009},
        {"openalex_id": "W2", "year": 2015},
        {"openalex_id": "W3", "year": None},
    ]
    kept = cc.apply_year_floor(papers, 2011)
    assert {p["openalex_id"] for p in kept} == {"W2", "W3"}


# ---------------------------------------------------------------------------
# Guided selection
# ---------------------------------------------------------------------------


def test_selection_prefers_citers_with_the_best_search_rank() -> None:
    selected = cc.select_papers_to_expand(
        ["WA"],
        {"WA": ["W3", "W1", "W2"]},
        {"W1": 0, "W2": 5, "W3": 9},
        max_citing_papers=2,
    )
    assert selected == ["W1", "W2"]


def test_selection_dedupes_across_co_cited_works_and_stops_at_the_cap() -> None:
    selected = cc.select_papers_to_expand(
        ["WA", "WB", "WC"],
        {"WA": ["W1", "W2"], "WB": ["W2", "W3"], "WC": ["W4"]},
        {"W1": 0, "W2": 1, "W3": 2, "W4": 3},
        max_citing_papers=3,
    )
    assert selected == ["W1", "W2", "W3"]


def test_selection_handles_missing_ranks() -> None:
    selected = cc.select_papers_to_expand(
        ["WA"], {"WA": ["W9", "W1"]}, {"W1": 0}, max_citing_papers=5
    )
    # Unranked papers sort last rather than crashing.
    assert selected == ["W1", "W9"]


# ---------------------------------------------------------------------------
# In-domain scoring
# ---------------------------------------------------------------------------


def test_in_domain_score_rewards_topic_concentration() -> None:
    # Same in-domain count, very different share of total citations.
    focused = cc.in_domain_score(10, 20)
    broad = cc.in_domain_score(10, 1000)

    assert focused > broad
    assert focused == pytest.approx(10 * (0.5**2))
    assert cc.in_domain_score(5, 0) is None


def test_network_stats_report_the_in_domain_ratio() -> None:
    papers = [oa_work("W1", refs=["W2", "WX"]), oa_work("W2", refs=["W1"])]

    stats = cc.network_stats(papers)

    assert stats["total_papers"] == 2
    assert stats["total_references"] == 3
    assert stats["in_domain_references"] == 2
    assert stats["in_domain_ratio"] == pytest.approx(2 / 3, abs=1e-4)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def _session(tmp_path, papers):
    session = Session.create(query="q", profile="acadeepr-run1", root=tmp_path)
    session.store.add_papers(papers, source="search")
    for index, paper in enumerate(papers):
        record = session.store.get_record(paper["openalex_id"])
        if record:
            record.search_rank = index
    session.save()
    return session


def test_co_cite_hydrates_missing_works_and_stashes_the_map(tmp_path) -> None:
    session = _session(
        tmp_path,
        [oa_work("W1", refs=["WA", "WB"]), oa_work("W2", refs=["WA"]), oa_work("W3", refs=["WA", "WB"])],
    )
    oa = FakeOpenAlex(works={"WA": oa_work("WA", title="Foundational"), "WB": oa_work("WB")})

    result = asyncio.run(
        registry.run_tool(
            "cf.citations.co_cite",
            {"session_id": session.session_id, "session_dir": str(tmp_path)},
            deps=CiteFlowDeps(openalex=oa),
        )
    )

    assert result.data["co_cited_total"] == 2
    assert result.data["added"] == 2
    assert result.data["co_cited"][0]["openalex_id"] == "WA"
    assert result.data["co_cited"][0]["co_citation_count"] == 3
    assert result.data["co_cited"][0]["title"] == "Foundational"
    # The heavy citing_map stays out of the tool payload.
    assert "citing_map" not in result.data

    reloaded = Session.open(session.session_id, root=tmp_path)
    assert reloaded.cocitation["citing_map"]["WA"] == ["W1", "W2", "W3"]
    assert reloaded.cocitation["search_ranks"] == {"W1": 0, "W2": 1, "W3": 2}


def test_co_cite_can_skip_hydration(tmp_path) -> None:
    session = _session(tmp_path, [oa_work("W1", refs=["WA"]), oa_work("W2", refs=["WA"])])
    oa = FakeOpenAlex()

    result = asyncio.run(
        registry.run_tool(
            "cf.citations.co_cite",
            {"session_id": session.session_id, "hydrate": False, "session_dir": str(tmp_path)},
            deps=CiteFlowDeps(openalex=oa),
        )
    )

    assert result.data["added"] == 0
    assert oa.get_by_ids_calls == []
    assert result.data["co_cited"][0]["in_store"] is False


def test_expand_refs_guided_uses_the_stashed_map(tmp_path) -> None:
    session = _session(
        tmp_path,
        [oa_work("W1", refs=["WA"]), oa_work("W2", refs=["WA"]), oa_work("W3", refs=["WA"])],
    )
    works = {
        "WA": oa_work("WA"),
        "W1": oa_work("W1", refs=["R1", "R2"]),
        "W2": oa_work("W2", refs=["R2", "R3"]),
        "W3": oa_work("W3", refs=["R4"]),
        "R1": oa_work("R1"),
        "R2": oa_work("R2"),
        "R3": oa_work("R3"),
        "R4": oa_work("R4"),
    }
    oa = FakeOpenAlex(works=works)
    args = {"session_id": session.session_id, "session_dir": str(tmp_path)}

    asyncio.run(registry.run_tool("cf.citations.co_cite", args, deps=CiteFlowDeps(openalex=oa)))
    result = asyncio.run(
        registry.run_tool(
            "cf.citations.expand_refs_guided",
            {**args, "max_citing_papers": 2, "limit_per_work": 10},
            deps=CiteFlowDeps(openalex=oa),
        )
    )

    # Best two by search rank.
    assert result.data["source_ids"] == ["W1", "W2"]
    assert result.data["added"] == 3  # R1, R2, R3 (R2 shared, R4 not reached)

    row = Session.open(session.session_id, root=tmp_path).get_round(0, "refs")
    assert row["source_ids"] == ["W1", "W2"]
    assert set(row["expanded_ids"]) == {"R1", "R2", "R3"}
    assert row["params"]["max_citing_papers"] == 2


def test_expand_refs_guided_requires_co_cite_first(tmp_path) -> None:
    session = _session(tmp_path, [oa_work("W1", refs=["WA"])])

    with pytest.raises(ValueError):
        asyncio.run(
            registry.run_tool(
                "cf.citations.expand_refs_guided",
                {"session_id": session.session_id, "session_dir": str(tmp_path)},
                deps=CiteFlowDeps(openalex=FakeOpenAlex()),
            )
        )


def test_expand_refs_guided_is_a_no_op_without_co_cited_works(tmp_path) -> None:
    session = _session(tmp_path, [oa_work("W1", refs=["WA"]), oa_work("W2", refs=["WB"])])
    oa = FakeOpenAlex()
    args = {"session_id": session.session_id, "session_dir": str(tmp_path)}

    co = asyncio.run(registry.run_tool("cf.citations.co_cite", args, deps=CiteFlowDeps(openalex=oa)))
    assert co.data["co_cited_total"] == 0  # nothing cited twice

    result = asyncio.run(
        registry.run_tool(
            "cf.citations.expand_refs_guided", args, deps=CiteFlowDeps(openalex=oa)
        )
    )
    assert result.data["source_ids"] == []
    assert result.data["added"] == 0
