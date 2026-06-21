from __future__ import annotations

import asyncio

import httpx
import pytest

from metasci_universe.providers.springer import SpringerProvider, normalize_doi
from metasci_universe.schemas.authors import WorkAuthorsRequest
from metasci_universe.schemas.works import WorksFullTextRequest, WorksGetRequest, WorksSearchRequest


ARTICLE_HTML = """
<!doctype html>
<html>
  <head>
    <meta name="citation_title" content="A Springer Article">
    <meta name="citation_doi" content="10.1007/s10796-025-10632-z">
    <meta name="citation_journal_title" content="Example Journal">
    <meta name="citation_publication_date" content="2025/04/18">
    <meta name="citation_author" content="Ada Lovelace">
    <meta name="citation_author" content="Grace Hopper">
    <meta name="citation_author_institution" content="Analytical Engine Lab">
    <meta name="citation_keywords" content="science mapping; agents">
    <meta name="citation_pdf_url" content="/content/pdf/10.1007/s10796-025-10632-z.pdf">
    <meta name="description" content="A compact Springer abstract.">
    <meta name="citation_volume" content="42">
    <meta name="citation_issue" content="3">
  </head>
  <body>
    <article>
      <span class="c-article-identifiers__type">Research Article</span>
      <div class="c-article-body">
        <section class="c-article-section" data-title="Introduction">
          <h2>1 Introduction</h2>
          <p>Springer body paragraph.</p>
          <section class="c-article-section" data-title="Method">
            <h3>1.1 Method</h3>
            <p>Nested method paragraph.</p>
          </section>
        </section>
      </div>
      <section data-title="References">
        <ol class="c-article-references">
          <li>Reference One. doi:10.1007/ref-one</li>
          <li>Reference Two without DOI.</li>
        </ol>
      </section>
    </article>
  </body>
</html>
"""


def _provider_for(handler) -> tuple[SpringerProvider, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SpringerProvider(client=client, polite_delay=(0.0, 0.0)), client


def test_springer_normalize_doi_accepts_variants() -> None:
    assert normalize_doi("doi:10.1007/example") == "10.1007/example"
    assert normalize_doi("https://doi.org/10.1007/example") == "10.1007/example"
    assert normalize_doi("10.1007/example.") == "10.1007/example"


def test_springer_provider_get_work_normalizes_article() -> None:
    asyncio.run(_test_springer_provider_get_work_normalizes_article())


async def _test_springer_provider_get_work_normalizes_article() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/article/10.1007/s10796-025-10632-z"
        return httpx.Response(200, text=ARTICLE_HTML, headers={"Content-Type": "text/html"})

    provider, client = _provider_for(handler)
    result = await provider.get_work(
        WorksGetRequest(
            identifier="https://link.springer.com/article/10.1007/s10796-025-10632-z",
            provider="springer",
        )
    )
    await client.aclose()

    assert result.metadata["provider"] == "springer"
    assert result.metadata["reference_count"] == 2
    assert result.data["id"] == "springer:10.1007/s10796-025-10632-z"
    assert result.data["doi"] == "https://doi.org/10.1007/s10796-025-10632-z"
    assert result.data["publication_year"] == 2025
    assert result.data["source"]["name"] == "Example Journal"
    assert result.data["authors"][0]["display_name"] == "Ada Lovelace"
    assert result.data["authors"][0]["position"] == 1
    assert result.data["referenced_works"] == ["https://doi.org/10.1007/ref-one"]
    assert result.data["_raw"]["authors_raw"] == ["Ada Lovelace", "Grace Hopper"]
    assert result.data["_raw"]["references"][1] == "Reference Two without DOI."
    assert result.data["pdf_url"].endswith(".pdf")


def test_springer_provider_follows_article_authorization_redirect() -> None:
    asyncio.run(_test_springer_provider_follows_article_authorization_redirect())


async def _test_springer_provider_follows_article_authorization_redirect() -> None:
    article_seen = False
    idp_seen = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal article_seen, idp_seen
        if request.url.host == "link.springer.com" and not article_seen:
            article_seen = True
            return httpx.Response(
                303,
                request=request,
                headers={
                    "Location": (
                        "https://idp.springer.com/authorize?response_type=cookie&client_id=springerlink"
                        "&redirect_uri=https%3A%2F%2Flink.springer.com%2Farticle%2F10.1007%2Fs10796-025-10632-z"
                    )
                },
            )
        if request.url.host == "idp.springer.com":
            idp_seen = True
            return httpx.Response(
                303,
                request=request,
                headers={"Location": "https://link.springer.com/article/10.1007/s10796-025-10632-z"},
            )
        return httpx.Response(200, text=ARTICLE_HTML, headers={"Content-Type": "text/html"})

    provider, client = _provider_for(handler)
    result = await provider.get_work(
        WorksGetRequest(
            identifier="https://link.springer.com/article/10.1007/s10796-025-10632-z",
            provider="springer",
        )
    )
    await client.aclose()

    assert article_seen is True
    assert idp_seen is True
    assert result.data["title"] == "A Springer Article"


def test_springer_provider_get_fulltext_markdown_and_pdf() -> None:
    asyncio.run(_test_springer_provider_get_fulltext_markdown_and_pdf())


async def _test_springer_provider_get_fulltext_markdown_and_pdf() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "doi.org":
            return httpx.Response(
                302,
                text="",
                request=request,
                headers={"Location": "https://link.springer.com/article/10.1007/s10796-025-10632-z"},
            )
        if request.url.path.endswith(".pdf"):
            return httpx.Response(200, content=b"%PDF-1.4 example")
        return httpx.Response(200, text=ARTICLE_HTML, headers={"Content-Type": "text/html"})

    provider, client = _provider_for(handler)
    result = await provider.get_fulltext(
        WorksFullTextRequest(
            identifier="10.1007/s10796-025-10632-z",
            provider="springer",
            download_pdf=True,
        )
    )
    await client.aclose()

    assert requests[0].url.host == "doi.org"
    assert requests[1].url.host == "link.springer.com"
    assert requests[2].url.host == "link.springer.com"
    assert requests[3].url.path.endswith(".pdf")
    assert result.metadata["format"] == "markdown"
    assert result.metadata["pdf_downloaded"] is True
    assert result.data["pdf_bytes"] == b"%PDF-1.4 example"
    assert "# A Springer Article" in result.data["markdown"]
    assert "## Abstract" in result.data["markdown"]
    assert "Springer body paragraph." in result.data["markdown"]
    assert result.data["work"]["title"] == "A Springer Article"


def test_springer_provider_authors_from_work() -> None:
    asyncio.run(_test_springer_provider_authors_from_work())


async def _test_springer_provider_authors_from_work() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=ARTICLE_HTML, headers={"Content-Type": "text/html"})

    provider, client = _provider_for(handler)
    result = await provider.authors_from_work(
        WorkAuthorsRequest(
            identifier="https://link.springer.com/article/10.1007/s10796-025-10632-z",
            provider="springer",
            all_authors=True,
        )
    )
    await client.aclose()

    assert result.metadata["provider"] == "springer"
    assert result.metadata["total_authors"] == 2
    assert [author["display_name"] for author in result.data] == ["Ada Lovelace", "Grace Hopper"]


def test_springer_provider_search_is_not_supported() -> None:
    provider = SpringerProvider(polite_delay=(0.0, 0.0))
    with pytest.raises(NotImplementedError, match="DOI/URL-level retrieval only"):
        asyncio.run(provider.search_works(WorksSearchRequest(query="science", provider="springer")))
