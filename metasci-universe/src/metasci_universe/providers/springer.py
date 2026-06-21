"""Springer single-article provider backed by public article pages."""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Sequence
from urllib.parse import quote, urljoin

import httpx
from lxml import etree, html

from metasci_universe.providers.base import ProviderResult
from metasci_universe.schemas.authors import AuthorProfileRequest, AuthorSearchRequest, WorkAuthorsRequest
from metasci_universe.schemas.works import WorksFullTextRequest, WorksGetRequest, WorksSearchRequest


BASE_URL = "https://link.springer.com"
DOI_RESOLVER_URL = "https://doi.org"
DEFAULT_TIMEOUT = 30.0
DOI_RE = re.compile(r"\b10\.\d{4,9}/\S+", re.I)

BLOCK_TAGS = {
    "p",
    "li",
    "figcaption",
    "caption",
    "blockquote",
}

SKIP_SECTION_TITLES = {
    "abstract",
    "references",
    "reference",
    "author information",
    "authors and affiliations",
    "affiliations",
    "ethics declarations",
    "rights and permissions",
    "additional information",
    "publisher's note",
    "supplementary information",
    "about this article",
}

SKIP_HEADING_TITLES = {
    "explore related subjects",
    "topics",
    "article metrics",
    "about this article",
    "share this article",
    "recommendations",
}

SKIP_CLASS_PATTERNS = (
    "c-article-references",
    "c-article-metrics",
    "c-article-author-affiliation",
    "c-article-info-details",
    "c-article-share-box",
    "c-article-recommendations",
    "u-hide",
)


class SpringerProvider:
    """Provider for DOI/URL-level Springer article retrieval."""

    name = "springer"

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        doi_resolver_url: str = DOI_RESOLVER_URL,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.AsyncClient | None = None,
        polite_delay: tuple[float, float] = (1.0, 3.0),
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.doi_resolver_url = doi_resolver_url.rstrip("/")
        self.timeout = timeout
        self._client = client
        self.polite_delay = polite_delay
        self.parser = SpringerArticleParser(base_url=self.base_url)

    async def search_works(self, request: WorksSearchRequest) -> ProviderResult:
        raise NotImplementedError("Springer provider supports DOI/URL-level retrieval only.")

    async def get_work(self, request: WorksGetRequest) -> ProviderResult:
        data = await self._scrape_article(request.identifier, include_fulltext=False)
        work = self._normalize_work(data)
        return ProviderResult(
            data=work,
            metadata={
                "provider": self.name,
                "returned_count": 1,
                "reference_count": data.get("reference_num", 0),
                "source_url": data.get("source_url"),
            },
        )

    async def get_fulltext(self, request: WorksFullTextRequest) -> ProviderResult:
        data = await self._scrape_article(request.identifier, include_fulltext=True)
        work = self._normalize_work(data)
        markdown = self.parser.render_article_markdown(data)

        diagnostics: list[str] = []
        pdf_bytes: bytes | None = None
        if request.download_pdf:
            pdf_link = data.get("pdf_link")
            if pdf_link:
                pdf_bytes = await self._download_pdf(pdf_link)
            else:
                diagnostics.append("Springer page did not expose a PDF link.")

        if not data.get("full_text_markdown"):
            diagnostics.append("Springer page did not expose article body text in the HTML response.")

        return ProviderResult(
            data={
                "markdown": markdown,
                "work": work,
                "pdf_bytes": pdf_bytes,
            },
            metadata={
                "provider": self.name,
                "identifier": request.identifier,
                "format": "markdown",
                "content_length": len(markdown),
                "reference_count": data.get("reference_num", 0),
                "source_url": data.get("source_url"),
                "pdf_downloaded": pdf_bytes is not None,
            },
            diagnostics=diagnostics,
        )

    async def search_authors(self, request: AuthorSearchRequest) -> ProviderResult:
        raise NotImplementedError("Springer provider does not support authors.search.")

    async def get_author(self, request: AuthorProfileRequest) -> ProviderResult:
        raise NotImplementedError("Springer provider does not support authors.profile.")

    async def authors_from_work(self, request: WorkAuthorsRequest) -> ProviderResult:
        article = await self.get_work(WorksGetRequest(identifier=request.identifier, provider="springer"))
        authors = article.data.get("authors") if isinstance(article.data, dict) else []
        if not isinstance(authors, list):
            authors = []

        diagnostics: list[str] = []
        data: Any
        if request.all_authors:
            data = authors
        elif request.author_position > len(authors):
            data = None
            diagnostics.append(
                f"Requested author_position={request.author_position}, but the work has {len(authors)} authors."
            )
        else:
            data = authors[request.author_position - 1]

        return ProviderResult(
            data=data,
            metadata={
                "provider": self.name,
                "returned_count": len(data) if isinstance(data, list) else (1 if data else 0),
                "total_authors": len(authors),
                "work": {
                    "id": article.data.get("id") if isinstance(article.data, dict) else None,
                    "doi": article.data.get("doi") if isinstance(article.data, dict) else None,
                    "title": article.data.get("title") if isinstance(article.data, dict) else None,
                    "publication_year": article.data.get("publication_year") if isinstance(article.data, dict) else None,
                },
            },
            diagnostics=diagnostics,
        )

    async def resolve_article_url(self, url_or_doi: str) -> str:
        """Accept a Springer URL, DOI URL, or bare DOI and return an article URL."""
        value = _compact_spaces(url_or_doi)
        if not value:
            raise ValueError("URL or DOI is required.")

        doi = normalize_doi(value)
        if doi and (not is_http_url(value) or re.match(r"^https?://(?:dx\.)?doi\.org/", value, re.I)):
            try:
                return await self.resolve_doi(doi)
            except httpx.HTTPError:
                if doi.lower().startswith("10.1007/"):
                    return f"{self.base_url}/article/{doi}"
                raise

        if is_http_url(value):
            return value

        if doi:
            return await self.resolve_doi(doi)

        raise ValueError(f"Input is neither an HTTP URL nor a DOI: {url_or_doi}")

    async def resolve_doi(self, doi: str) -> str:
        resolver_url = f"{self.doi_resolver_url}/{quote(doi, safe='/:._;()-')}"
        response = await self._request("GET", resolver_url, follow_redirects=True)
        return str(response.url)

    async def _scrape_article(self, identifier: str, *, include_fulltext: bool) -> dict[str, Any]:
        article_url = await self.resolve_article_url(identifier)
        response = await self._request("GET", article_url)
        tree = self.parser.parse(response.text)
        data = self.parser.extract_article(tree, article_url, include_fulltext=include_fulltext)
        data["input"] = identifier
        return data

    async def _download_pdf(self, url: str) -> bytes:
        response = await self._request("GET", url)
        return response.content

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self.polite_delay:
            await asyncio.sleep(random.uniform(*self.polite_delay))
        kwargs.setdefault("follow_redirects", True)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        extra_headers = kwargs.pop("headers", None)
        if extra_headers:
            headers.update(extra_headers)

        if self._client is not None:
            response = await self._client.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            return response

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            return response

    def _normalize_work(self, data: dict[str, Any]) -> dict[str, Any]:
        doi = normalize_doi(data.get("doi") or "")
        doi_url = f"https://doi.org/{doi}" if doi else None
        references = data.get("references") or []
        raw_authors = data.get("authors") or []

        record = {
            "id": self._springer_id(doi=doi, source_url=data.get("source_url")),
            "doi": doi_url,
            "title": _none_if_unknown(data.get("title"), "Unknown title"),
            "publication_year": _year_from_text(data.get("publish_date")),
            "publication_date": _none_if_unknown(data.get("publish_date"), "Unknown date"),
            "type": _none_if_unknown(data.get("article_type"), "Unknown type") or "article",
            "cited_by_count": 0,
            "is_oa": None,
            "source": {
                "id": None,
                "name": _none_if_unknown(data.get("journal"), "Unknown journal"),
                "type": "journal",
                "issn_l": None,
            },
            "topics": [
                {
                    "id": None,
                    "name": keyword,
                    "score": None,
                }
                for keyword in data.get("keywords") or []
            ],
            "abstract": _none_if_unknown(data.get("abstract"), "No abstract available.") or "",
            "authors": self._normalize_authors(raw_authors),
            "referenced_works": _reference_doi_urls(references),
            "provider_ids": {
                key: value
                for key, value in {
                    "doi": doi,
                    "source_url": data.get("source_url"),
                }.items()
                if value
            },
            "pdf_url": data.get("pdf_link"),
            "_raw": {
                "source_url": data.get("source_url"),
                "scraped_at": data.get("scraped_at"),
                "article_type": data.get("article_type"),
                "volume": data.get("volume"),
                "issue": data.get("issue"),
                "pages": data.get("pages"),
                "keywords": data.get("keywords") or [],
                "institutions": data.get("institutions") or [],
                "authors_raw": raw_authors,
                "references": references,
                "reference_count": len(references),
                "pdf_link": data.get("pdf_link"),
            },
        }
        return {
            key: value
            for key, value in record.items()
            if value not in (None, "", [], {}) or key in {"topics", "authors", "referenced_works", "abstract"}
        }

    def _normalize_authors(self, names: Iterable[str]) -> list[dict[str, Any]]:
        authors = []
        for index, name in enumerate(_dedupe(names), start=1):
            authors.append(
                {
                    "id": "",
                    "display_name": name,
                    "orcid": None,
                    "position": index,
                    "author_position": "",
                    "is_corresponding": None,
                    "institutions": [],
                }
            )
        return authors

    def _springer_id(self, *, doi: str | None, source_url: Any) -> str:
        if doi:
            return f"springer:{doi}"
        source = _compact_spaces(source_url or "")
        digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:12] if source else "unknown"
        return f"springer:{digest}"


class SpringerArticleParser:
    """Parse Springer article pages into extracted article fields."""

    def __init__(self, *, base_url: str = BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def parse(self, content: bytes | str) -> etree._Element:
        document = html.fromstring(content)
        document.make_links_absolute(self.base_url)
        return document

    def extract_article(self, tree: etree._Element, url: str, *, include_fulltext: bool = True) -> dict[str, Any]:
        meta = self.extract_meta(tree)
        json_ld = self.extract_json_ld(tree)

        title = _first(
            [
                meta.get("citation_title"),
                meta.get("dc.title"),
                json_ld.get("headline"),
                json_ld.get("name"),
                meta.get("og:title"),
                _xpath_first(tree, ["//h1"]),
            ],
            "Unknown title",
        )

        doi = _first(
            [
                meta.get("citation_doi"),
                meta.get("dc.identifier"),
                meta.get("prism.doi"),
                json_ld.get("doi"),
                doi_from_text(_xpath_first(tree, ["//body"]) or ""),
            ],
            "Unknown DOI",
        )
        if doi and doi.startswith("doi:"):
            doi = doi[4:]

        authors = self._dedupe_authors(
            _xpath_texts(
                tree,
                [
                    '//span[contains(@class,"authors__name")]',
                    '//li[contains(@class,"c-article-author-list__item")]'
                    '//span[contains(@class,"name")]',
                    '//meta[@name="citation_author"]/@content',
                ],
            )
            + self._json_ld_people(json_ld.get("author"))
            + self._list_meta(meta, "citation_author")
        )

        institutions = _dedupe(
            self._list_meta(meta, "citation_author_institution")
            + _xpath_texts(
                tree,
                [
                    '//li[contains(@class,"c-article-author-affiliation")]',
                    '//section[@id="Affiliations"]//li',
                    '//section[contains(@data-title,"Author information")]//li[contains(@class,"affiliation")]',
                ],
            )
        )

        keywords = _dedupe(
            self._split_keywords(meta.get("citation_keywords"))
            + self._split_keywords(meta.get("keywords"))
            + _xpath_texts(
                tree,
                [
                    '//div[contains(@class,"c-bibliographic-information__column")]'
                    '/h3[normalize-space()="Keywords"]/following-sibling::ul[1]/li//a',
                    '//section[contains(@class,"article-keywords")]//li',
                ],
            )
        )

        abstract = _first(
            [
                json_ld.get("description"),
                meta.get("description"),
                meta.get("dc.description"),
                self.extract_section_text(tree, "Abstract"),
            ],
            "No abstract available.",
        )

        pdf_link = _first(
            [
                meta.get("citation_pdf_url"),
                _xpath_first(
                    tree,
                    [
                        '//a[contains(@class,"pdf-download")]/@href',
                        '//a[contains(@href,"/content/pdf") and contains(@href,".pdf")]/@href',
                        '//meta[@name="citation_pdf_url"]/@content',
                    ],
                ),
            ]
        )
        pdf_link = urljoin(self.base_url, pdf_link) if pdf_link else None

        references = self.extract_references(tree)
        article: dict[str, Any] = {
            "source_url": url,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "title": title,
            "article_type": self.extract_article_type(tree),
            "publish_date": _first(
                [
                    meta.get("citation_publication_date"),
                    meta.get("dc.date"),
                    meta.get("prism.publicationdate"),
                    json_ld.get("datePublished"),
                    _xpath_first(
                        tree,
                        [
                            '//ul[contains(@class,"c-article-identifiers")]/li/time',
                            '//time[contains(@itemprop,"datePublished")]',
                        ],
                    ),
                ],
                "Unknown date",
            ),
            "journal": _first(
                [
                    meta.get("citation_journal_title"),
                    meta.get("prism.publicationname"),
                    _xpath_first(
                        tree,
                        [
                            '//a[@data-track-action="journal homepage"]/span',
                            '//i[@data-test="journal-title"]',
                            '//span[contains(@class,"app-journal-masthead__title")]//a',
                        ],
                    ),
                ],
                "Unknown journal",
            ),
            "volume": _first(
                [
                    meta.get("citation_volume"),
                    _xpath_first(tree, ['//span[@data-test="journal-volume"]', '//meta[@name="citation_volume"]/@content']),
                ],
                "Unknown volume",
            ),
            "issue": _first(
                [
                    meta.get("citation_issue"),
                    _xpath_first(tree, ['//span[@data-test="journal-issue"]', '//meta[@name="citation_issue"]/@content']),
                ],
            ),
            "pages": self.extract_pages(meta, tree),
            "doi": doi,
            "doi_url": f"https://doi.org/{doi}" if doi and doi != "Unknown DOI" else None,
            "pdf_link": pdf_link,
            "authors": authors,
            "institutions": institutions,
            "keywords": keywords,
            "abstract": abstract,
            "references": references,
            "reference_num": len(references),
        }

        if include_fulltext:
            full_text_markdown = self.extract_full_text_markdown(tree, title or "")
            article["full_text"] = self.markdown_to_plain_text(full_text_markdown) or "No full text available."
            article["full_text_markdown"] = full_text_markdown or "No full text available."

        return article

    def extract_meta(self, tree: etree._Element) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        for node in tree.xpath("//meta[@name or @property]"):
            key = (node.get("name") or node.get("property") or "").strip().lower()
            value = _compact_spaces(node.get("content") or "")
            if not key or not value:
                continue
            if key in meta:
                if isinstance(meta[key], list):
                    meta[key].append(value)
                else:
                    meta[key] = [meta[key], value]
            else:
                meta[key] = value
        return meta

    def extract_json_ld(self, tree: etree._Element) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []
        for script in tree.xpath('//script[@type="application/ld+json"]/text()'):
            try:
                payload = json.loads(script)
            except json.JSONDecodeError:
                continue
            for item in self._flatten_json_ld(payload):
                item_type = item.get("@type") or item.get("type") or ""
                if isinstance(item_type, list):
                    type_text = " ".join(str(part) for part in item_type)
                else:
                    type_text = str(item_type)
                if re.search(r"(scholarlyarticle|article|creativework)", type_text, re.I):
                    candidates.append(item)
        return candidates[0] if candidates else {}

    def extract_section_text(self, tree: etree._Element, section_title: str) -> str | None:
        lower_title = section_title.lower()
        sections = tree.xpath(
            f'//section[translate(@data-title, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")="{lower_title}"]'
        )
        if not sections:
            sections = tree.xpath(
                f'//section[.//h2[translate(normalize-space(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")="{lower_title}"]]'
            )
        if not sections:
            return None
        paragraphs = [_text_content(node) for node in sections[0].xpath(".//p")]
        return _first(paragraphs) if len(paragraphs) == 1 else "\n\n".join(_dedupe(paragraphs))

    def extract_article_type(self, tree: etree._Element) -> str:
        return _first(
            _xpath_texts(
                tree,
                [
                    '//span[contains(@class,"c-article-identifiers__type")]',
                    '//div[contains(@class,"c-meta")]/span[contains(@class,"type")]',
                    '//span[@data-test="article-category"]',
                ],
            ),
            "Unknown type",
        )

    def extract_pages(self, meta: dict[str, Any], tree: etree._Element) -> str | None:
        first_page = _first([self._meta_value(meta, "citation_firstpage")])
        last_page = _first([self._meta_value(meta, "citation_lastpage")])
        if first_page and last_page:
            return f"{first_page}-{last_page}" if first_page != last_page else first_page
        return _xpath_first(
            tree,
            [
                '//span[@data-test="journal-pages"]',
                '//li[contains(.,"Pages")]/span',
            ],
        )

    def extract_references(self, tree: etree._Element) -> list[str]:
        nodes = tree.xpath(
            '//section[contains(translate(@data-title, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "references")]'
            '//ol[contains(@class,"c-article-references")]/li'
            ' | //ol[contains(@class,"c-article-references")]/li'
            ' | //li[contains(@class,"c-article-references__item")]'
        )
        references = []
        for node in nodes:
            text = _text_content(node)
            if text:
                references.append(text)
        return _dedupe(references)

    def extract_full_text_markdown(self, tree: etree._Element, title: str = "") -> str:
        blocks: list[str] = []
        if title:
            blocks.append(f"# {title}")

        roots = self._article_body_roots(tree)
        if roots:
            for root in roots:
                self._append_markdown_blocks(root, blocks)
        else:
            fallback_root = _first_element(
                tree.xpath(
                    '//main | //article | //div[contains(@class,"main-content")] | '
                    '//div[contains(@class,"c-article-body")]'
                )
            )
            if fallback_root is not None:
                self._append_markdown_blocks(fallback_root, blocks)

        return "\n\n".join(_dedupe_preserve_blocks(blocks)).strip()

    def markdown_to_plain_text(self, markdown: str) -> str:
        lines = []
        for line in markdown.splitlines():
            line = re.sub(r"^#{1,6}\s+", "", line)
            line = re.sub(r"^[-*]\s+", "", line)
            line = re.sub(r"^>\s*", "", line)
            clean = _compact_spaces(line)
            if clean:
                lines.append(clean)
        return "\n\n".join(lines)

    def render_article_markdown(self, data: dict[str, Any]) -> str:
        lines = [f"# {data.get('title') or 'Untitled Springer Article'}"]
        meta_lines = []
        if data.get("doi"):
            meta_lines.append(f"- DOI: {data['doi']}")
        if data.get("journal"):
            meta_lines.append(f"- Journal: {data['journal']}")
        if data.get("publish_date"):
            meta_lines.append(f"- Published: {data['publish_date']}")
        if data.get("authors"):
            meta_lines.append(f"- Authors: {', '.join(data['authors'])}")
        if data.get("source_url"):
            meta_lines.append(f"- Source: {data['source_url']}")
        if meta_lines:
            lines.extend(["", *meta_lines])

        if data.get("abstract") and data["abstract"] != "No abstract available.":
            lines.extend(["", "## Abstract", data["abstract"]])

        body = data.get("full_text_markdown") or ""
        body_lines = body.splitlines()
        if body_lines and body_lines[0].lstrip().startswith("# "):
            body = "\n".join(body_lines[1:]).strip()
        if body:
            lines.extend(["", body])

        references = data.get("references") or []
        if references:
            lines.extend(["", "## References"])
            lines.extend(f"{index}. {ref}" for index, ref in enumerate(references, start=1))

        return "\n".join(lines).rstrip() + "\n"

    def _article_body_roots(self, tree: etree._Element) -> list[etree._Element]:
        roots = tree.xpath(
            '//section[contains(@class,"c-article-section")]'
            ' | //div[contains(@class,"c-article-body")]//section'
            ' | //article//section[@data-title]'
        )
        filtered = []
        for root in roots:
            if self._has_candidate_ancestor(root, roots) or self._should_skip_node(root):
                continue
            filtered.append(root)
        return filtered

    def _append_markdown_blocks(self, root: etree._Element, blocks: list[str]) -> None:
        emitted_data_title = False
        data_title = _compact_spaces(root.get("data-title") or "")
        if data_title and not self._has_matching_heading(root, data_title):
            blocks.append(f"## {data_title}")
            emitted_data_title = True

        for node in root.iter():
            if node is not root and self._should_skip_node(node):
                continue

            tag = _tag_name(node)
            if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                text = _text_content(node)
                if _normalise_heading_text(text) in SKIP_HEADING_TITLES:
                    break
                if text:
                    level = max(1, min(int(tag[1]), 6))
                    blocks.append(f"{'#' * level} {text}")
                continue

            if tag not in BLOCK_TAGS:
                continue

            if self._has_block_ancestor(node, stop_at=root):
                continue

            text = _text_content(node)
            if not text:
                continue

            if tag == "li":
                blocks.append(f"- {text}")
            elif tag in {"figcaption", "caption"}:
                blocks.append(f"> {text}")
            elif tag == "blockquote":
                blocks.append(f"> {text}")
            else:
                blocks.append(text)

        if emitted_data_title and len(blocks) >= 2 and blocks[-1] == f"## {data_title}":
            blocks.pop()

    def _should_skip_node(self, node: etree._Element) -> bool:
        for ancestor in [node, *node.iterancestors()]:
            data_title = _compact_spaces(ancestor.get("data-title") or "").lower()
            if data_title in SKIP_SECTION_TITLES:
                return True

            class_text = _compact_spaces(ancestor.get("class") or "").lower()
            id_text = _compact_spaces(ancestor.get("id") or "").lower()
            if any(pattern in class_text for pattern in SKIP_CLASS_PATTERNS):
                return True
            if id_text in {"references", "author-information", "rightslink"}:
                return True
        return False

    def _has_matching_heading(self, node: etree._Element, title: str) -> bool:
        expected = _normalise_heading_text(title)
        if not expected:
            return False
        for heading in node.xpath(".//h1 | .//h2 | .//h3 | .//h4 | .//h5 | .//h6"):
            if _normalise_heading_text(_text_content(heading)) == expected:
                return True
        return False

    def _has_candidate_ancestor(self, node: etree._Element, candidates: Sequence[etree._Element]) -> bool:
        for ancestor in node.iterancestors():
            if any(ancestor is candidate for candidate in candidates):
                return True
        return False

    def _has_block_ancestor(self, node: etree._Element, stop_at: etree._Element) -> bool:
        for ancestor in node.iterancestors():
            if ancestor is stop_at:
                return False
            if _tag_name(ancestor) in BLOCK_TAGS:
                return True
        return False

    def _meta_value(self, meta: dict[str, Any], key: str) -> str | None:
        value = meta.get(key.lower())
        if isinstance(value, list):
            return _first(value)
        return _compact_spaces(value or "") or None

    def _list_meta(self, meta: dict[str, Any], key: str) -> list[str]:
        value = meta.get(key.lower())
        if value is None:
            return []
        if isinstance(value, list):
            return _dedupe(value)
        return [value] if _compact_spaces(value) else []

    def _split_keywords(self, value: str | None) -> list[str]:
        if not value:
            return []
        return _dedupe(part for part in re.split(r"[;,]", value) if part.strip())

    def _json_ld_people(self, payload: Any) -> list[str]:
        if not payload:
            return []
        people = payload if isinstance(payload, list) else [payload]
        names = []
        for person in people:
            if isinstance(person, dict):
                names.append(str(person.get("name") or ""))
            else:
                names.append(str(person))
        return _dedupe(names)

    def _dedupe_authors(self, values: Iterable[str]) -> list[str]:
        seen = set()
        authors = []
        for value in values:
            clean = _compact_spaces(value)
            if not clean or re.fullmatch(r"\d+", clean):
                continue
            key = _normalise_author_key(clean)
            if key and key not in seen:
                seen.add(key)
                authors.append(clean)
        return authors

    def _flatten_json_ld(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            items: list[dict[str, Any]] = []
            for item in payload:
                items.extend(self._flatten_json_ld(item))
            return items
        if not isinstance(payload, dict):
            return []
        graph = payload.get("@graph")
        if isinstance(graph, list):
            return [payload] + [item for node in graph for item in self._flatten_json_ld(node)]
        return [payload]


def doi_from_text(value: str) -> str | None:
    match = DOI_RE.search(value or "")
    if not match:
        return None
    return match.group(0).rstrip(".,;)")


def normalize_doi(value: str) -> str | None:
    clean = _compact_spaces(value)
    clean = re.sub(r"^doi:\s*", "", clean, flags=re.I)
    clean = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", clean, flags=re.I)
    clean = clean.strip()
    match = DOI_RE.search(clean)
    if not match:
        return None
    return match.group(0).rstrip(".,;)")


def is_http_url(value: str) -> bool:
    return bool(re.match(r"^https?://", value or "", flags=re.I))


def _compact_spaces(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = " ".join(_compact_spaces(item) for item in value)
    elif isinstance(value, dict):
        value = value.get("name") or value.get("value") or ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _dedupe(values: Iterable[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        clean = _compact_spaces(value)
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _first(values: Iterable[Any], default: str | None = None) -> str | None:
    for value in values:
        clean = _compact_spaces(value or "")
        if clean:
            return clean
    return default


def _text_content(node: etree._Element) -> str:
    return _compact_spaces(" ".join(node.xpath(".//text()[normalize-space()]")))


def _xpath_texts(tree: etree._Element, expressions: Sequence[str]) -> list[str]:
    values: list[str] = []
    for expression in expressions:
        for item in tree.xpath(expression):
            if isinstance(item, etree._Element):
                values.append(_text_content(item))
            else:
                values.append(str(item))
    return _dedupe(values)


def _xpath_first(tree: etree._Element, expressions: Sequence[str]) -> str | None:
    return _first(_xpath_texts(tree, expressions))


def _tag_name(node: etree._Element) -> str:
    return str(node.tag).lower() if isinstance(node.tag, str) else ""


def _first_element(nodes: Sequence[Any]) -> etree._Element | None:
    for node in nodes:
        if isinstance(node, etree._Element):
            return node
    return None


def _dedupe_preserve_blocks(blocks: Iterable[str]) -> list[str]:
    result = []
    previous = None
    for block in blocks:
        clean = block.strip()
        if clean and clean != previous:
            result.append(clean)
            previous = clean
    return result


def _normalise_heading_text(value: str) -> str:
    clean = _compact_spaces(value).lower()
    clean = re.sub(r"^\d+(?:\.\d+)*\s+", "", clean)
    return clean


def _normalise_author_key(value: str) -> str:
    clean = _compact_spaces(value).lower()
    if "," in clean:
        parts = [part.strip() for part in clean.split(",", 1)]
        if all(parts):
            clean = f"{parts[1]} {parts[0]}"
    clean = re.sub(r"[^a-z0-9]+", " ", clean)
    return _compact_spaces(clean)


def _reference_doi_urls(references: Iterable[str]) -> list[str]:
    dois = []
    for reference in references:
        doi = normalize_doi(reference)
        if doi:
            dois.append(f"https://doi.org/{doi}")
    return _dedupe(dois)


def _year_from_text(value: Any) -> int | None:
    match = re.search(r"\b(18|19|20|21)\d{2}\b", _compact_spaces(value))
    if not match:
        return None
    return int(match.group(0))


def _none_if_unknown(value: Any, unknown: str) -> str | None:
    text = _compact_spaces(value)
    if not text or text == unknown:
        return None
    return text
