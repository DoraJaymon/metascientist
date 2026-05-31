from __future__ import annotations

import asyncio

import httpx

from metasci_universe.providers.dblp_api import DblpAPIProvider
from metasci_universe.providers.acl_anthology import ACLAnthologyProvider
from metasci_universe.providers.cvf_openaccess import CVFOpenAccessProvider
from metasci_universe.providers.openreview_api import OpenReviewAPIProvider
from metasci_universe.providers.pmlr import PMLRProvider
from metasci_universe.schemas.conferences import ConferencePapersRequest


def _json_response(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload)


def _html_response(payload: str) -> httpx.Response:
    return httpx.Response(200, text=payload)


def test_openreview_provider_fetches_and_normalizes_accepted_papers() -> None:
    asyncio.run(_test_openreview_provider_fetches_and_normalizes_accepted_papers())


async def _test_openreview_provider_fetches_and_normalizes_accepted_papers() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/notes"
        return _json_response(
            {
                "count": 1,
                "notes": [
                    {
                        "id": "abc123",
                        "forum": "abc123",
                        "number": 7,
                        "invitation": "ICLR.cc/2024/Conference/-/Submission",
                        "pdate": 1705363200000,
                        "content": {
                            "title": {"value": "A Useful Representation Learner"},
                            "authors": {"value": ["Ada Lovelace", "Alan Turing"]},
                            "authorids": {"value": ["~Ada_Lovelace1", "~Alan_Turing1"]},
                            "abstract": {"value": "We learn useful representations."},
                            "pdf": {"value": "/pdf?id=abc123"},
                            "venue": {"value": "ICLR 2024 poster"},
                            "venueid": {"value": "ICLR.cc/2024/Conference"},
                            "presentation_type": {"value": "poster"},
                            "keywords": {"value": ["representation learning"]},
                        },
                    }
                ],
            }
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenReviewAPIProvider(client=client)
    result = await provider.search_conference_papers(
        ConferencePapersRequest(venue="iclr", year=2024, source="openreview", limit=10)
    )
    await client.aclose()

    assert result.metadata["venue_id"] == "ICLR.cc/2024/Conference"
    assert result.metadata["spider"] == "openreview-api-v2-notes"
    assert result.data[0]["id"] == "openreview:abc123"
    assert result.data[0]["source"]["name"] == "ICLR 2024 poster"
    assert result.data[0]["authors"][1]["display_name"] == "Alan Turing"
    assert result.data[0]["pdf_url"] == "https://openreview.net/pdf?id=abc123"
    assert result.data[0]["provenance"][0]["spider"] == "openreview-api-v2-notes"
    assert requests[0].url.params["content.venueid"] == "ICLR.cc/2024/Conference"


def test_dblp_provider_fetches_and_normalizes_conference_papers() -> None:
    asyncio.run(_test_dblp_provider_fetches_and_normalizes_conference_papers())


async def _test_dblp_provider_fetches_and_normalizes_conference_papers() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _json_response(
            {
                "result": {
                    "hits": {
                        "@total": "1",
                        "hit": [
                            {
                                "info": {
                                    "key": "conf/cvpr/Example24",
                                    "type": "Conference and Workshop Papers",
                                    "title": "A Vision Paper",
                                    "venue": "CVPR",
                                    "year": "2024",
                                    "doi": "10.1109/CVPR.example",
                                    "url": "https://dblp.org/rec/conf/cvpr/Example24",
                                    "ee": "https://doi.org/10.1109/CVPR.example",
                                    "authors": {
                                        "author": [
                                            {"text": "First Author", "@pid": "1/1"},
                                            {"text": "Second Author", "@pid": "2/2"},
                                        ]
                                    },
                                }
                            }
                        ],
                    }
                }
            }
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = DblpAPIProvider(client=client)
    result = await provider.search_conference_papers(ConferencePapersRequest(venue="cvpr", year=2024, source="dblp"))
    await client.aclose()

    assert result.metadata["query"] == "venue:CVPR: year:2024:"
    assert result.metadata["spider"] == "dblp-publication-search-api"
    assert result.data[0]["id"] == "dblp:conf/cvpr/Example24"
    assert result.data[0]["doi"] == "https://doi.org/10.1109/CVPR.example"
    assert result.data[0]["authors"][0]["id"] == "1/1"
    assert result.data[0]["provenance"][0]["spider"] == "dblp-publication-search-api"
    assert requests[0].url.params["format"] == "json"


def test_acl_provider_fetches_and_normalizes_proceedings_papers() -> None:
    asyncio.run(_test_acl_provider_fetches_and_normalizes_proceedings_papers())


async def _test_acl_provider_fetches_and_normalizes_proceedings_papers() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/venues/acl/":
            return _html_response('<a href="/2024.acl-long/">ACL 2024 Long Papers</a>')
        return _html_response(
            """
            <section id="main">
              <span class="d-block"><strong><a href="/2024.acl-long.1/">A Language Paper</a></strong></span>
              <span class="d-block"><strong><a href="/2024.acl-long.2/">Another Language Paper</a></strong></span>
            </section>
            """
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ACLAnthologyProvider(client=client)
    result = await provider.search_conference_papers(ConferencePapersRequest(venue="acl", year=2024, source="acl"))
    await client.aclose()

    assert requests[0].url.path == "/venues/acl/"
    assert result.metadata["provider"] == "acl"
    assert result.metadata["filtered_total"] == 2
    assert result.data[0]["id"] == "acl:2024.acl-long.1"
    assert result.data[0]["pdf_url"] == "https://aclanthology.org/2024.acl-long.1.pdf"
    assert result.data[0]["provenance"][0]["spider"] == "acl-anthology-proceedings-html"


def test_cvf_provider_fetches_and_normalizes_listing_papers() -> None:
    asyncio.run(_test_cvf_provider_fetches_and_normalizes_listing_papers())


async def _test_cvf_provider_fetches_and_normalizes_listing_papers() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _html_response(
            """
            <dl>
              <dt class="ptitle"><a href="html/Example_Paper.html">A Vision Paper</a></dt>
              <dd><a href="papers/Example_Paper.pdf">pdf</a></dd>
              <dt class="ptitle"><a href="html/Second_Paper.html">A Second Vision Paper</a></dt>
              <dd><a href="papers/Second_Paper.pdf">pdf</a></dd>
            </dl>
            """
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = CVFOpenAccessProvider(client=client)
    result = await provider.search_conference_papers(ConferencePapersRequest(venue="cvpr", year=2024, source="cvf"))
    await client.aclose()

    assert requests[0].url.path == "/CVPR2024"
    assert requests[0].url.params["day"] == "all"
    assert result.metadata["provider"] == "cvf"
    assert result.metadata["filtered_total"] == 2
    assert result.data[0]["id"] == "cvf:Example_Paper"
    assert result.data[0]["pdf_url"] == "https://openaccess.thecvf.com/papers/Example_Paper.pdf"
    assert result.data[0]["provenance"][0]["spider"] == "cvf-openaccess-html"


def test_pmlr_provider_fetches_and_normalizes_volume_papers() -> None:
    asyncio.run(_test_pmlr_provider_fetches_and_normalizes_volume_papers())


async def _test_pmlr_provider_fetches_and_normalizes_volume_papers() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/":
            return _html_response('<a href="/v235/">Proceedings of AISTATS 2024</a>')
        return _html_response(
            """
            <div class="paper">
              <p class="title"><a href="/v235/example24a.html">A Learning Paper</a></p>
              <p class="title"><a href="/v235/example24b.html">Another Learning Paper</a></p>
            </div>
            """
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = PMLRProvider(client=client)
    result = await provider.search_conference_papers(ConferencePapersRequest(venue="aistats", year=2024, source="pmlr"))
    await client.aclose()

    assert requests[0].url.path == "/"
    assert result.metadata["provider"] == "pmlr"
    assert result.metadata["filtered_total"] == 2
    assert result.data[0]["id"] == "pmlr:example24a"
    assert result.data[0]["pdf_url"] == "https://proceedings.mlr.press/v235/example24a.pdf"
    assert result.data[0]["provenance"][0]["spider"] == "pmlr-volume-html"
