from __future__ import annotations

import asyncio

from metasci_universe.api.citations import CitationGraphService
from metasci_universe.providers.openalex_api import OpenAlexAPIProvider
from metasci_universe.providers.semantic_scholar_api import SemanticScholarAPIProvider
from metasci_universe.schemas.citations import CitationLookupRequest, CitationResolveRequest


class FakeOpenAlex:
    def __init__(self) -> None:
        self.name = "openalex"

    def _work_identifier(self, identifier: str) -> str:
        if identifier.startswith("https://openalex.org/"):
            return identifier.replace("https://openalex.org/", "")
        return identifier

    def _compact_openalex_id(self, value):
        if isinstance(value, str):
            return value.replace("https://openalex.org/", "")
        return value

    async def _get_json(self, endpoint: str, *, params: dict | None = None) -> dict:
        if endpoint == "/works/W1":
            return {
                "id": "https://openalex.org/W1",
                "doi": "https://doi.org/10.123/seed",
                "title": "Seed Paper",
                "publication_year": 2020,
                "cited_by_count": 10,
                "referenced_works": ["https://openalex.org/W2"],
                "primary_location": {"source": {"display_name": "Venue"}},
                "authorships": [{"author": {"display_name": "Ada"}}],
            }
        if endpoint == "/works" and (params or {}).get("filter") == "openalex:https://openalex.org/W2":
            return {
                "meta": {"count": 1},
                "results": [
                    {
                        "id": "https://openalex.org/W2",
                        "doi": "https://doi.org/10.123/ref",
                        "title": "Reference Paper",
                        "publication_year": 2019,
                        "cited_by_count": 4,
                        "primary_location": {"source": {"display_name": "Ref Venue"}},
                    }
                ],
            }
        raise AssertionError(f"unexpected OpenAlex call {endpoint} {params}")

    async def _fetch_cursor(self, endpoint: str, *, params: dict, limit: int):
        if endpoint == "/works" and params.get("filter") == "cites:https://openalex.org/W1":
            return (
                [
                    {
                        "id": "https://openalex.org/W3",
                        "doi": "https://doi.org/10.123/citing",
                        "title": "Citing Paper",
                        "publication_year": 2021,
                        "cited_by_count": 3,
                        "primary_location": {"source": {"display_name": "Citing Venue"}},
                    }
                ],
                {"count": 1},
            )
        raise AssertionError(f"unexpected OpenAlex cursor call {endpoint} {params}")


class FakeOpenAlexArxiv(FakeOpenAlex):
    async def _get_json(self, endpoint: str, *, params: dict | None = None) -> dict:
        if endpoint == "/works":
            assert (params or {}).get("search") == "Arxiv Seed Paper"
            return {
                "meta": {"count": 1},
                "results": [
                    {
                        "id": "https://openalex.org/W4",
                        "doi": "https://doi.org/10.123/arxiv-seed",
                        "title": "Arxiv Seed Paper",
                        "publication_year": 2024,
                        "cited_by_count": 2,
                        "referenced_works": [],
                        "primary_location": {"source": {"display_name": "arXiv"}},
                        "authorships": [{"author": {"display_name": "Ada"}}],
                    }
                ],
            }
        raise AssertionError(f"unexpected OpenAlex call {endpoint} {params}")


class FakeOpenAlexOpenCitations:
    def __init__(self) -> None:
        self.name = "openalex"

    def _work_identifier(self, identifier: str) -> str:
        return identifier.replace("https://openalex.org/", "")

    async def _get_json(self, endpoint: str, *, params: dict | None = None) -> dict:
        if endpoint == "/works/WOC":
            return {
                "id": "https://openalex.org/WOC",
                "doi": "https://doi.org/10.123/seed",
                "title": "OpenCitations Seed",
                "publication_year": 2022,
                "cited_by_count": 0,
                "referenced_works": [],
                "primary_location": {"source": {"display_name": "Venue"}},
                "authorships": [{"author": {"display_name": "Ada"}}],
            }
        if endpoint == "/works" and (params or {}).get("filter") == "openalex:https://openalex.org/WOCREF":
            return {
                "meta": {"count": 1},
                "results": [
                    {
                        "id": "https://openalex.org/WOCREF",
                        "doi": "https://doi.org/10.123/ref",
                        "title": "OpenCitations Reference",
                        "publication_year": 2021,
                        "cited_by_count": 5,
                        "primary_location": {"source": {"display_name": "Ref Venue"}},
                    }
                ],
            }
        if endpoint == "/works" and (params or {}).get("filter") == "doi:10.123/cit":
            return {
                "meta": {"count": 1},
                "results": [
                    {
                        "id": "https://openalex.org/WOCCIT",
                        "doi": "https://doi.org/10.123/cit",
                        "title": "OpenCitations Citing",
                        "publication_year": 2023,
                        "cited_by_count": 1,
                        "primary_location": {"source": {"display_name": "Citing Venue"}},
                    }
                ],
            }
        raise AssertionError(f"unexpected OpenAlex call {endpoint} {params}")

    async def _fetch_cursor(self, endpoint: str, *, params: dict, limit: int):
        if endpoint == "/works" and params.get("filter") == "cites:https://openalex.org/WOC":
            return ([], {"count": 0})
        raise AssertionError(f"unexpected OpenAlex cursor call {endpoint} {params}")


class FakeOpenCitationsEmpty:
    async def references(self, identifier: str) -> list[dict]:
        return []

    async def citations(self, identifier: str) -> list[dict]:
        return []


class FakeOpenCitationsWithEdges:
    async def references(self, identifier: str) -> list[dict]:
        assert identifier == "doi:10.123/seed"
        return [
            {
                "oci": "seed-ref",
                "citing": "doi:10.123/seed openalex:WOC",
                "cited": "doi:10.123/ref openalex:WOCREF",
                "creation": "2022",
            }
        ]

    async def citations(self, identifier: str) -> list[dict]:
        assert identifier == "doi:10.123/seed"
        return [
            {
                "oci": "cit-seed",
                "citing": "doi:10.123/cit",
                "cited": "doi:10.123/seed openalex:WOC",
                "creation": "2023",
            }
        ]


class FakeS2:
    def __init__(self) -> None:
        self.name = "semantic_scholar"
        self.reference_calls = 0
        self.citation_calls = 0

    async def get_paper(self, identifier: str) -> dict:
        assert identifier == "DOI:10.123/seed"
        return {
            "paperId": "S1",
            "corpusId": 101,
            "title": "Seed Paper",
            "year": 2020,
            "externalIds": {"DOI": "10.123/seed", "OpenAlex": "W1"},
            "citationCount": 10,
            "referenceCount": 1,
        }

    async def search_paper(self, title: str, *, limit: int = 3) -> list[dict]:
        return []

    async def references(self, paper_id: str, *, limit: int = 100) -> list[dict]:
        self.reference_calls += 1
        assert paper_id == "S1"
        return [
            {
                "paperId": "S2",
                "corpusId": 102,
                "title": "Reference Paper",
                "year": 2019,
                "externalIds": {"DOI": "10.123/ref"},
                "citationCount": 4,
            }
        ]

    async def citations(self, paper_id: str, *, limit: int = 100) -> list[dict]:
        self.citation_calls += 1
        assert paper_id == "S1"
        return [
            {
                "paperId": "S3",
                "corpusId": 103,
                "title": "Citing Paper",
                "year": 2021,
                "externalIds": {"DOI": "10.123/citing"},
                "citationCount": 3,
            }
        ]


class FakeS2NoCalls(FakeS2):
    async def get_paper(self, identifier: str) -> dict:
        raise AssertionError("Semantic Scholar should not be called")

    async def search_paper(self, title: str, *, limit: int = 3) -> list[dict]:
        raise AssertionError("Semantic Scholar should not be called")

    async def references(self, paper_id: str, *, limit: int = 100) -> list[dict]:
        raise AssertionError("Semantic Scholar should not be called")

    async def citations(self, paper_id: str, *, limit: int = 100) -> list[dict]:
        raise AssertionError("Semantic Scholar should not be called")


def test_citation_lookup_merges_openalex_and_s2_edges() -> None:
    asyncio.run(_test_citation_lookup_merges_openalex_and_s2_edges())


async def _test_citation_lookup_merges_openalex_and_s2_edges() -> None:
    s2 = FakeS2()
    service = CitationGraphService(
        openalex=FakeOpenAlex(),
        opencitations=FakeOpenCitationsEmpty(),
        semantic_scholar=s2,
    )  # type: ignore[arg-type]
    result = await service.lookup(CitationLookupRequest(openalex_id="W1", provider="auto", limit=10))

    assert result.command == "citations.lookup"
    assert result.data["resolved_identity"]["openalex_id"] == "W1"
    assert result.data["resolved_identity"]["s2_id"] == "S1"
    assert len(result.data["references"]) == 1
    assert len(result.data["citations"]) == 1
    assert result.data["references"][0]["doi"] == "10.123/ref"
    assert result.data["citations"][0]["doi"] == "10.123/citing"
    assert result.data["provider_counts"]["references"] == {
        "openalex": 1,
        "opencitations": 0,
        "semantic_scholar": 1,
        "merged": 1,
    }
    assert result.data["provider_counts"]["citations"] == {
        "openalex": 1,
        "opencitations": 0,
        "semantic_scholar": 1,
        "merged": 1,
    }
    assert s2.reference_calls == 1
    assert s2.citation_calls == 1


def test_citation_lookup_uses_opencitations_before_s2() -> None:
    asyncio.run(_test_citation_lookup_uses_opencitations_before_s2())


async def _test_citation_lookup_uses_opencitations_before_s2() -> None:
    service = CitationGraphService(
        openalex=FakeOpenAlexOpenCitations(),
        opencitations=FakeOpenCitationsWithEdges(),
        semantic_scholar=FakeS2NoCalls(),
    )  # type: ignore[arg-type]
    result = await service.lookup(CitationLookupRequest(openalex_id="WOC", provider="auto", limit=10))

    assert len(result.data["references"]) == 1
    assert len(result.data["citations"]) == 1
    assert result.data["references"][0]["title"] == "OpenCitations Reference"
    assert result.data["citations"][0]["title"] == "OpenCitations Citing"
    assert result.data["provider_counts"]["references"] == {
        "openalex": 0,
        "opencitations": 1,
        "semantic_scholar": 0,
        "merged": 1,
    }
    assert result.data["provider_counts"]["citations"] == {
        "openalex": 0,
        "opencitations": 1,
        "semantic_scholar": 0,
        "merged": 1,
    }


def test_citation_resolve_openalex_only_with_mock_http() -> None:
    asyncio.run(_test_citation_resolve_openalex_only_with_mock_http())


async def _test_citation_resolve_openalex_only_with_mock_http() -> None:
    provider = OpenAlexAPIProvider()
    provider._get_json = FakeOpenAlex()._get_json  # type: ignore[method-assign]
    service = CitationGraphService(openalex=provider, semantic_scholar=FakeS2())  # type: ignore[arg-type]
    identity, diagnostics, metadata = await service.resolve(CitationResolveRequest(openalex_id="W1", provider="openalex"))

    assert diagnostics == []
    assert metadata["resolved_from"] == ["openalex"]
    assert identity
    assert identity["title"] == "Seed Paper"
    assert identity["referenced_works"] == ["W2"]


def test_citation_resolve_arxiv_uses_title_lookup_not_openalex_url() -> None:
    asyncio.run(_test_citation_resolve_arxiv_uses_title_lookup_not_openalex_url())


async def _test_citation_resolve_arxiv_uses_title_lookup_not_openalex_url() -> None:
    service = CitationGraphService(openalex=FakeOpenAlexArxiv(), semantic_scholar=FakeS2())  # type: ignore[arg-type]

    async def fake_fetch_arxiv_title(arxiv_id: str, diagnostics: list[str]) -> str | None:
        assert arxiv_id == "2410.12462"
        return "Arxiv Seed Paper"

    service._fetch_arxiv_title = fake_fetch_arxiv_title  # type: ignore[method-assign]
    identity, diagnostics, metadata = await service.resolve(CitationResolveRequest(arxiv_id="2410.12462", provider="openalex"))

    assert metadata["resolved_from"] == ["openalex"]
    assert identity
    assert identity["openalex_id"] == "W4"
    assert identity["title"] == "Arxiv Seed Paper"
    assert "OpenAlex arXiv lookup used arXiv title metadata." in diagnostics


def test_semantic_scholar_provider_sends_api_key(monkeypatch) -> None:
    asyncio.run(_test_semantic_scholar_provider_sends_api_key(monkeypatch))


async def _test_semantic_scholar_provider_sends_api_key(monkeypatch) -> None:
    monkeypatch.setenv("S2_API_KEY", "test-key")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"paperId": "S1"}

    class FakeClient:
        def __init__(self) -> None:
            self.headers = None

        async def get(self, url: str, *, params: dict, headers: dict | None):
            self.headers = headers
            return FakeResponse()

    client = FakeClient()
    provider = SemanticScholarAPIProvider(client=client)  # type: ignore[arg-type]
    await provider.get_paper("10.123/seed")

    assert client.headers == {"x-api-key": "test-key"}
