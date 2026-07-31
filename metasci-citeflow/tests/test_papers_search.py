from __future__ import annotations

import asyncio

import pytest

from metasci_citeflow import registry
from metasci_citeflow.deps import CiteFlowDeps
from metasci_citeflow.papers import (
    merge_openalex_into,
    merge_search_results,
    resolution_queries,
)
from metasci_citeflow.session import Session, clear_cache
from metasci_citeflow.errors import S2Unavailable
from fakes import FakeOpenAlex, FakeS2, oa_work, s2_paper


@pytest.fixture(autouse=True)
def _isolated_cache():
    clear_cache()
    yield
    clear_cache()


# ---------------------------------------------------------------------------
# Merge semantics
# ---------------------------------------------------------------------------


def test_merge_dedupes_across_queries_and_stamps_rank() -> None:
    merged = merge_search_results(
        [
            ("q1", [s2_paper("1"), s2_paper("2")]),
            ("q2", [s2_paper("2"), s2_paper("3")]),
        ]
    )

    assert [p["corpus_id"] for p in merged] == ["1", "2", "3"]
    # search_rank is the position in the merged list, 0-based - it decides which citing
    # papers get picked during references expansion.
    assert [p["search_rank"] for p in merged] == [0, 1, 2]
    assert [p["_search_query_index"] for p in merged] == [0, 0, 1]


def test_merge_skips_papers_without_any_id() -> None:
    merged = merge_search_results([("q", [{"title": "anonymous"}, s2_paper("1")])])
    assert [p["corpus_id"] for p in merged] == ["1"]


def test_resolution_queries_carry_doi_mag_and_title() -> None:
    queries = resolution_queries(
        [s2_paper("1", doi="10.1/a", mag="555", title="T"), s2_paper("2", title="Only title")]
    )

    assert queries[0] == {"doi": "10.1/a", "mag": "555", "title": "T"}
    assert queries[1] == {"title": "Only title"}


def test_merge_openalex_prefers_graph_fields_but_keeps_corpus_id() -> None:
    s2 = s2_paper("215548661", doi="10.1/a", cited_by=600, abstract="s2 abstract")
    oa = oa_work("W1", cited_by=620, refs=["W10", "W11"], abstract="oa abstract")

    merged = merge_openalex_into(s2, oa)

    assert merged["openalex_id"] == "W1"
    # Ground truth is matched on both ids, so the corpus_id must survive resolution.
    assert merged["corpus_id"] == "215548661"
    assert merged["reference_ids"] == ["W10", "W11"]
    assert merged["cited_by_count"] == 620
    # S2's abstract is kept when present; OpenAlex only fills gaps.
    assert merged["abstract"] == "s2 abstract"


def test_merge_openalex_fills_a_missing_abstract() -> None:
    merged = merge_openalex_into(
        s2_paper("1", abstract=""), oa_work("W1", abstract="reconstructed")
    )
    assert merged["abstract"] == "reconstructed"


def test_merge_openalex_tolerates_an_unresolved_paper() -> None:
    merged = merge_openalex_into(s2_paper("1"), None)
    assert merged["openalex_id"] is None
    assert merged["corpus_id"] == "1"


# ---------------------------------------------------------------------------
# The tool: the ID-space invariant
# ---------------------------------------------------------------------------


def _session_with_analysis(tmp_path, queries=("q1", "q2")):
    session = Session.create(query="test", profile="acadeepr-run1", root=tmp_path)
    session.set_analysis(
        {
            "search_queries": list(queries),
            "structured_keywords": [["alignment", "factual"]],
            "discriminative_terms": {"factuality": 9},
            "rerank_query": "factual alignment",
        }
    )
    return session


def _deps(s2_results, oa: FakeOpenAlex) -> CiteFlowDeps:
    return CiteFlowDeps(s2=FakeS2(s2_results), openalex=oa)


def test_search_resolves_every_paper_to_an_openalex_id(tmp_path) -> None:
    session = _session_with_analysis(tmp_path)
    oa = FakeOpenAlex(
        works={
            "W1": oa_work("W1", refs=["W10"], abstract="a1"),
            "W2": oa_work("W2", refs=["W20"], abstract="a2"),
        },
        by_doi={"10.1/a": "W1", "10.1/b": "W2"},
    )
    deps = _deps(
        {
            "q1": [s2_paper("1", doi="10.1/a"), s2_paper("2", doi="10.1/b")],
            "q2": [s2_paper("2", doi="10.1/b")],
        },
        oa,
    )

    result = asyncio.run(
        registry.run_tool(
            "cf.papers.search",
            {"session_id": session.session_id, "session_dir": str(tmp_path)},
            deps=deps,
        )
    )

    assert result.data["merged"] == 2
    assert result.data["resolved"] == 2
    assert result.data["openalex_coverage"] == 1.0
    assert result.data["unresolved"] == []

    records = Session.open(session.session_id, root=tmp_path).store.get_all_papers()
    # One record per merged paper - resolution must not create an OpenAlex/S2 duplicate pair.
    assert len(records) == 2
    for record in records:
        assert record.openalex_id.startswith("W")
        assert all(ref.startswith("W") for ref in record.reference_ids)
        assert record.search_rank is not None
        assert record.abstract


def test_search_reports_unresolved_papers_instead_of_dropping_them(tmp_path) -> None:
    session = _session_with_analysis(tmp_path, queries=("q1",))
    oa = FakeOpenAlex(works={"W1": oa_work("W1")}, by_doi={"10.1/a": "W1"})
    deps = _deps(
        {"q1": [s2_paper("1", doi="10.1/a"), s2_paper("2", title="unresolvable")]}, oa
    )

    result = asyncio.run(
        registry.run_tool(
            "cf.papers.search",
            {"session_id": session.session_id, "session_dir": str(tmp_path)},
            deps=deps,
        )
    )

    assert result.data["resolved"] == 1
    assert result.data["openalex_coverage"] == 0.5
    assert result.data["unresolved"][0]["corpus_id"] == "2"
    # Kept in the store - still useful for keyword relevance, just not expandable.
    assert len(Session.open(session.session_id, root=tmp_path).store.get_all_papers()) == 2


def test_search_falls_back_from_doi_to_mag(tmp_path) -> None:
    session = _session_with_analysis(tmp_path, queries=("q1",))
    oa = FakeOpenAlex(works={"W5": oa_work("W5")}, by_mag={"555": "W5"})
    deps = _deps({"q1": [s2_paper("1", mag="555")]}, oa)

    result = asyncio.run(
        registry.run_tool(
            "cf.papers.search",
            {"session_id": session.session_id, "session_dir": str(tmp_path)},
            deps=deps,
        )
    )

    assert result.data["resolved"] == 1


def test_search_uses_profile_query_budget_limit_and_year(tmp_path) -> None:
    session = _session_with_analysis(tmp_path, queries=("q1", "q2", "q3", "q4"))
    s2 = FakeS2({"q1": [s2_paper("1")], "q2": [s2_paper("2")]})
    deps = CiteFlowDeps(s2=s2, openalex=FakeOpenAlex())

    asyncio.run(
        registry.run_tool(
            "cf.papers.search",
            {"session_id": session.session_id, "session_dir": str(tmp_path)},
            deps=deps,
        )
    )

    # acadeepr-run1 uses search_queries[:2], limit 50, years 2015-2023.
    assert [call["query"] for call in s2.calls] == ["q1", "q2"]
    assert s2.calls[0]["limit"] == 50
    assert s2.calls[0]["year"] == "2015-2023"


def test_search_records_a_round_zero_ledger_row(tmp_path) -> None:
    session = _session_with_analysis(tmp_path, queries=("q1",))
    oa = FakeOpenAlex(works={"W1": oa_work("W1")}, by_doi={"10.1/a": "W1"})
    deps = _deps({"q1": [s2_paper("1", doi="10.1/a")]}, oa)

    asyncio.run(
        registry.run_tool(
            "cf.papers.search",
            {"session_id": session.session_id, "session_dir": str(tmp_path)},
            deps=deps,
        )
    )

    row = Session.open(session.session_id, root=tmp_path).get_round(0, "search")
    assert row is not None
    assert row["expanded_ids"] == ["W1"]
    assert row["params"]["queries"] == ["q1"]


def test_search_can_skip_resolution(tmp_path) -> None:
    session = _session_with_analysis(tmp_path, queries=("q1",))
    oa = FakeOpenAlex()
    deps = _deps({"q1": [s2_paper("1", doi="10.1/a")]}, oa)

    result = asyncio.run(
        registry.run_tool(
            "cf.papers.search",
            {
                "session_id": session.session_id,
                "resolve_openalex": False,
                "session_dir": str(tmp_path),
            },
            deps=deps,
        )
    )

    assert result.data["resolved"] == 0
    assert oa.resolve_calls == []


def test_search_requires_queries(tmp_path) -> None:
    session = Session.create(query="q", root=tmp_path)

    with pytest.raises(ValueError):
        asyncio.run(
            registry.run_tool(
                "cf.papers.search",
                {"session_id": session.session_id, "session_dir": str(tmp_path)},
                deps=CiteFlowDeps(s2=FakeS2({}), openalex=FakeOpenAlex()),
            )
        )


# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------


def test_repair_backfills_ids_and_abstracts(tmp_path) -> None:
    session = _session_with_analysis(tmp_path, queries=("q1",))
    session.store.add_papers(
        [s2_paper("1", doi="10.1/a", abstract=""), s2_paper("2", doi="10.1/b")],
        source="search",
    )
    session.save()

    oa = FakeOpenAlex(
        works={"W1": oa_work("W1", refs=["W10"], abstract="recovered abstract")},
        by_doi={"10.1/a": "W1"},
    )

    result = asyncio.run(
        registry.run_tool(
            "cf.papers.repair",
            {"session_id": session.session_id, "session_dir": str(tmp_path)},
            deps=CiteFlowDeps(openalex=oa),
        )
    )

    assert result.data["resolved"] == 1
    assert result.data["abstracts_filled"] == 1
    assert result.data["still_missing"] == 1

    record = Session.open(session.session_id, root=tmp_path).store.get_record("1")
    assert record.openalex_id == "W1"
    assert record.abstract == "recovered abstract"
    assert record.reference_ids == ["W10"]


def test_repair_is_idempotent(tmp_path) -> None:
    session = _session_with_analysis(tmp_path, queries=("q1",))
    session.store.add_papers([s2_paper("1", doi="10.1/a")], source="search")
    session.save()
    oa = FakeOpenAlex(works={"W1": oa_work("W1")}, by_doi={"10.1/a": "W1"})

    args = {"session_id": session.session_id, "session_dir": str(tmp_path)}
    first = asyncio.run(registry.run_tool("cf.papers.repair", args, deps=CiteFlowDeps(openalex=oa)))
    second = asyncio.run(registry.run_tool("cf.papers.repair", args, deps=CiteFlowDeps(openalex=oa)))

    assert first.data["resolved"] == 1
    assert second.data["resolved"] == 0  # nothing left to do
    assert second.data["still_missing"] == 0


# ---------------------------------------------------------------------------
# Provider fallback
# ---------------------------------------------------------------------------


class _RateLimitedS2:
    """S2 double that is always throttled."""

    def __init__(self) -> None:
        self.calls = 0

    async def search(self, query, *, limit=50, year=None):
        self.calls += 1
        raise S2Unavailable("rate limited after 5 retries")


class _SearchingOpenAlex(FakeOpenAlex):
    def __init__(self, results, **kwargs):
        super().__init__(**kwargs)
        self.results = results
        self.search_calls = []

    async def search(self, query, *, limit=50, year=None):
        self.search_calls.append({"query": query, "limit": limit, "year": year})
        return [dict(p) for p in self.results.get(query, [])]


def test_search_falls_back_to_openalex_when_s2_is_rate_limited(tmp_path) -> None:
    session = _session_with_analysis(tmp_path, queries=("q1", "q2"))
    s2 = _RateLimitedS2()
    oa = _SearchingOpenAlex({"q1": [oa_work("W1", refs=["W10"])], "q2": [oa_work("W2")]})

    result = asyncio.run(
        registry.run_tool(
            "cf.papers.search",
            {"session_id": session.session_id, "session_dir": str(tmp_path)},
            deps=CiteFlowDeps(s2=s2, openalex=oa),
        )
    )

    assert result.data["provider"] == "openalex"
    assert result.data["merged"] == 2
    # OpenAlex results are already OpenAlex works, so no resolution round trip is needed.
    assert result.data["openalex_coverage"] == 1.0
    assert oa.resolve_calls == []
    assert result.data["diagnostics"]
    assert [c["query"] for c in oa.search_calls] == ["q1", "q2"]

    records = Session.open(session.session_id, root=tmp_path).store.get_all_papers()
    assert {r.openalex_id for r in records} == {"W1", "W2"}


def test_rate_limited_s2_raises_rather_than_returning_empty() -> None:
    # An empty list would be indistinguishable from "no results for this query",
    # and the store would silently stay empty.
    s2 = _RateLimitedS2()
    with pytest.raises(S2Unavailable):
        asyncio.run(s2.search("q"))
