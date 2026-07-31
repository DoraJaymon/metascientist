from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from metasci_citeflow.providers.openalex_graph import (
    OpenAlexGraph,
    compact_id,
    normalise_doi,
    parse_work,
    reconstruct_abstract,
)
from metasci_citeflow.providers.s2_search import parse_paper


# ---------------------------------------------------------------------------
# Semantic Scholar parsing
# ---------------------------------------------------------------------------

# Captured from the live S2 graph API. Note there is no OpenAlex id in externalIds -
# S2 never returns one, which is why every search result must be resolved separately.
S2_RAW = {
    "paperId": "d36e39aedd802aea4be1ea303c70dc56e97dbc3c",
    "externalIds": {
        "ArXiv": "2004.04228",
        "ACL": "2020.acl-main.450",
        "DBLP": "journals/corr/abs-2004-04228",
        "MAG": "3034188538",
        "DOI": "10.18653/v1/2020.acl-main.450",
        "CorpusId": 215548661,
    },
    "title": "Asking and Answering Questions to Evaluate the Factual Consistency of Summaries",
    "abstract": "Practical applications of abstractive summarization...",
    "year": 2020,
    "authors": [{"name": "Alex Wang"}, {"name": "Kyunghyun Cho"}],
    "venue": "Annual Meeting of the ACL",
    "citationCount": 620,
    "referenceCount": 41,
    "influentialCitationCount": 90,
    "fieldsOfStudy": ["Computer Science"],
}


def test_parse_paper_extracts_resolution_keys() -> None:
    paper = parse_paper(S2_RAW)

    assert paper is not None
    assert paper["corpus_id"] == "215548661"
    assert paper["doi"] == "10.18653/v1/2020.acl-main.450"
    assert paper["mag_id"] == "3034188538"
    # S2 has no OpenAlex id; cf.papers.search must resolve it.
    assert paper["openalex_id"] is None
    assert paper["citation_count"] == 620
    assert paper["cited_by_count"] == 620
    assert paper["authors"] == ["Alex Wang", "Kyunghyun Cho"]


def test_parse_paper_falls_back_to_paper_id_without_corpus_id() -> None:
    paper = parse_paper({"paperId": "abc123", "title": "No corpus id"})
    assert paper is not None
    assert paper["corpus_id"] == "abc123"


def test_parse_paper_rejects_records_without_identity() -> None:
    assert parse_paper({"title": "anonymous"}) is None
    assert parse_paper({}) is None


# ---------------------------------------------------------------------------
# OpenAlex parsing - abstract reconstruction was the regression
# ---------------------------------------------------------------------------


def test_reconstruct_abstract_restores_word_order() -> None:
    inverted = {"Deep": [0], "learning": [1], "for": [2], "summarization": [3], "learning.": [4]}
    assert reconstruct_abstract(inverted) == "Deep learning for summarization learning."


def test_reconstruct_abstract_handles_repeated_words() -> None:
    inverted = {"the": [0, 3], "cat": [1], "sat": [2], "mat": [4]}
    assert reconstruct_abstract(inverted) == "the cat sat the mat"


def test_reconstruct_abstract_handles_missing_index() -> None:
    assert reconstruct_abstract(None) == ""
    assert reconstruct_abstract({}) == ""


def test_parse_work_reconstructs_abstract_and_compacts_ids() -> None:
    raw = {
        "id": "https://openalex.org/W2963341956",
        "ids": {"openalex": "https://openalex.org/W2963341956", "mag": "2963341956"},
        "doi": "https://doi.org/10.18653/V1/2020.ACL-MAIN.450",
        "title": "Evaluating factual consistency",
        "publication_year": 2020,
        "cited_by_count": 620,
        "abstract_inverted_index": {"Factual": [0], "consistency": [1], "matters": [2]},
        "referenced_works": [
            "https://openalex.org/W111",
            "https://openalex.org/W222",
        ],
        "primary_location": {"source": {"display_name": "ACL"}},
        "authorships": [{"author": {"display_name": "Alex Wang"}}],
    }

    paper = parse_work(raw)

    assert paper is not None
    assert paper["openalex_id"] == "W2963341956"
    # Regression: the previous port hardcoded abstract="" for every citation-expanded paper.
    assert paper["abstract"] == "Factual consistency matters"
    assert paper["reference_ids"] == ["W111", "W222"]
    assert paper["referenced_works"] == ["W111", "W222"]
    assert paper["doi"] == "10.18653/v1/2020.acl-main.450"
    assert paper["mag_id"] == "2963341956"
    assert paper["venue"] == "ACL"
    assert paper["authors"] == ["Alex Wang"]
    assert paper["reference_count"] == 2


def test_parse_work_drops_non_work_references() -> None:
    raw = {
        "id": "https://openalex.org/W1",
        "referenced_works": ["https://openalex.org/W2", "", None, "A9999"],
    }
    paper = parse_work(raw)
    assert paper is not None
    assert paper["reference_ids"] == ["W2"]


def test_parse_work_rejects_work_without_id() -> None:
    assert parse_work({"title": "no id"}) is None
    assert parse_work(None) is None


def test_compact_and_doi_normalisation() -> None:
    assert compact_id("https://openalex.org/W42") == "W42"
    assert compact_id("W42") == "W42"
    assert compact_id(None) == ""
    assert normalise_doi("https://doi.org/10.1/ABC") == "10.1/abc"
    assert normalise_doi("doi:10.1/abc") == "10.1/abc"
    assert normalise_doi(None) == ""


# ---------------------------------------------------------------------------
# OpenAlexGraph query construction, against a recording provider
# ---------------------------------------------------------------------------


class RecordingProvider:
    """Captures the params handed to _fetch_cursor and replays canned works."""

    def __init__(self, pages: Dict[str, List[Dict[str, Any]]] | None = None) -> None:
        self.pages = pages or {}
        self.calls: List[Dict[str, Any]] = []

    async def _fetch_cursor(self, endpoint: str, *, params: Dict[str, Any], limit: int):
        self.calls.append({"endpoint": endpoint, "params": dict(params), "limit": limit})
        return list(self.pages.get(params.get("filter", ""), [])), {}


def _raw(oa_id: str, **extra: Any) -> Dict[str, Any]:
    payload = {"id": f"https://openalex.org/{oa_id}", "title": f"Work {oa_id}"}
    payload.update(extra)
    return payload


def test_get_by_ids_batches_by_fifty_and_preserves_order() -> None:
    ids = [f"W{i}" for i in range(1, 121)]
    pages = {}
    for start in range(0, 120, 50):
        chunk = ids[start : start + 50]
        pages["openalex:" + "|".join(chunk)] = [_raw(i) for i in chunk]

    provider = RecordingProvider(pages)
    graph = OpenAlexGraph(provider)

    results = asyncio.run(graph.get_by_ids(ids))

    assert len(provider.calls) == 3  # 50 + 50 + 20
    assert [r["openalex_id"] for r in results] == ids
    assert all(call["params"]["select"] for call in provider.calls)


def test_get_by_ids_skips_invalid_ids_and_reports_misses() -> None:
    # W404 is requested but OpenAlex returns nothing for it.
    provider = RecordingProvider({"openalex:W1|W404": [_raw("W1")]})
    graph = OpenAlexGraph(provider)

    results = asyncio.run(graph.get_by_ids(["W1", "12345", "W404"]))

    assert results[0]["openalex_id"] == "W1"
    assert results[1] is None  # non-W ids are never requested
    assert results[2] is None  # requested but not returned
    requested = provider.calls[0]["params"]["filter"]
    assert "12345" not in requested


def test_forward_citations_push_filters_into_the_query() -> None:
    provider = RecordingProvider()
    graph = OpenAlexGraph(provider)

    asyncio.run(
        graph.get_citations(
            ["W1"],
            year_range=(2018, 2023),
            min_cited_by=5,
            field_id="fields/17",
            max_per_work=500,
        )
    )

    filter_str = provider.calls[0]["params"]["filter"]
    assert "cites:W1" in filter_str
    assert "publication_year:2018-2023" in filter_str
    # ">= 5" is expressed as "> 4" because OpenAlex range filters are strict.
    assert "cited_by_count:>4" in filter_str
    assert "primary_topic.field.id:fields/17" in filter_str
    # Regression: the previous port capped at per_page<=200 and never paginated.
    assert provider.calls[0]["limit"] == 500
    assert provider.calls[0]["params"]["cursor"] == "*"


def test_forward_citations_default_to_unbounded_pagination() -> None:
    provider = RecordingProvider()
    graph = OpenAlexGraph(provider)

    asyncio.run(graph.get_citations(["W1"]))

    assert provider.calls[0]["limit"] > 200
    assert "cited_by_count" not in provider.calls[0]["params"]["filter"]
    assert "publication_year" not in provider.calls[0]["params"]["filter"]


def test_forward_citations_query_each_seed_for_attribution() -> None:
    provider = RecordingProvider(
        {
            "cites:W1": [_raw("W10")],
            "cites:W2": [_raw("W20")],
        }
    )
    graph = OpenAlexGraph(provider)

    result = asyncio.run(graph.get_citations(["W1", "W2"]))

    assert set(result) == {"W1", "W2"}
    assert result["W1"][0]["openalex_id"] == "W10"
    assert result["W2"][0]["openalex_id"] == "W20"


def test_forward_citations_survive_a_failing_seed() -> None:
    class Flaky(RecordingProvider):
        async def _fetch_cursor(self, endpoint, *, params, limit):
            if params["filter"].startswith("cites:W1"):
                raise RuntimeError("boom")
            return await super()._fetch_cursor(endpoint, params=params, limit=limit)

    provider = Flaky({"cites:W2": [_raw("W20")]})
    graph = OpenAlexGraph(provider)

    result = asyncio.run(graph.get_citations(["W1", "W2"]))

    assert result["W1"] == []
    assert result["W2"][0]["openalex_id"] == "W20"


def test_open_year_ranges_use_strict_bounds() -> None:
    provider = RecordingProvider()
    graph = OpenAlexGraph(provider)

    asyncio.run(graph.get_citations(["W1"], year_range=(2019, None)))
    assert "publication_year:>2018" in provider.calls[0]["params"]["filter"]

    asyncio.run(graph.get_citations(["W1"], year_range=(None, 2021)))
    assert "publication_year:<2022" in provider.calls[1]["params"]["filter"]


# ---------------------------------------------------------------------------
# Resolution: DOI -> MAG -> title
# ---------------------------------------------------------------------------


def test_resolve_many_prefers_doi_and_batches() -> None:
    pages = {
        "doi:10.1/a|10.1/b": [
            _raw("W1", doi="https://doi.org/10.1/A"),
            _raw("W2", doi="https://doi.org/10.1/B"),
        ]
    }
    provider = RecordingProvider(pages)
    graph = OpenAlexGraph(provider)

    results = asyncio.run(
        graph.resolve_many([{"doi": "10.1/a", "title": "x"}, {"doi": "10.1/B", "title": "y"}])
    )

    assert [r["openalex_id"] for r in results] == ["W1", "W2"]
    assert len(provider.calls) == 1  # one batched DOI request, no title fallback needed


def test_resolve_many_falls_back_to_mag_then_title() -> None:
    pages = {
        "mag:555": [_raw("W5", ids={"mag": "555"})],
        "type:article": [_raw("W9", title="A very specific paper title")],
    }
    provider = RecordingProvider(pages)
    graph = OpenAlexGraph(provider)

    results = asyncio.run(
        graph.resolve_many(
            [
                {"mag": "555", "title": "unused"},
                {"title": "A very specific paper title"},
                {"title": "nothing matches this"},
            ]
        )
    )

    assert results[0]["openalex_id"] == "W5"
    assert results[1]["openalex_id"] == "W9"
    # Title search returned a non-matching title, so it is rejected rather than accepted.
    assert results[2] is None


def test_resolve_many_returns_none_for_unresolvable_papers() -> None:
    provider = RecordingProvider()
    graph = OpenAlexGraph(provider)

    results = asyncio.run(graph.resolve_many([{}, {"doi": "10.1/missing"}]))

    assert results == [None, None]


def test_batch_get_references_hydrates_each_work_once() -> None:
    pages = {
        "openalex:W1|W2": [
            _raw("W1", referenced_works=["https://openalex.org/W100"]),
            _raw("W2", referenced_works=["https://openalex.org/W100", "https://openalex.org/W200"]),
        ],
        "openalex:W100|W200": [_raw("W100"), _raw("W200")],
    }
    provider = RecordingProvider(pages)
    graph = OpenAlexGraph(provider)

    result = asyncio.run(graph.batch_get_references(["W1", "W2"]))

    assert [p["openalex_id"] for p in result["W1"]] == ["W100"]
    assert [p["openalex_id"] for p in result["W2"]] == ["W100", "W200"]
    # W100 is shared by both seeds but fetched only once.
    assert len(provider.calls) == 2


def test_batch_get_references_respects_limit_per_work() -> None:
    pages = {
        "openalex:W1": [
            _raw("W1", referenced_works=[f"https://openalex.org/W{i}" for i in range(10, 20)])
        ],
        "openalex:W10|W11": [_raw("W10"), _raw("W11")],
    }
    provider = RecordingProvider(pages)
    graph = OpenAlexGraph(provider)

    result = asyncio.run(graph.batch_get_references(["W1"], limit_per_work=2))

    assert len(result["W1"]) == 2
