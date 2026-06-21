from __future__ import annotations

import asyncio
import json
from pathlib import Path

from metasci_universe.providers.base import ProviderResult
from metasci_universe.schemas.works import WorksFullTextRequest, WorksSearchRequest


def test_works_search_saves_sciencedirect_dataset(monkeypatch, tmp_path: Path) -> None:
    asyncio.run(_test_works_search_saves_sciencedirect_dataset(monkeypatch, tmp_path))


async def _test_works_search_saves_sciencedirect_dataset(monkeypatch, tmp_path: Path) -> None:
    from metasci_universe.api import works

    class FakeScienceDirectProvider:
        async def search_works(self, request: WorksSearchRequest) -> ProviderResult:
            assert request.provider == "sciencedirect"
            return ProviderResult(
                data=[
                    {
                        "id": "sciencedirect:S1",
                        "doi": "https://doi.org/10.1016/example",
                        "title": "ScienceDirect paper",
                        "publication_year": 2025,
                        "publication_date": "2025-01-01",
                        "type": "article",
                        "cited_by_count": 0,
                        "is_oa": True,
                        "source": {"id": None, "name": "Example Journal", "type": "journal", "issn_l": None},
                        "topics": [],
                        "provider_ids": {"pii": "S1"},
                    }
                ],
                metadata={"provider": "sciencedirect", "returned_count": 1},
                diagnostics=["diagnostic note"],
            )

        async def get_work(self, request):  # pragma: no cover - not used by this behavior
            raise AssertionError("unexpected get_work")

        async def search_authors(self, request):  # pragma: no cover - protocol filler
            raise AssertionError("unexpected search_authors")

        async def get_author(self, request):  # pragma: no cover - protocol filler
            raise AssertionError("unexpected get_author")

        async def authors_from_work(self, request):  # pragma: no cover - protocol filler
            raise AssertionError("unexpected authors_from_work")

    monkeypatch.setattr(works, "get_provider", lambda *args, **kwargs: FakeScienceDirectProvider())

    result = await works.search(
        "deep learning",
        provider="sciencedirect",
        limit=1,
        output_dir=str(tmp_path),
    )

    assert result.metadata["provider"] == "sciencedirect"
    data_file = Path(result.artifacts["data_file"])
    metadata_file = Path(result.artifacts["metadata_file"])
    assert data_file.name == "papers.json"
    assert json.loads(data_file.read_text(encoding="utf-8"))[0]["id"] == "sciencedirect:S1"
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert metadata["schema_name"] == "works"
    assert metadata["command"] == "works.search"
    assert metadata["input"]["provider"] == "sciencedirect"
    assert metadata["diagnostics"] == ["diagnostic note"]


def test_works_fulltext_saves_xml_artifact(monkeypatch, tmp_path: Path) -> None:
    asyncio.run(_test_works_fulltext_saves_xml_artifact(monkeypatch, tmp_path))


async def _test_works_fulltext_saves_xml_artifact(monkeypatch, tmp_path: Path) -> None:
    from metasci_universe.api import works

    xml = "<article><body>Full text</body></article>"

    class FakeScienceDirectProvider:
        async def get_fulltext(self, request: WorksFullTextRequest) -> ProviderResult:
            assert request.identifier == "10.1016/j.example.2025.01.001"
            assert request.provider == "sciencedirect"
            return ProviderResult(
                data=xml,
                metadata={
                    "provider": "sciencedirect",
                    "identifier": request.identifier,
                    "id_type": "doi",
                    "format": "xml",
                    "content_length": 40,
                },
                diagnostics=["full text access depends on Elsevier entitlements"],
            )

    monkeypatch.setattr(works, "get_provider", lambda *args, **kwargs: FakeScienceDirectProvider())

    result = await works.fulltext(
        "10.1016/j.example.2025.01.001",
        provider="sciencedirect",
        output_dir=str(tmp_path),
    )

    xml_file = Path(result.artifacts["xml_file"])
    metadata_file = Path(result.artifacts["metadata_file"])
    assert xml_file.name == "fulltext.xml"
    assert xml_file.read_text(encoding="utf-8") == "<article><body>Full text</body></article>"
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert metadata["schema_name"] == "fulltext"
    assert metadata["command"] == "works.fulltext"
    assert metadata["input"]["identifier"] == "10.1016/j.example.2025.01.001"
    assert metadata["metadata"]["provider"] == "sciencedirect"
    assert result.data == {
        "xml_file": str(xml_file),
        "content_length": len(xml),
    }


def test_works_fulltext_saves_springer_markdown_work_and_pdf(monkeypatch, tmp_path: Path) -> None:
    asyncio.run(_test_works_fulltext_saves_springer_markdown_work_and_pdf(monkeypatch, tmp_path))


async def _test_works_fulltext_saves_springer_markdown_work_and_pdf(monkeypatch, tmp_path: Path) -> None:
    from metasci_universe.api import works

    markdown = "# A Springer Article\n\nBody text.\n"
    work = {
        "id": "springer:10.1007/example",
        "doi": "https://doi.org/10.1007/example",
        "title": "A Springer Article",
        "authors": [],
        "referenced_works": [],
    }

    class FakeSpringerProvider:
        async def get_fulltext(self, request: WorksFullTextRequest) -> ProviderResult:
            assert request.provider == "springer"
            assert request.download_pdf is True
            return ProviderResult(
                data={
                    "markdown": markdown,
                    "work": work,
                    "pdf_bytes": b"%PDF-1.4 example",
                },
                metadata={
                    "provider": "springer",
                    "format": "markdown",
                    "content_length": len(markdown),
                },
            )

    monkeypatch.setattr(works, "get_provider", lambda *args, **kwargs: FakeSpringerProvider())

    result = await works.fulltext(
        "10.1007/example",
        provider="springer",
        download_pdf=True,
        output_dir=str(tmp_path),
    )

    markdown_file = Path(result.artifacts["markdown_file"])
    work_file = Path(result.artifacts["work_file"])
    pdf_file = Path(result.artifacts["pdf_file"])
    metadata_file = Path(result.artifacts["metadata_file"])

    assert markdown_file.name == "fulltext.md"
    assert markdown_file.read_text(encoding="utf-8") == markdown
    assert json.loads(work_file.read_text(encoding="utf-8"))["id"] == "springer:10.1007/example"
    assert pdf_file.name == "article.pdf"
    assert pdf_file.read_bytes() == b"%PDF-1.4 example"
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert metadata["schema_name"] == "fulltext"
    assert metadata["command"] == "works.fulltext"
    assert metadata["data_file"] == "fulltext.md"
    assert sorted(metadata["extra_files"]) == ["article.pdf", "work.json"]
    assert result.data == {
        "markdown_file": str(markdown_file),
        "work_file": str(work_file),
        "content_length": len(markdown),
        "pdf_file": str(pdf_file),
    }
