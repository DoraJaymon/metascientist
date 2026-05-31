from __future__ import annotations

import pytest
from pydantic import ValidationError

from metasci_universe.schemas.authors import WorkAuthorsRequest
from metasci_universe.schemas.conferences import ConferencePapersRequest
from metasci_universe.schemas.embeddings import EmbedWorksRequest
from metasci_universe.schemas.works import WorksSearchRequest


def test_works_search_requires_constraint() -> None:
    with pytest.raises(ValidationError):
        WorksSearchRequest()


def test_works_search_rejects_inverted_years() -> None:
    with pytest.raises(ValidationError):
        WorksSearchRequest(query="science", from_year=2025, to_year=2020)


def test_works_search_rejects_inverted_citation_bounds() -> None:
    with pytest.raises(ValidationError):
        WorksSearchRequest(query="science", min_cited_by_count=100, max_cited_by_count=50)


def test_works_search_deduplicates_include() -> None:
    request = WorksSearchRequest(query="science", include=["authors", "authors", "references"])
    assert request.include == ["authors", "references"]


def test_works_search_normalizes_new_filters() -> None:
    request = WorksSearchRequest(query="science", country_code=" us ", work_type=" Article ")
    assert request.country_code == "US"
    assert request.work_type == "article"


def test_work_authors_rejects_all_authors_full() -> None:
    with pytest.raises(ValidationError):
        WorkAuthorsRequest(identifier="10.123/example", all_authors=True, detail_level="full")


def test_conference_papers_normalizes_venue_and_query() -> None:
    request = ConferencePapersRequest(
        venue=" ICLR ",
        year=2024,
        query="  representation learning  ",
        source_collection_id=" v235 ",
    )
    assert request.venue == "iclr"
    assert request.query == "representation learning"
    assert request.source_collection_id == "v235"


def test_conference_papers_accepts_new_conference_sources() -> None:
    assert ConferencePapersRequest(venue="acl", year=2024, source="acl").source == "acl"
    assert ConferencePapersRequest(venue="cvpr", year=2024, source="cvf").source == "cvf"
    assert ConferencePapersRequest(venue="aistats", year=2024, source="pmlr").source == "pmlr"


def test_embed_works_rejects_api_settings_for_local_backend() -> None:
    with pytest.raises(ValidationError):
        EmbedWorksRequest(dataset_path="papers.json", backend="spacy", api_base_url="https://example.test/v1")
