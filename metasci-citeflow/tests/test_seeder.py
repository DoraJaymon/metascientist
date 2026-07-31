from __future__ import annotations

import asyncio

import pytest

from metasci_citeflow import registry
from metasci_citeflow.deps import CiteFlowDeps
from metasci_citeflow.graph.seeder import Seeder, call_with_retry, prepare_candidates
from metasci_citeflow.llm.seed_selector import SeedSelector, format_papers_block
from metasci_citeflow.profiles import resolve
from metasci_citeflow.session import Session, clear_cache
from fakes import FakeLLM, FakeOpenAlex, RecordingSleep, oa_work


@pytest.fixture(autouse=True)
def _isolated_cache():
    clear_cache()
    yield
    clear_cache()


def reply(indices) -> str:
    return f"reasoning: picked the central ones\nselected_indices: {list(indices)}"


def paper(oa_id: str, *, cited_by: int = 100, year: int = 2020, title: str = None) -> dict:
    return {
        "openalex_id": oa_id,
        "corpus_id": oa_id,
        "title": title or f"Paper {oa_id}",
        "abstract": f"Abstract for {oa_id}",
        "year": year,
        "cited_by_count": cited_by,
        "citation_count": cited_by,
    }


def _seeder(llm, profile=None, sleep=None) -> Seeder:
    return Seeder(
        llm,
        query="factual consistency metrics",
        profile=profile or resolve("acadeepr-run1"),
        sleep=sleep or RecordingSleep(),
    )


# ---------------------------------------------------------------------------
# Prompt rendering and index mapping
# ---------------------------------------------------------------------------


def test_papers_block_is_one_indexed_with_truncated_abstracts() -> None:
    block = format_papers_block(
        [{"title": "T1", "cited_by_count": 42, "abstract": "x" * 600}, {"title": "T2"}]
    )

    assert block.startswith("1. T1")
    assert "   Citation Count: 42" in block
    assert "x" * 500 + "..." in block
    assert "2. T2" in block


def test_selector_maps_one_indexed_replies_and_drops_out_of_range() -> None:
    llm = FakeLLM({"seed_selection": [reply([1, 3, 99])]})
    selector = SeedSelector(llm, model="m")

    result = asyncio.run(selector.select("q", [paper("W1"), paper("W2"), paper("W3")]))

    assert [p["openalex_id"] for p in result["selected_papers"]] == ["W1", "W3"]


def test_selector_accepts_an_empty_selection() -> None:
    llm = FakeLLM({"seed_selection": ["reasoning: none are suitable\nselected_indices: []"]})
    selector = SeedSelector(llm, model="m")

    result = asyncio.run(selector.select("q", [paper("W1")]))

    assert result["selected_papers"] == []
    assert result["reasoning"] == "none are suitable"


def test_selector_survives_an_unparseable_reply() -> None:
    llm = FakeLLM({"seed_selection": ["the model rambled without a list"]})
    selector = SeedSelector(llm, model="m")

    result = asyncio.run(selector.select("q", [paper("W1")]))
    assert result["selected_papers"] == []


# ---------------------------------------------------------------------------
# Batching and the citation budget
# ---------------------------------------------------------------------------


def test_enforce_limits_stops_once_the_budget_is_met() -> None:
    llm = FakeLLM({"seed_selection": [reply([1, 2])]})
    seeder = _seeder(llm)
    candidates = [paper(f"W{i}", cited_by=400) for i in range(30)]

    result = asyncio.run(
        seeder.select_seeds_with_llm(
            candidates, min_seeds=2, min_total_citations=600, enforce_limits=True
        )
    )

    assert len(result["seeds"]) == 2
    assert result["total_citations"] == 800
    # Budget met after batch 1, so the remaining two batches are never sent.
    assert result["batches"] == 1
    assert len(llm.calls_for("seed_selection")) == 1


def test_without_enforce_limits_every_batch_runs() -> None:
    llm = FakeLLM({"seed_selection": [reply([1]), reply([1]), reply([1])]})
    seeder = _seeder(llm, profile=resolve("acadeepr-run3"))
    candidates = [paper(f"W{i}", cited_by=400) for i in range(30)]

    result = asyncio.run(
        seeder.select_seeds_with_llm(
            candidates, min_seeds=2, min_total_citations=600, enforce_limits=False
        )
    )

    assert result["batches"] == 3
    assert len(result["seeds"]) == 3


def test_candidates_above_the_hard_ceiling_never_reach_the_llm() -> None:
    llm = FakeLLM({"seed_selection": [reply([1])]})
    seeder = _seeder(llm)

    result = asyncio.run(
        seeder.select_seeds_with_llm(
            [paper("W_huge", cited_by=9000), paper("W_ok", cited_by=300)],
            min_seeds=1,
            min_total_citations=0,
            enforce_limits=True,
        )
    )

    # 8000 ceiling inside the selector, distinct from the 5000 pre-rank filter.
    assert "W_huge" not in llm.calls[0]["user"]
    assert [s["openalex_id"] for s in result["seeds"]] == ["W_ok"]


def test_all_candidates_filtered_means_no_llm_call() -> None:
    llm = FakeLLM({})
    seeder = _seeder(llm)

    result = asyncio.run(
        seeder.select_seeds_with_llm(
            [paper("W1", cited_by=9000)], min_seeds=1, min_total_citations=0, enforce_limits=True
        )
    )

    assert result["seeds"] == []
    assert llm.calls == []


def test_seeds_are_deduplicated_across_batches() -> None:
    llm = FakeLLM({"seed_selection": [reply([1]), reply([1])]})
    seeder = _seeder(llm, profile=resolve("acadeepr-run3"))
    candidates = [paper("Wsame") for _ in range(20)]

    result = asyncio.run(
        seeder.select_seeds_with_llm(
            candidates, min_seeds=5, min_total_citations=10**6, enforce_limits=False
        )
    )

    assert len(result["seeds"]) == 1


# ---------------------------------------------------------------------------
# Two-strategy flow
# ---------------------------------------------------------------------------


def test_strategy_one_is_skipped_when_the_strong_bucket_is_too_small() -> None:
    llm = FakeLLM({"seed_selection": [reply([1])]})
    seeder = _seeder(llm)
    strong = [paper("W1"), paper("W2")]  # below min_papers=3
    weak = [paper("W9", cited_by=700)]

    result = asyncio.run(seeder.select_from_co_citations(strong, weak))

    assert result["strategies_used"] == [2]
    assert [s["openalex_id"] for s in result["seeds"]] == ["W9"]


def test_strategy_two_runs_with_a_decremented_budget() -> None:
    calls = []

    class TrackingSeeder(Seeder):
        async def select_seeds_with_llm(self, candidates, **kwargs):
            calls.append(kwargs)
            return await super().select_seeds_with_llm(candidates, **kwargs)

    llm = FakeLLM({"seed_selection": [reply([1]), reply([1])]})
    seeder = TrackingSeeder(
        llm,
        query="q",
        profile=resolve("acadeepr-run1"),
        sleep=RecordingSleep(),
    )
    strong = [paper(f"W{i}", cited_by=200) for i in range(5)]
    weak = [paper(f"V{i}", cited_by=500) for i in range(5)]

    result = asyncio.run(seeder.select_from_co_citations(strong, weak))

    assert result["strategies_used"] == [1, 2]
    # run1 wants 2 seeds / 600 citations; strategy 1 delivered 1 seed / 200.
    assert calls[0]["min_seeds"] == 2 and calls[0]["min_total_citations"] == 600
    assert calls[1]["min_seeds"] == 1 and calls[1]["min_total_citations"] == 400
    assert result["total_seed_citations"] == 700
    assert result["budget"]["met"] is True


def test_strategy_two_is_skipped_when_strategy_one_met_the_budget() -> None:
    llm = FakeLLM({"seed_selection": [reply([1, 2])]})
    seeder = _seeder(llm)
    strong = [paper(f"W{i}", cited_by=400) for i in range(5)]

    result = asyncio.run(seeder.select_from_co_citations(strong, [paper("V1")]))

    assert result["strategies_used"] == [1]
    assert result["budget"]["met"] is True


def test_strategy_two_excludes_papers_already_chosen() -> None:
    llm = FakeLLM({"seed_selection": [reply([1]), reply([1])]})
    seeder = _seeder(llm)
    shared = paper("Wshared", cited_by=100)
    strong = [shared, paper("W2"), paper("W3")]
    weak = [shared, paper("V2", cited_by=100)]

    result = asyncio.run(seeder.select_from_co_citations(strong, weak))

    ids = [s["openalex_id"] for s in result["seeds"]]
    assert ids.count("Wshared") == 1
    assert "V2" in ids


def test_no_seeds_is_reported_not_raised() -> None:
    llm = FakeLLM({"seed_selection": [reply([]), reply([])]})
    seeder = _seeder(llm)

    result = asyncio.run(
        seeder.select_from_co_citations([paper(f"W{i}") for i in range(5)], [paper("V1")])
    )

    assert result["seeds"] == []
    assert result["budget"]["met"] is False


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


def test_retry_backs_off_exponentially_then_succeeds() -> None:
    sleep = RecordingSleep()
    attempts = {"n": 0}

    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("provider hiccup")
        return "ok"

    result = asyncio.run(call_with_retry(flaky, sleep=sleep, initial_wait=5, max_wait=90))

    assert result == "ok"
    assert attempts["n"] == 3
    assert sleep.waits == [5, 10]


def test_retry_reraises_after_exhausting_attempts() -> None:
    sleep = RecordingSleep()

    async def always_fails():
        raise RuntimeError("down")

    with pytest.raises(RuntimeError):
        asyncio.run(call_with_retry(always_fails, sleep=sleep, max_retries=3, initial_wait=1))

    assert len(sleep.waits) == 2


# ---------------------------------------------------------------------------
# Candidate preparation
# ---------------------------------------------------------------------------


def test_prepare_candidates_applies_both_filters_and_quality_order(tmp_path) -> None:
    session = Session.create(query="q", root=tmp_path)
    session.store.add_papers(
        [
            oa_work("W_broad", cited_by=6000, year=2020),
            oa_work("W_old", cited_by=200, year=2005),
            oa_work("W_good", cited_by=300, year=2022),
            oa_work("W_meh", cited_by=50, year=2016),
        ],
        source="citation",
    )
    records = [session.store.get_record(i) for i in ("W_broad", "W_old", "W_good", "W_meh")]

    prepared = prepare_candidates(records, max_citation_exclude=5000, year_floor=2011)

    ids = [p["openalex_id"] for p in prepared]
    assert "W_broad" not in ids  # above the 5000 pre-rank ceiling
    assert "W_old" not in ids  # below the co-citation year floor
    assert ids[0] == "W_good"  # ranked by citations + recency


def test_prepare_candidates_skips_already_marked_seeds(tmp_path) -> None:
    session = Session.create(query="q", root=tmp_path)
    session.store.add_papers([oa_work("W1"), oa_work("W2")], source="citation")
    session.store.mark_as_seeds(["W1"], tag="seed_r0_refs")
    records = [session.store.get_record("W1"), session.store.get_record("W2")]

    prepared = prepare_candidates(records, max_citation_exclude=5000, year_floor=2011)

    assert [p["openalex_id"] for p in prepared] == ["W2"]


def test_prepare_candidates_tolerates_missing_records() -> None:
    assert prepare_candidates([None, None], max_citation_exclude=5000, year_floor=2011) == []


# ---------------------------------------------------------------------------
# Tool wiring
# ---------------------------------------------------------------------------


def _prepared_session(tmp_path):
    session = Session.create(query="factual consistency", profile="acadeepr-run1", root=tmp_path)
    # Four search papers all citing WA/WB/WC gives a strong bucket of 3, which is what
    # min_papers=3 requires before strategy 1 will run at all.
    session.store.add_papers(
        [oa_work(f"W{i}", refs=["WA", "WB", "WC"]) for i in range(1, 5)],
        source="search",
    )
    session.store.add_papers(
        [
            oa_work("WA", cited_by=400, year=2020, title="Central A"),
            oa_work("WB", cited_by=300, year=2021, title="Central B"),
            oa_work("WC", cited_by=250, year=2019, title="Central C"),
        ],
        source="citation",
    )
    session.save()
    return session


def test_select_refs_marks_seeds_and_records_a_ledger_row(tmp_path) -> None:
    session = _prepared_session(tmp_path)
    args = {"session_id": session.session_id, "session_dir": str(tmp_path)}
    asyncio.run(
        registry.run_tool(
            "cf.citations.co_cite",
            {**args, "hydrate": False},
            deps=CiteFlowDeps(openalex=FakeOpenAlex()),
        )
    )

    llm = FakeLLM({"seed_selection": [reply([1, 2])]})
    result = asyncio.run(
        registry.run_tool(
            "cf.seeds.select_refs", args, deps=CiteFlowDeps(llm=llm, sleep=RecordingSleep())
        )
    )

    assert set(result.data["seed_ids"]) == {"WA", "WB"}
    assert result.data["total_seed_citations"] == 700
    assert result.data["strategies_used"] == [1]

    reloaded = Session.open(session.session_id, root=tmp_path)
    assert reloaded.store.get_record("WA").is_seed is True
    assert "seed_r0_refs" in reloaded.store.get_record("WA").tags
    row = reloaded.get_round(0, "seeds_refs")
    assert set(row["seed_ids"]) == {"WA", "WB"}


def test_select_refs_requires_co_cite_first(tmp_path) -> None:
    session = _prepared_session(tmp_path)

    with pytest.raises(ValueError):
        asyncio.run(
            registry.run_tool(
                "cf.seeds.select_refs",
                {"session_id": session.session_id, "session_dir": str(tmp_path)},
                deps=CiteFlowDeps(llm=FakeLLM({})),
            )
        )


def test_seeds_mark_supports_manual_seeds(tmp_path) -> None:
    session = _prepared_session(tmp_path)

    result = asyncio.run(
        registry.run_tool(
            "cf.seeds.mark",
            {
                "session_id": session.session_id,
                "paper_ids": ["W1"],
                "tag": "manual",
                "session_dir": str(tmp_path),
            },
        )
    )

    assert result.data["marked"] == 1
    assert Session.open(session.session_id, root=tmp_path).store.get_record("W1").is_seed
