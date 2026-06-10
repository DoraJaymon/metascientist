from __future__ import annotations

import asyncio

from metasci_universe.api.citations import CitationGraphService
from metasci_universe.providers.openalex_api import OpenAlexAPIProvider
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


def test_citation_lookup_merges_openalex_and_s2_edges() -> None:
    asyncio.run(_test_citation_lookup_merges_openalex_and_s2_edges())


async def _test_citation_lookup_merges_openalex_and_s2_edges() -> None:
    s2 = FakeS2()
    service = CitationGraphService(openalex=FakeOpenAlex(), semantic_scholar=s2)  # type: ignore[arg-type]
    result = await service.lookup(CitationLookupRequest(openalex_id="W1", provider="auto", limit=10))

    assert result.command == "citations.lookup"
    assert result.data["resolved_identity"]["openalex_id"] == "W1"
    assert result.data["resolved_identity"]["s2_id"] == "S1"
    assert len(result.data["references"]) == 1
    assert len(result.data["citations"]) == 1
    assert result.data["references"][0]["doi"] == "10.123/ref"
    assert result.data["citations"][0]["doi"] == "10.123/citing"
    assert result.data["provider_counts"]["references"] == {"openalex": 1, "semantic_scholar": 1, "merged": 1}
    assert result.data["provider_counts"]["citations"] == {"openalex": 1, "semantic_scholar": 1, "merged": 1}
    assert s2.reference_calls == 1
    assert s2.citation_calls == 1


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
