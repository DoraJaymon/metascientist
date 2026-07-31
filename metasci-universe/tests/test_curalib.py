from __future__ import annotations

import pytest

from metasci_universe.memory.curalib import PaperRecord, PaperStore


def _paper(corpus_id: str, **overrides) -> dict:
    paper = {
        "corpus_id": corpus_id,
        "openalex_id": f"W{corpus_id}",
        "title": f"Paper {corpus_id}",
        "abstract": f"Abstract for {corpus_id}",
        "year": 2020,
        "citation_count": 10,
        "reference_ids": [],
    }
    paper.update(overrides)
    return paper


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_save_load_round_trip_preserves_indexes(tmp_path) -> None:
    store = PaperStore()
    store.add_papers(
        [_paper("1"), _paper("2")],
        source="search",
        keywords="alpha beta",
        api_name="semantic_scholar",
    )
    store.advance_round()
    store.add_papers([_paper("3")], source="citation", parent_ids=["W1"], api_name="openalex")

    path = tmp_path / "store.json"
    store.save_to_json(str(path))
    loaded = PaperStore.load_from_json(str(path))

    assert len(loaded.get_all_papers()) == 3
    assert loaded._current_round == 1
    assert loaded._keyword_index == {"alpha beta": {"1", "2"}}
    # Regression: save_to_json used to omit api_index while load_from_json read it,
    # so the index silently emptied on every round trip.
    assert loaded._api_index == {"semantic_scholar": {"1", "2"}, "openalex": {"3"}}
    assert loaded._openalex_index == {"W1": "1", "W2": "2", "W3": "3"}


def test_save_load_round_trip_preserves_scores_and_history(tmp_path) -> None:
    store = PaperStore()
    store.add_papers([_paper("1")], source="search", keywords="alpha")
    store.update_scores([{"corpus_id": "1", "score": 0.75, "rationale": "on topic"}], score_type="llm")
    store.batch_update_scores({"1": 0.42}, field="keyword_match_score")
    store.mark_as_seeds(["1"], tag="seed_r0")

    path = tmp_path / "store.json"
    store.save_to_json(str(path))
    record = PaperStore.load_from_json(str(path)).get_record("1")

    assert record is not None
    assert record.llm_score == 0.75
    assert record.llm_rationale == "on topic"
    assert record.is_evaluated is True
    assert record.keyword_match_score == 0.42
    assert record.is_seed is True
    assert "seed_r0" in record.tags
    assert record.discovery_history == [
        {"round": 0, "source": "search", "keywords": "alpha", "parent_ids": None, "search_rank": None}
    ]


# ---------------------------------------------------------------------------
# Deduplication semantics (pinned - downstream seed selection depends on these)
# ---------------------------------------------------------------------------


def test_add_papers_dedupes_by_corpus_id_and_appends_history() -> None:
    store = PaperStore()
    first = store.add_papers([_paper("1")], source="search", keywords="alpha")
    second = store.add_papers([_paper("1")], source="search", keywords="beta")

    assert len(first) == 1
    assert second == []  # existing record updated in place, not returned as new
    record = store.get_record("1")
    assert record is not None
    assert len(record.discovery_history) == 2
    assert record.source_keywords == ["alpha", "beta"]
    assert store._keyword_index == {"alpha": {"1"}, "beta": {"1"}}


def test_add_papers_dedupes_by_openalex_id_when_corpus_id_differs() -> None:
    store = PaperStore()
    store.add_papers([_paper("1", openalex_id="W100")], source="search")
    added = store.add_papers(
        [_paper("999", openalex_id="W100")], source="citation", parent_ids=["W7"]
    )

    assert added == []
    assert len(store.get_all_papers()) == 1
    record = store.get_record("1")
    assert record is not None
    assert record.parent_paper_ids == {"W7"}


def test_add_papers_falls_back_to_openalex_id_as_corpus_id() -> None:
    store = PaperStore()
    store.add_papers([{"openalex_id": "W42", "title": "No corpus id"}], source="citation")

    record = store.get_record("W42")
    assert record is not None
    # Regression: the record used to keep corpus_id="" while being stored under the
    # openalex_id key, so anything reading record.corpus_id got an empty primary key.
    assert record.corpus_id == "W42"
    assert store._openalex_index["W42"] == "W42"


def test_add_papers_skips_records_without_any_identifier() -> None:
    store = PaperStore()
    added = store.add_papers([{"title": "anonymous"}], source="search")

    assert added == []
    assert store.get_all_papers() == []


def test_source_reflects_first_discovery() -> None:
    store = PaperStore()
    store.add_papers([_paper("1")], source="search", keywords="alpha")
    store.add_papers([_paper("1")], source="citation", parent_ids=["W9"])

    record = store.get_record("1")
    assert record is not None
    assert record.source == "search"
    assert store.get_stats()["search_papers"] == 1
    assert store.get_stats()["citation_papers"] == 0


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def test_rank_by_importance_orders_by_weighted_score() -> None:
    store = PaperStore()
    store.add_papers(
        [
            _paper("low", citation_count=1, year=2005),
            _paper("high", citation_count=5000, year=2024),
        ],
        source="search",
    )

    ranked = store.rank_by_importance(weights={"centrality": 0.5, "recency": 0.5})

    assert [r.corpus_id for r in ranked] == ["high", "low"]
    assert ranked[0].importance_score > ranked[1].importance_score


def test_rank_by_importance_uses_search_rank_when_no_embedding() -> None:
    store = PaperStore()
    store.add_papers(
        [_paper("a", search_rank=1), _paper("b", search_rank=50)],
        source="search",
    )

    ranked = store.rank_by_importance(
        weights={"relevance": 1.0}, relevance_priority=["embedding_sim", "search_rank", 0.02]
    )

    assert [r.corpus_id for r in ranked] == ["a", "b"]
    assert ranked[0]._relevance_score == 1.0
    assert ranked[1]._relevance_score == 0.02


def test_multiplicative_relevance_combines_keyword_and_embedding() -> None:
    store = PaperStore()
    store.add_papers([_paper("1")], source="search")
    store.batch_update_scores({"1": 0.5}, field="embedding_sim")
    store.batch_update_scores({"1": 0.4}, field="keyword_match_score")

    ranked = store.rank_by_importance(
        weights={
            "relevance_mode": "multiplicative",
            "keyword_scale": 0.7,
            "embedding_scale": 1.0,
            "combined_relevance": 0.5,
        }
    )

    # (1 + 0.7*0.4) * (1 + 1.0*0.5) - 1 = 0.92, weighted by combined_relevance 0.5
    assert ranked[0].importance_score == pytest.approx(0.46)


def test_high_relevance_papers_get_tagged() -> None:
    store = PaperStore()
    store.add_papers([_paper("1")], source="search")
    store.batch_update_scores({"1": 0.95}, field="embedding_sim")

    ranked = store.rank_by_importance(weights={"relevance": 0.5})

    assert "high_embedding_sim" in ranked[0].tags


# ---------------------------------------------------------------------------
# Stats / seeds
# ---------------------------------------------------------------------------


def test_get_stats_counts_evaluated_and_sources() -> None:
    store = PaperStore()
    store.add_papers([_paper("1"), _paper("2")], source="search", keywords="alpha")
    store.add_papers([_paper("3")], source="citation", parent_ids=["W1"])
    store.update_scores([{"corpus_id": "1", "score": 0.9}], score_type="llm")

    stats = store.get_stats()

    assert stats["total_papers"] == 3
    assert stats["evaluated_count"] == 1
    assert stats["search_papers"] == 2
    assert stats["citation_papers"] == 1
    assert stats["keywords_used"] == ["alpha"]


def test_mark_as_seeds_resolves_openalex_ids() -> None:
    store = PaperStore()
    store.add_papers([_paper("1", openalex_id="W100")], source="search")

    marked = store.mark_as_seeds(["W100"], tag="seed_r0")

    assert marked == 1
    record = store.get_record("1")
    assert record is not None and record.is_seed is True


def test_get_unevaluated_ids_filters_scored_papers() -> None:
    store = PaperStore()
    store.add_papers([_paper("1"), _paper("2")], source="search")
    store.update_scores([{"corpus_id": "1", "score": 0.9}], score_type="llm")

    assert store.get_unevaluated_ids(["1", "2"]) == ["2"]


def test_paper_record_to_dict_exposes_provider_aliases() -> None:
    record = PaperRecord(corpus_id="1", title="t", year=2020, citation_count=7)

    payload = record.to_dict()

    assert payload["publication_year"] == 2020
    assert payload["cited_by_count"] == 7
