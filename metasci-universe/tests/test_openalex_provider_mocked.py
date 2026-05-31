from __future__ import annotations

import asyncio

import httpx

from metasci_universe.schemas.authors import WorkAuthorsRequest
from metasci_universe.schemas.works import WorksSearchRequest
from metasci_universe.providers.openalex_api import OpenAlexAPIProvider


def _json_response(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload)


def test_openalex_provider_search_works_resolves_source_and_normalizes() -> None:
    asyncio.run(_test_openalex_provider_search_works_resolves_source_and_normalizes())


async def _test_openalex_provider_search_works_resolves_source_and_normalizes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/sources":
            return _json_response(
                {
                    "meta": {"count": 1},
                    "results": [
                        {
                            "id": "https://openalex.org/S123",
                            "display_name": "Journal of Informetrics",
                            "works_count": 1000,
                        }
                    ],
                }
            )
        if request.url.path == "/works":
            return _json_response(
                {
                    "meta": {"count": 1, "next_cursor": None},
                    "results": [
                        {
                            "id": "https://openalex.org/W1",
                            "doi": "https://doi.org/10.123/example",
                            "title": "A normalized work",
                            "publication_year": 2024,
                            "publication_date": "2024-01-01",
                            "type": "article",
                            "cited_by_count": 7,
                            "open_access": {"is_oa": True},
                            "primary_location": {
                                "source": {
                                    "id": "https://openalex.org/S123",
                                    "display_name": "Journal of Informetrics",
                                    "type": "journal",
                                    "issn_l": "1751-1577",
                                }
                            },
                            "topics": [{"id": "https://openalex.org/T1", "display_name": "Scientometrics", "score": 0.8}],
                            "abstract_inverted_index": {"Hello": [0]},
                            "authorships": [
                                {
                                    "author_position": "first",
                                    "author": {"id": "https://openalex.org/A1", "display_name": "Ada Lovelace"},
                                    "institutions": [{"id": "https://openalex.org/I1", "display_name": "Example U"}],
                                }
                            ],
                        }
                    ],
                }
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAlexAPIProvider(client=client)
    request = WorksSearchRequest(
        query="scientometrics",
        source_name="Journal of Informetrics",
        from_year=2024,
        to_year=2024,
        limit=10,
        include=["authors"],
    )

    result = await provider.search_works(request)
    await client.aclose()

    assert result.data[0]["id"] == "W1"
    assert result.data[0]["source"]["id"] == "S123"
    assert result.data[0]["authors"][0]["id"] == "A1"
    assert result.metadata["filtered_total"] == 1
    assert result.metadata["resolved_entities"]["source"]["id"] == "S123"
    works_request = [item for item in requests if item.url.path == "/works"][0]
    assert "primary_location.source.id:S123" in works_request.url.params["filter"]
    assert "type:article" in works_request.url.params["filter"]


def test_openalex_provider_search_works_adds_core_filters() -> None:
    asyncio.run(_test_openalex_provider_search_works_adds_core_filters())


async def _test_openalex_provider_search_works_adds_core_filters() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/works":
            return _json_response({"meta": {"count": 0, "next_cursor": None}, "results": []})
        raise AssertionError(f"unexpected path {request.url.path}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAlexAPIProvider(client=client)
    result = await provider.search_works(
        WorksSearchRequest(
            query="science",
            country_code="us",
            work_type="review",
            is_oa=True,
            min_cited_by_count=100,
            max_cited_by_count=500,
            limit=10,
        )
    )
    await client.aclose()

    filter_param = requests[0].url.params["filter"]
    assert result.metadata["filters"] == [
        "authorships.institutions.country_code:US",
        "type:review",
        "is_oa:true",
        "cited_by_count:>99",
        "cited_by_count:<501",
    ]
    assert "authorships.institutions.country_code:US" in filter_param
    assert "type:review" in filter_param
    assert "is_oa:true" in filter_param
    assert "cited_by_count:>99" in filter_param
    assert "cited_by_count:<501" in filter_param


def test_openalex_provider_topic_name_resolves_hierarchy_before_topic() -> None:
    asyncio.run(_test_openalex_provider_topic_name_resolves_hierarchy_before_topic())


async def _test_openalex_provider_topic_name_resolves_hierarchy_before_topic() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/topics":
            return _json_response(
                {
                    "meta": {"count": 1},
                    "results": [
                        {
                            "id": "https://openalex.org/T11636",
                            "display_name": "Artificial Intelligence in Healthcare and Education",
                            "works_count": 500,
                            "domain": {
                                "id": "https://openalex.org/domains/3",
                                "display_name": "Physical Sciences",
                            },
                            "field": {
                                "id": "https://openalex.org/fields/17",
                                "display_name": "Computer Science",
                            },
                            "subfield": {
                                "id": "https://openalex.org/subfields/1702",
                                "display_name": "Artificial Intelligence",
                            },
                        }
                    ],
                }
            )
        if request.url.path == "/works":
            return _json_response({"meta": {"count": 0, "next_cursor": None}, "results": []})
        raise AssertionError(f"unexpected path {request.url.path}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAlexAPIProvider(client=client)
    result = await provider.search_works(WorksSearchRequest(topic_name="Artificial Intelligence", limit=10))
    await client.aclose()

    topic = result.metadata["resolved_entities"]["topic"]
    assert topic["id"] == "subfields/1702"
    assert topic["display_name"] == "Artificial Intelligence"
    assert topic["type"] == "subfield"
    works_request = [item for item in requests if item.url.path == "/works"][0]
    assert "topics.subfield.id:subfields/1702" in works_request.url.params["filter"]


def test_openalex_provider_topic_name_falls_back_to_top_topic() -> None:
    asyncio.run(_test_openalex_provider_topic_name_falls_back_to_top_topic())


async def _test_openalex_provider_topic_name_falls_back_to_top_topic() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/topics":
            return _json_response(
                {
                    "meta": {"count": 1},
                    "results": [
                        {
                            "id": "https://openalex.org/T99",
                            "display_name": "Peer Review in Scientific Publishing",
                            "works_count": 1200,
                            "domain": {
                                "id": "https://openalex.org/domains/2",
                                "display_name": "Social Sciences",
                            },
                            "field": {
                                "id": "https://openalex.org/fields/33",
                                "display_name": "Communication",
                            },
                            "subfield": {
                                "id": "https://openalex.org/subfields/3304",
                                "display_name": "Library and Information Sciences",
                            },
                        }
                    ],
                }
            )
        if request.url.path == "/works":
            return _json_response({"meta": {"count": 0, "next_cursor": None}, "results": []})
        raise AssertionError(f"unexpected path {request.url.path}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAlexAPIProvider(client=client)
    result = await provider.search_works(WorksSearchRequest(topic_name="Peer Review", limit=10))
    await client.aclose()

    topic = result.metadata["resolved_entities"]["topic"]
    assert topic["id"] == "T99"
    assert topic["type"] == "topic"
    assert topic["match_level"] == "fuzzy"
    works_request = [item for item in requests if item.url.path == "/works"][0]
    assert "topics.id:T99" in works_request.url.params["filter"]


def test_openalex_provider_explicit_field_topic_id_uses_field_filter() -> None:
    asyncio.run(_test_openalex_provider_explicit_field_topic_id_uses_field_filter())


async def _test_openalex_provider_explicit_field_topic_id_uses_field_filter() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/works":
            return _json_response({"meta": {"count": 0, "next_cursor": None}, "results": []})
        raise AssertionError(f"unexpected path {request.url.path}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAlexAPIProvider(client=client)
    await provider.search_works(WorksSearchRequest(topic_id="fields/17", limit=10))
    await client.aclose()

    assert [request.url.path for request in requests] == ["/works"]
    assert "topics.field.id:fields/17" in requests[0].url.params["filter"]


def test_openalex_provider_topic_match_does_not_use_word_subset() -> None:
    provider = OpenAlexAPIProvider()

    assert provider._hierarchical_match("Computer", "Computer Science")
    assert provider._hierarchical_match("Computer Science", "Computer Science")
    assert not provider._hierarchical_match("Science", "Computer Science")
    assert not provider._hierarchical_match("Art", "Artificial Intelligence")


def test_openalex_provider_authors_from_work() -> None:
    asyncio.run(_test_openalex_provider_authors_from_work())


async def _test_openalex_provider_authors_from_work() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/works/doi:10.123/example"
        return _json_response(
            {
                "id": "https://openalex.org/W1",
                "doi": "https://doi.org/10.123/example",
                "title": "A paper",
                "publication_year": 2020,
                "authorships": [
                    {
                        "author_position": "first",
                        "author": {"id": "https://openalex.org/A1", "display_name": "First Author"},
                        "institutions": [],
                    },
                    {
                        "author_position": "last",
                        "author": {"id": "https://openalex.org/A2", "display_name": "Second Author"},
                        "institutions": [],
                    },
                ],
            }
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAlexAPIProvider(client=client)
    result = await provider.authors_from_work(WorkAuthorsRequest(identifier="10.123/example", all_authors=True))
    await client.aclose()

    assert result.metadata["total_authors"] == 2
    assert result.data[1]["id"] == "A2"
