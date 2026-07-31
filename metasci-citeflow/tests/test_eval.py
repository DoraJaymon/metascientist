from __future__ import annotations

import asyncio
import json

import pytest

from metasci_citeflow import registry
from metasci_citeflow.eval.benchmark import Benchmark, BenchmarkQuery
from metasci_citeflow.eval.metrics import (
    evaluate_ranking,
    matched_positions,
    mean_average_precision,
    mrr,
    ndcg_at_k,
    paper_ids,
    precision_at_k,
    recall_at_k,
    store_coverage,
)
from metasci_citeflow.session import Session, clear_cache
from fakes import oa_work


@pytest.fixture(autouse=True)
def _isolated_cache():
    clear_cache()
    yield
    clear_cache()


def _query(n_truth: int = 3) -> BenchmarkQuery:
    return BenchmarkQuery(
        query_id="semantic_test",
        query="a research question",
        papers=[
            {"openalex_id": f"W{i}", "corpus_id": f"c{i}", "title_en": f"GT {i}"}
            for i in range(1, n_truth + 1)
        ],
    )


def _ranked(*ids: str):
    return [{"openalex_id": i, "corpus_id": ""} for i in ids]


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def test_ground_truth_matches_on_either_identifier() -> None:
    query = _query(2)

    # One prediction carries only the corpus id, the other only the OpenAlex id.
    ranked = [{"corpus_id": "c1"}, {"openalex_id": "W2"}]

    assert matched_positions(ranked, query.id_sets()) == [1, 2]


def test_duplicate_records_of_one_paper_count_once() -> None:
    query = _query(1)
    ranked = _ranked("W1", "W1", "W1")

    # Each ground-truth paper contributes at most its first appearance.
    assert matched_positions(ranked, query.id_sets()) == [1]


def test_paper_ids_normalises_openalex_urls() -> None:
    assert "W42" in paper_ids({"openalex_id": "https://openalex.org/W42"})


# ---------------------------------------------------------------------------
# Metric formulas (pinned to the original implementation)
# ---------------------------------------------------------------------------


def test_recall_at_k_counts_hits_within_the_cutoff() -> None:
    assert recall_at_k([1, 30, 80], num_truth=4, k=20) == pytest.approx(0.25)
    assert recall_at_k([1, 30, 80], num_truth=4, k=100) == pytest.approx(0.75)
    assert recall_at_k([], num_truth=0, k=20) == 0.0


def test_precision_at_k_is_normalised_by_ground_truth_size() -> None:
    # Deliberate deviation from textbook precision@k: with a median GT size of 1,
    # dividing by k would cap a perfect run at 0.05.
    assert precision_at_k([1], num_truth=1, k=20) == pytest.approx(1.0)
    assert precision_at_k([1], num_truth=2, k=20) == pytest.approx(0.5)
    assert precision_at_k([1, 2], num_truth=2, k=20) == pytest.approx(1.0)


def test_mrr_uses_the_first_hit() -> None:
    assert mrr([4, 9]) == pytest.approx(0.25)
    assert mrr([]) == 0.0


def test_map_averages_precision_at_each_hit() -> None:
    # hits at ranks 1 and 3 over 2 ground-truth papers: (1/1 + 2/3) / 2
    assert mean_average_precision([1, 3], num_truth=2) == pytest.approx((1 + 2 / 3) / 2)
    assert mean_average_precision([], num_truth=3) == 0.0


def test_ndcg_uses_the_inverse_sqrt_discount() -> None:
    # DCG discounts by 1/sqrt(i), not 1/log2(i+1) - preserved from the original.
    perfect = ndcg_at_k([1], num_truth=1, num_predicted=10, k=20)
    assert perfect == pytest.approx(1.0)

    second = ndcg_at_k([2], num_truth=1, num_predicted=10, k=20)
    assert second == pytest.approx(1 / (2**0.5))


def test_ndcg_is_zero_without_predictions() -> None:
    assert ndcg_at_k([], num_truth=2, num_predicted=0, k=20) == 0.0


# ---------------------------------------------------------------------------
# Store coverage
# ---------------------------------------------------------------------------


def test_store_coverage_is_ranking_independent() -> None:
    query = _query(3)
    papers = _ranked("W1", "W3", "W99")

    coverage = store_coverage(papers, query)

    assert coverage["num_ground_truth_in_store"] == 2
    assert coverage["ground_truth_store_coverage"] == pytest.approx(2 / 3, abs=1e-4)
    assert coverage["missing_titles"] == ["GT 2"]


def test_store_coverage_bounds_recall() -> None:
    query = _query(3)
    store = _ranked("W1", "W2")
    ranked = _ranked("W1")

    metrics = evaluate_ranking(ranked, query, store_papers=store)

    # Found 2 of 3, ranked only 1: coverage is the ceiling recall could reach.
    assert metrics.ground_truth_store_coverage == pytest.approx(2 / 3, abs=1e-4)
    assert metrics.overall_recall == pytest.approx(1 / 3)
    assert metrics.overall_recall <= metrics.ground_truth_store_coverage


def test_evaluate_reports_per_paper_positions() -> None:
    query = _query(3)
    metrics = evaluate_ranking(_ranked("W3", "X", "W1"), query)

    assert metrics.gt_positions == [3, None, 1]
    assert metrics.num_matched == 2
    assert metrics.overall_precision == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# Benchmark loading
# ---------------------------------------------------------------------------


def test_benchmark_round_trips(tmp_path) -> None:
    path = tmp_path / "bench.json"
    path.write_text(
        json.dumps(
            [
                {
                    "query_id": "semantic_1",
                    "query_en": "question one",
                    "papers": [{"openalex_id": "W1", "corpus_id": "c1", "title_en": "T"}],
                }
            ]
        ),
        encoding="utf-8",
    )

    bench = Benchmark.load(path)

    assert len(bench) == 1
    assert "semantic_1" in bench
    assert bench.get("semantic_1").size == 1
    with pytest.raises(KeyError):
        bench.get("nope")


def test_benchmark_missing_file_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        Benchmark.load(tmp_path / "absent.json")


def test_real_benchmark_shape_if_available() -> None:
    try:
        bench = Benchmark.load()
    except FileNotFoundError:
        pytest.skip("AcaDeepR benchmark not present")

    assert len(bench) == 47
    sizes = sorted(q.size for q in bench)
    # Median ground-truth size is 1, so per-query reporting is required.
    assert sizes[len(sizes) // 2] == 1
    assert max(sizes) == 26


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def _bench_file(tmp_path):
    path = tmp_path / "bench.json"
    path.write_text(
        json.dumps(
            [
                {
                    "query_id": "semantic_test",
                    "query_en": "q",
                    "papers": [
                        {"openalex_id": "W1", "corpus_id": "c1", "title_en": "GT one"},
                        {"openalex_id": "W2", "corpus_id": "c2", "title_en": "GT two"},
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    return str(path)


def test_eval_score_defaults_to_store_coverage(tmp_path) -> None:
    session = Session.create(query="q", root=tmp_path)
    session.store.add_papers([oa_work("W1"), oa_work("W9")], source="search")
    session.save()

    result = asyncio.run(
        registry.run_tool(
            "cf.eval.score",
            {
                "session_id": session.session_id,
                "query_id": "semantic_test",
                "benchmark_path": _bench_file(tmp_path),
                "session_dir": str(tmp_path),
            },
        )
    )

    assert result.data["ranking_scored"] is False
    assert result.data["ground_truth_store_coverage"] == pytest.approx(0.5)
    assert result.data["missing_titles"] == ["GT two"]


def test_eval_score_with_a_ranking(tmp_path) -> None:
    session = Session.create(query="q", root=tmp_path)
    session.store.add_papers([oa_work("W1"), oa_work("W2"), oa_work("W9")], source="search")
    session.save()

    result = asyncio.run(
        registry.run_tool(
            "cf.eval.score",
            {
                "session_id": session.session_id,
                "query_id": "semantic_test",
                "benchmark_path": _bench_file(tmp_path),
                "ranked_paper_ids": ["W9", "W1", "W2"],
                "session_dir": str(tmp_path),
            },
        )
    )

    assert result.data["ranking_scored"] is True
    assert result.data["num_matched"] == 2
    assert result.data["recall@20"] == pytest.approx(1.0)
    assert result.data["mrr"] == pytest.approx(0.5)
    assert result.data["gt_positions"] == [2, 3]


def test_eval_compare_tabulates_sessions(tmp_path) -> None:
    good = Session.create(query="q", root=tmp_path)
    good.store.add_papers([oa_work("W1"), oa_work("W2")], source="search")
    good.save()

    poor = Session.create(query="q", root=tmp_path)
    poor.store.add_papers([oa_work("W1")], source="search")
    poor.save()

    result = asyncio.run(
        registry.run_tool(
            "cf.eval.compare",
            {
                "session_ids": [good.session_id, poor.session_id],
                "query_ids": ["semantic_test"],
                "benchmark_path": _bench_file(tmp_path),
                "session_dir": str(tmp_path),
            },
        )
    )

    rows = result.data["rows"]
    assert len(rows) == 2
    assert rows[0]["ground_truth_store_coverage"] == pytest.approx(1.0)
    assert rows[1]["ground_truth_store_coverage"] == pytest.approx(0.5)
