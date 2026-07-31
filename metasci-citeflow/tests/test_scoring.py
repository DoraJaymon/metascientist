from __future__ import annotations

import asyncio

import pytest

from metasci_citeflow import registry
from metasci_citeflow.deps import CiteFlowDeps
from metasci_citeflow.filters import apply_filters
from metasci_citeflow.scoring import keywords as kw
from metasci_citeflow.scoring import reranker as rr
from metasci_citeflow.session import Session, clear_cache
from fakes import FakeReranker, oa_work


@pytest.fixture(autouse=True)
def _isolated_cache():
    clear_cache()
    yield
    clear_cache()


# ---------------------------------------------------------------------------
# Reranker
# ---------------------------------------------------------------------------


def test_document_text_joins_title_and_abstract() -> None:
    record = type("R", (), {"title": "A Title", "abstract": "The abstract."})()
    assert rr.document_text(record) == "A Title. The abstract."

    bare = type("R", (), {"title": "Only title", "abstract": ""})()
    assert rr.document_text(bare) == "Only title"


def test_scores_already_in_unit_range_are_kept_as_is() -> None:
    # The live API returns e.g. 0.9595 / 0.0147 / 0.0006 - rescaling by the max would
    # wrongly promote the best item in a batch of uniformly poor matches to 1.0.
    assert rr.normalise_scores([0.96, 0.015, 0.0006]) == [0.96, 0.015, 0.0006]


def test_out_of_range_scores_are_divided_by_the_max() -> None:
    assert rr.normalise_scores([8.0, 4.0, 0.0]) == [1.0, 0.5, 0.0]
    assert rr.normalise_scores([]) == []


def test_score_relevance_skips_already_scored_records(tmp_path) -> None:
    session = Session.create(query="q", root=tmp_path)
    session.store.add_papers([oa_work("W1"), oa_work("W2")], source="search")
    session.store.batch_update_scores({"W1": 0.5}, field="embedding_sim")

    reranker = FakeReranker()
    scores, report = asyncio.run(
        rr.score_relevance(session.store.get_all_papers(), "query", reranker)
    )

    assert report["skipped"] == 1
    assert set(scores) == {"W2"}

    forced_scores, forced = asyncio.run(
        rr.score_relevance(session.store.get_all_papers(), "query", reranker, force=True)
    )
    assert forced["skipped"] == 0
    assert set(forced_scores) == {"W1", "W2"}


def test_reranker_without_a_token_raises_a_named_error() -> None:
    client = rr.BGEReranker(api_token="")
    with pytest.raises(rr.RerankerUnavailable):
        asyncio.run(client.rerank("q", ["doc"]))


def test_reranker_batches_at_one_hundred() -> None:
    class Recording:
        def __init__(self):
            self.batches = []

        async def post(self, url, json, headers):
            self.batches.append(len(json["documents"]))
            return type(
                "R",
                (),
                {
                    "status_code": 200,
                    "json": lambda self=None, n=len(json["documents"]): {
                        "results": [
                            {"index": i, "relevance_score": 0.5} for i in range(n)
                        ]
                    },
                },
            )()

    recording = Recording()
    client = rr.BGEReranker(api_token="t", client=recording)
    scores = asyncio.run(client.rerank("q", [f"doc {i}" for i in range(250)]))

    assert recording.batches == [100, 100, 50]
    assert len(scores) == 250


# ---------------------------------------------------------------------------
# Keyword scoring
# ---------------------------------------------------------------------------


def test_noisy_or_accumulates_without_saturating() -> None:
    weights = {"factuality": 0.9, "metric": 0.5}

    one, matched_one = kw.score_text("a factuality study", weights)
    two, matched_two = kw.score_text("a factuality metric study", weights)

    assert one == pytest.approx(0.9)
    # 1 - (1-0.9)(1-0.5) = 0.95: the second match closes half the remaining gap.
    assert two == pytest.approx(0.95)
    assert set(matched_two) == {"factuality", "metric"}
    assert two > one < 1.0


def test_no_match_scores_zero() -> None:
    score, matched = kw.score_text("unrelated text", {"factuality": 0.9})
    assert score == 0.0 and matched == []


def test_multiword_terms_match_on_raw_text() -> None:
    score, matched = kw.score_text("we study factual alignment here", {"factual alignment": 0.8})
    assert matched == ["factual alignment"]
    assert score == pytest.approx(0.8)


def test_score_records_normalises_weights_and_reports_mode(tmp_path) -> None:
    session = Session.create(query="q", root=tmp_path)
    session.store.add_papers(
        [oa_work("W1", title="Factuality of summaries", abstract="metric study")],
        source="search",
    )

    scores, report = kw.score_records(
        session.store.get_all_papers(), {"factuality": 9, "metric": 5}
    )

    # Weights are rarity 1-10, divided by 10.
    assert scores["W1"] == pytest.approx(0.95)
    assert report["lemmatizer"] in {"spacy", "fallback"}
    assert report["per_term_hits"]["factuality"] == 1
    assert report["nonzero"] == 1


def test_lemma_mode_matches_inflected_forms() -> None:
    if kw.lemmatizer_mode("lemma") != "spacy":
        pytest.skip("spaCy en_core_web_sm not installed")

    # "metrics" in the text should match the term "metric" via lemmatisation.
    score, matched = kw.score_text("new metrics for evaluation", {"metric": 0.5})
    assert matched == ["metric"]
    assert score == pytest.approx(0.5)


def test_empty_terms_yield_an_empty_report() -> None:
    scores, report = kw.score_records([], {})
    assert scores == {} and report["scored"] == 0


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def test_filters_apply_citation_ceiling_and_year_window() -> None:
    records = [
        oa_work("W_broad", cited_by=9000, year=2020),
        oa_work("W_old", cited_by=100, year=2010),
        oa_work("W_ok", cited_by=300, year=2020),
    ]

    kept, reasons = apply_filters(records, max_citations=8000, year_range=(2016, 2023))

    assert [r["openalex_id"] for r in kept] == ["W_ok"]
    assert reasons == {"max_citations": 1, "year_range": 1}


def test_papers_with_unknown_year_survive_by_default() -> None:
    records = [oa_work("W1", year=None)]

    kept, _ = apply_filters(records, year_range=(2016, 2023))
    assert len(kept) == 1

    dropped, reasons = apply_filters(records, year_range=(2016, 2023), drop_missing_year=True)
    assert dropped == [] and reasons["missing_year"] == 1


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def _scored_session(tmp_path):
    session = Session.create(query="factual alignment", profile="acadeepr-run1", root=tmp_path)
    session.set_analysis(
        {
            "rerank_query": "factual alignment metric",
            "discriminative_terms": {"factuality": 9, "metric": 5},
            "search_queries": ["factual alignment"],
        }
    )
    session.store.add_papers(
        [
            oa_work("W1", title="Factuality metric", abstract="a metric", cited_by=300, year=2021),
            oa_work("W2", title="Unrelated work", abstract="other", cited_by=50, year=2020),
        ],
        source="search",
    )
    session.save()
    return session


def test_autoscore_writes_all_three_signals(tmp_path) -> None:
    session = _scored_session(tmp_path)

    result = asyncio.run(
        registry.run_tool(
            "cf.store.autoscore",
            {"session_id": session.session_id, "session_dir": str(tmp_path)},
            deps=CiteFlowDeps(reranker=FakeReranker()),
        )
    )

    assert result.data["rerank"]["scored"] == 2
    assert result.data["keywords"]["scored"] == 2
    assert result.data["coverage"]["embedding_sim"] == 1.0
    assert result.data["coverage"]["keyword_match_score"] == 1.0

    reloaded = Session.open(session.session_id, root=tmp_path)
    assert reloaded.store.get_record("W1").embedding_sim is not None
    assert reloaded.store.get_record("W1").keyword_match_score > 0


def test_autoscore_degrades_gracefully_without_a_reranker(tmp_path) -> None:
    session = _scored_session(tmp_path)

    class Broken:
        async def rerank(self, query, documents):
            raise rr.RerankerUnavailable("no token")

    result = asyncio.run(
        registry.run_tool(
            "cf.store.autoscore",
            {"session_id": session.session_id, "session_dir": str(tmp_path)},
            deps=CiteFlowDeps(reranker=Broken()),
        )
    )

    # The two free signals still land; the paid one is reported as a diagnostic.
    assert result.data["rerank"]["scored"] == 0
    assert result.data["diagnostics"]
    assert result.data["keywords"]["scored"] == 2


def test_filter_tool_uses_profile_presets(tmp_path) -> None:
    session = _scored_session(tmp_path)
    session.store.add_papers([oa_work("W_big", cited_by=9000, year=2020)], source="search")
    session.save()

    result = asyncio.run(
        registry.run_tool(
            "cf.papers.filter",
            {
                "session_id": session.session_id,
                "profile_key": "filter_params",
                "session_dir": str(tmp_path),
            },
        )
    )

    # acadeepr-run1 final filter: max_citations 8000, years 2016-2023.
    assert result.data["filters_used"]["max_citations"] == 8000
    assert "W_big" not in result.data["paper_ids"]


def test_rank_blends_signals_and_boosts_judged(tmp_path) -> None:
    session = _scored_session(tmp_path)
    asyncio.run(
        registry.run_tool(
            "cf.store.autoscore",
            {"session_id": session.session_id, "session_dir": str(tmp_path)},
            deps=CiteFlowDeps(reranker=FakeReranker({"Factuality metric. a metric": 0.9,
                                                     "Unrelated work. other": 0.1})),
        )
    )

    plain = asyncio.run(
        registry.run_tool(
            "cf.store.rank",
            {
                "session_id": session.session_id,
                "profile_key": "final_sort_weights_1",
                "boost_judged": False,
                "session_dir": str(tmp_path),
            },
        )
    )
    assert plain.data["paper_ids"][0] == "W1"
    assert plain.data["weights_used"]["relevance_mode"] == "multiplicative"

    # Mark the weaker paper as judged; +0.1 should lift it above.
    session = Session.open(session.session_id, root=tmp_path)
    session.add_judged(["W2"])
    boosted = asyncio.run(
        registry.run_tool(
            "cf.store.rank",
            {
                "session_id": session.session_id,
                "profile_key": "final_sort_weights_1",
                "session_dir": str(tmp_path),
            },
        )
    )
    assert boosted.data["boost_judged"] is True
    scores = {p["openalex_id"]: p["importance_score"] for p in boosted.data["papers"]}
    assert scores["W2"] > plain.data["papers"][1]["importance_score"]


def test_rank_dedupes_by_title(tmp_path) -> None:
    session = _scored_session(tmp_path)
    session.store.add_papers(
        [oa_work("W1dup", title="Factuality metric", cited_by=10, year=2021)], source="citation"
    )
    session.save()

    result = asyncio.run(
        registry.run_tool(
            "cf.store.rank",
            {
                "session_id": session.session_id,
                "dedupe_by_title": True,
                "session_dir": str(tmp_path),
            },
        )
    )

    titles = [p["title"] for p in result.data["papers"]]
    assert titles.count("Factuality metric") == 1


def test_rank_rejects_an_unknown_profile_key(tmp_path) -> None:
    session = _scored_session(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(
            registry.run_tool(
                "cf.store.rank",
                {
                    "session_id": session.session_id,
                    "profile_key": "nope",
                    "session_dir": str(tmp_path),
                },
            )
        )
