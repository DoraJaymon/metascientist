from __future__ import annotations

import asyncio
import json

import httpx

from metasci_universe.providers.sciencedirect_api import ScienceDirectAPIProvider
from metasci_universe.schemas.works import WorksFullTextRequest, WorksGetRequest, WorksSearchRequest


def _json_response(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload)


def test_sciencedirect_provider_search_works_normalizes_results() -> None:
    asyncio.run(_test_sciencedirect_provider_search_works_normalizes_results())


async def _test_sciencedirect_provider_search_works_normalizes_results() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "PUT"
        assert request.url.path == "/content/search/sciencedirect"
        body = json.loads(request.content.decode("utf-8"))
        assert body["qs"] == "deep learning AND drug discovery"
        assert body["display"] == {"offset": 0, "show": 2}
        assert body["date"] == "2024-2025"
        return _json_response(
            {
                "results": [
                    {
                        "title": "Deep learning for drug discovery",
                        "doi": "10.1016/j.example.2025.01.001",
                        "pii": "S1234567825000012",
                        "publicationDate": "2025-01-15",
                        "sourceTitle": "Example Journal",
                        "openAccess": True,
                    }
                ]
            }
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ScienceDirectAPIProvider(api_key="test-key", client=client)
    result = await provider.search_works(
        WorksSearchRequest(
            query="deep learning AND drug discovery",
            from_year=2024,
            to_year=2025,
            limit=2,
            provider="sciencedirect",
        )
    )
    await client.aclose()

    assert requests[0].headers["x-els-apikey"] == "test-key"
    assert result.metadata["provider"] == "sciencedirect"
    assert result.metadata["returned_count"] == 1
    assert result.data == [
        {
            "id": "sciencedirect:S1234567825000012",
            "doi": "https://doi.org/10.1016/j.example.2025.01.001",
            "title": "Deep learning for drug discovery",
            "publication_year": 2025,
            "publication_date": "2025-01-15",
            "type": "article",
            "cited_by_count": 0,
            "is_oa": True,
            "source": {
                "id": None,
                "name": "Example Journal",
                "type": "journal",
                "issn_l": None,
            },
            "topics": [],
            "provider_ids": {
                "pii": "S1234567825000012",
            },
        }
    ]


def test_sciencedirect_provider_get_work_returns_abstract_authors_and_references() -> None:
    asyncio.run(_test_sciencedirect_provider_get_work_returns_abstract_authors_and_references())


async def _test_sciencedirect_provider_get_work_returns_abstract_authors_and_references() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.url.path == "/content/article/doi/10.1016/j.example.2025.01.001"
        assert request.url.params["view"] == "META_ABS_REF"
        return _json_response(
            {
                "full-text-retrieval-response": {
                    "coredata": {
                        "dc:title": "Deep learning for drug discovery",
                        "prism:doi": "10.1016/j.example.2025.01.001",
                        "pii": "S1234567825000012",
                        "prism:coverDate": "2025-01-15",
                        "prism:publicationName": "Example Journal",
                        "prism:issn": "1234-5678",
                        "openaccess": "true",
                        "dc:description": "A compact abstract.",
                        "authors": {
                            "author": [
                                {"@auid": "7001", "ce:indexed-name": "Lovelace A", "orcid": "0000-0001"},
                                {"@auid": "7002", "ce:indexed-name": "Hopper G"},
                            ]
                        },
                        "bibliography": {
                            "reference": [
                                {"doi": "10.1016/j.ref.2020.01.001"},
                                {"@id": "ref-2"},
                            ]
                        },
                    }
                }
            }
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ScienceDirectAPIProvider(api_key="test-key", client=client)
    result = await provider.get_work(
        WorksGetRequest(
            identifier="10.1016/j.example.2025.01.001",
            provider="sciencedirect",
        )
    )
    await client.aclose()

    assert result.metadata == {"provider": "sciencedirect", "returned_count": 1}
    assert result.data["id"] == "sciencedirect:S1234567825000012"
    assert result.data["doi"] == "https://doi.org/10.1016/j.example.2025.01.001"
    assert result.data["abstract"] == "A compact abstract."
    assert result.data["source"] == {
        "id": None,
        "name": "Example Journal",
        "type": "journal",
        "issn_l": "1234-5678",
    }
    assert result.data["authors"] == [
        {
            "id": "7001",
            "display_name": "Lovelace A",
            "orcid": "0000-0001",
            "position": 1,
            "author_position": "",
            "is_corresponding": None,
            "institutions": [],
        },
        {
            "id": "7002",
            "display_name": "Hopper G",
            "orcid": None,
            "position": 2,
            "author_position": "",
            "is_corresponding": None,
            "institutions": [],
        },
    ]
    assert result.data["referenced_works"] == [
        "https://doi.org/10.1016/j.ref.2020.01.001",
        "ref-2",
    ]
    assert result.data["_raw"]["full-text-retrieval-response"]


def test_sciencedirect_provider_get_work_accepts_doi_url() -> None:
    asyncio.run(_test_sciencedirect_provider_get_work_accepts_doi_url())


async def _test_sciencedirect_provider_get_work_accepts_doi_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/content/article/doi/10.1016/j.example.2025.01.001"
        return _json_response(
            {
                "full-text-retrieval-response": {
                    "coredata": {
                        "dc:title": "DOI URL paper",
                        "prism:doi": "10.1016/j.example.2025.01.001",
                    }
                }
            }
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ScienceDirectAPIProvider(api_key="test-key", client=client)
    result = await provider.get_work(
        WorksGetRequest(
            identifier="https://doi.org/10.1016/j.example.2025.01.001",
            provider="sciencedirect",
        )
    )
    await client.aclose()

    assert result.data["doi"] == "https://doi.org/10.1016/j.example.2025.01.001"


def test_sciencedirect_provider_get_fulltext_xml() -> None:
    asyncio.run(_test_sciencedirect_provider_get_fulltext_xml())


async def _test_sciencedirect_provider_get_fulltext_xml() -> None:
    xml = "<article><body><section>Full text</section></body></article>"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/content/article/doi/10.1016/j.example.2025.01.001"
        assert request.headers["accept"] == "text/xml"
        return httpx.Response(200, text=xml, headers={"Content-Type": "text/xml"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ScienceDirectAPIProvider(api_key="test-key", client=client)
    result = await provider.get_fulltext(
        WorksFullTextRequest(
            identifier="10.1016/j.example.2025.01.001",
            provider="sciencedirect",
        )
    )
    await client.aclose()

    assert result.data == xml
    assert result.metadata == {
        "provider": "sciencedirect",
        "identifier": "10.1016/j.example.2025.01.001",
        "id_type": "doi",
        "format": "xml",
        "content_length": len(xml),
    }
