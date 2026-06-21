"""Elsevier ScienceDirect API provider."""

from __future__ import annotations

import os
from datetime import date
from typing import Any

import httpx
from dotenv import load_dotenv

from metasci_universe.providers.base import ProviderResult
from metasci_universe.schemas.authors import AuthorProfileRequest, AuthorSearchRequest, WorkAuthorsRequest
from metasci_universe.schemas.works import WorksFullTextRequest, WorksGetRequest, WorksSearchRequest


DEFAULT_BASE_URL = "https://api.elsevier.com/content"


class ScienceDirectAPIProvider:
    """Provider backed by Elsevier ScienceDirect article APIs."""

    name = "sciencedirect"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        inst_token: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        load_dotenv()
        self.api_key = api_key or os.getenv("ELSEVIER_API_KEY") or os.getenv("SCIENCEDIRECT_API_KEY")
        if not self.api_key:
            raise ValueError("Set ELSEVIER_API_KEY or SCIENCEDIRECT_API_KEY for ScienceDirect access.")
        self.inst_token = inst_token or os.getenv("ELSEVIER_INST_TOKEN") or os.getenv("SCIENCEDIRECT_INST_TOKEN")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client

    async def search_works(self, request: WorksSearchRequest) -> ProviderResult:
        if not request.query:
            raise ValueError("ScienceDirect works.search requires a keyword query.")

        diagnostics = self._unsupported_search_diagnostics(request)
        body: dict[str, Any] = {
            "qs": request.query,
            "display": {
                "offset": 0,
                "show": min(request.limit, 100),
            },
        }
        if request.from_year is not None or request.to_year is not None:
            body["date"] = f"{request.from_year or ''}-{request.to_year or ''}"

        payload = await self._request_json("PUT", "/search/sciencedirect", json=body)
        records = [
            self._normalize_search_result(item, include_raw=request.include_raw)
            for item in payload.get("results") or []
            if isinstance(item, dict)
        ]
        return ProviderResult(
            data=records[: request.limit],
            metadata={
                "provider": self.name,
                "returned_count": len(records[: request.limit]),
                "filtered_total": self._total_results(payload),
            },
            diagnostics=diagnostics,
        )

    async def get_work(self, request: WorksGetRequest) -> ProviderResult:
        identifier, id_type = self._article_identifier(request.identifier)
        payload = await self._request_json("GET", f"/article/{id_type}/{identifier}", params={"view": "META_ABS_REF"})
        work = self._normalize_article_payload(payload, identifier=identifier, id_type=id_type)
        return ProviderResult(data=work, metadata={"provider": self.name, "returned_count": 1})

    async def get_fulltext(self, request: WorksFullTextRequest) -> ProviderResult:
        identifier, id_type = self._article_identifier(request.identifier)
        response = await self._request("GET", f"/article/{id_type}/{identifier}", accept="text/xml")
        xml = response.text
        return ProviderResult(
            data=xml,
            metadata={
                "provider": self.name,
                "identifier": identifier,
                "id_type": id_type,
                "format": "xml",
                "content_length": len(xml),
            },
        )

    async def search_authors(self, request: AuthorSearchRequest) -> ProviderResult:
        raise NotImplementedError("ScienceDirect provider does not support authors.search.")

    async def get_author(self, request: AuthorProfileRequest) -> ProviderResult:
        raise NotImplementedError("ScienceDirect provider does not support authors.profile.")

    async def authors_from_work(self, request: WorkAuthorsRequest) -> ProviderResult:
        article = await self.get_work(WorksGetRequest(identifier=request.identifier, provider="sciencedirect"))
        authors = article.data.get("authors") if isinstance(article.data, dict) else None
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
            },
            diagnostics=diagnostics,
        )

    async def _request_json(self, method: str, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        response = await self._request(method, endpoint, accept="application/json", **kwargs)
        return response.json()

    async def _request(self, method: str, endpoint: str, *, accept: str, **kwargs: Any) -> httpx.Response:
        url = endpoint if endpoint.startswith("http") else f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {"X-ELS-APIKey": self.api_key, "Accept": accept}
        if self.inst_token:
            headers["X-ELS-Insttoken"] = self.inst_token
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

    def _normalize_search_result(self, item: dict[str, Any], *, include_raw: list[str]) -> dict[str, Any]:
        pii = self._clean_text(item.get("pii"))
        doi = self._normalize_doi(item.get("doi"))
        record = {
            "id": self._science_direct_id(pii=pii, doi=doi),
            "doi": doi,
            "title": self._clean_text(item.get("title")),
            "publication_year": self._year_from_date(item.get("publicationDate")),
            "publication_date": self._clean_text(item.get("publicationDate")),
            "type": "article",
            "cited_by_count": 0,
            "is_oa": self._bool_or_none(item.get("openAccess")),
            "source": {
                "id": None,
                "name": self._clean_text(item.get("sourceTitle")),
                "type": "journal",
                "issn_l": None,
            },
            "topics": [],
            "provider_ids": self._provider_ids(pii=pii),
        }
        if include_raw:
            record["_raw"] = {field: item[field] for field in include_raw if field in item}
        return record

    def _normalize_article_payload(self, payload: dict[str, Any], *, identifier: str, id_type: str) -> dict[str, Any]:
        core = self._article_core(payload)
        pii = self._first_text(
            core.get("pii"),
            core.get("xocs:pii"),
            core.get("prism:pii"),
            identifier if id_type == "pii" else None,
        )
        doi = self._normalize_doi(self._first_text(core.get("doi"), core.get("prism:doi"), identifier if id_type == "doi" else None))
        publication_date = self._first_text(
            core.get("publicationDate"),
            core.get("prism:coverDate"),
            core.get("prism:coverDisplayDate"),
        )
        record = {
            "id": self._science_direct_id(pii=pii, doi=doi),
            "doi": doi,
            "title": self._first_text(core.get("title"), core.get("dc:title")),
            "publication_year": self._year_from_date(publication_date),
            "publication_date": publication_date,
            "type": "article",
            "cited_by_count": 0,
            "is_oa": self._bool_or_none(self._first_text(core.get("openAccess"), core.get("openaccess"))),
            "source": {
                "id": None,
                "name": self._first_text(core.get("sourceTitle"), core.get("prism:publicationName")),
                "type": "journal",
                "issn_l": self._first_text(core.get("issn"), core.get("prism:issn")),
            },
            "topics": [],
            "abstract": self._abstract_text(core),
            "authors": self._authors(core),
            "referenced_works": self._references(core),
            "provider_ids": self._provider_ids(
                pii=pii,
                eid=self._first_text(core.get("eid")),
                scopus_id=self._first_text(core.get("scopus_id"), core.get("scopus-id")),
                pubmed_id=self._first_text(core.get("pubmed_id"), core.get("pubmed-id")),
            ),
            "_raw": payload,
        }
        return {key: value for key, value in record.items() if value not in (None, "", [], {}) or key in {"topics", "authors", "referenced_works"}}

    def _article_core(self, payload: dict[str, Any]) -> dict[str, Any]:
        for key in ("full-text-retrieval-response", "abstracts-retrieval-response", "article"):
            value = payload.get(key)
            if isinstance(value, dict):
                return value.get("coredata") if isinstance(value.get("coredata"), dict) else value
        core = payload.get("coredata")
        if isinstance(core, dict):
            return core
        return payload

    def _abstract_text(self, core: dict[str, Any]) -> str:
        abstract = self._first_text(core.get("dc:description"), core.get("description"), core.get("abstract"))
        if abstract:
            return abstract
        article = core.get("article")
        if isinstance(article, dict):
            return self._first_text(article.get("abstract"), article.get("dc:description"))
        return ""

    def _authors(self, core: dict[str, Any]) -> list[dict[str, Any]]:
        raw_authors = core.get("authors") or core.get("author") or core.get("dc:creator")
        if isinstance(raw_authors, dict):
            raw_authors = raw_authors.get("author") or raw_authors.get("$") or raw_authors
        if isinstance(raw_authors, str):
            raw_authors = [name.strip() for name in raw_authors.split(";") if name.strip()]
        if not isinstance(raw_authors, list):
            return []

        authors = []
        for index, item in enumerate(raw_authors, start=1):
            if isinstance(item, str):
                name = item
                author_id = ""
                orcid = None
            elif isinstance(item, dict):
                name = self._first_text(item.get("ce:indexed-name"), item.get("preferred-name"), item.get("name"), item.get("$"))
                author_id = self._first_text(item.get("@auid"), item.get("auid"))
                orcid = self._first_text(item.get("orcid"))
            else:
                continue
            if not name:
                continue
            authors.append(
                {
                    "id": author_id,
                    "display_name": name,
                    "orcid": orcid,
                    "position": index,
                    "author_position": "",
                    "is_corresponding": None,
                    "institutions": [],
                }
            )
        return authors

    def _references(self, core: dict[str, Any]) -> list[str]:
        bibliography = core.get("bibliography") or core.get("references") or core.get("reference")
        if isinstance(bibliography, dict):
            raw_references = bibliography.get("reference") or bibliography.get("references") or []
        else:
            raw_references = bibliography
        if not isinstance(raw_references, list):
            return []

        references = []
        for item in raw_references:
            if isinstance(item, str):
                references.append(item)
            elif isinstance(item, dict):
                value = self._first_text(
                    item.get("doi"),
                    item.get("prism:doi"),
                    item.get("ref-info", {}).get("refd-itemidlist", {}).get("itemid")
                    if isinstance(item.get("ref-info"), dict)
                    else None,
                    item.get("@id"),
                )
                if value:
                    references.append(self._normalize_doi(value) if self._looks_like_doi(value) else value)
        return references

    def _unsupported_search_diagnostics(self, request: WorksSearchRequest) -> list[str]:
        unsupported = []
        for field in (
            "topic_name",
            "source_name",
            "author_name",
            "institution_name",
            "topic_id",
            "source_id",
            "author_id",
            "institution_id",
            "country_code",
            "is_oa",
            "min_cited_by_count",
            "max_cited_by_count",
        ):
            if getattr(request, field) not in (None, "", False):
                unsupported.append(field)
        if request.work_type and request.work_type != "article":
            unsupported.append("work_type")
        if request.sort_by != "cited_by_count:desc":
            unsupported.append("sort_by")
        if unsupported:
            return [
                "ScienceDirect search currently applies query/date/limit only; ignored unsupported filters: "
                + ", ".join(sorted(set(unsupported)))
            ]
        return []

    def _article_identifier(self, identifier: str) -> tuple[str, str]:
        value = identifier.strip()
        if value.lower().startswith("doi:"):
            return value.split(":", 1)[1], "doi"
        if value.startswith("https://doi.org/"):
            return value.removeprefix("https://doi.org/"), "doi"
        if value.startswith("http://doi.org/"):
            return value.removeprefix("http://doi.org/"), "doi"
        if value.startswith("10."):
            return value, "doi"
        return value, "pii"

    def _science_direct_id(self, *, pii: str | None, doi: str | None) -> str:
        if pii:
            return f"sciencedirect:{pii}"
        if doi:
            return f"sciencedirect:{doi.replace('https://doi.org/', '')}"
        return "sciencedirect:unknown"

    def _provider_ids(self, **values: str | None) -> dict[str, str]:
        return {key: value for key, value in values.items() if value}

    def _normalize_doi(self, value: Any) -> str | None:
        text = self._clean_text(value)
        if not text:
            return None
        if text.startswith("https://doi.org/"):
            return text
        if text.startswith("doi:"):
            text = text.split(":", 1)[1]
        return f"https://doi.org/{text}"

    def _looks_like_doi(self, value: Any) -> bool:
        text = self._clean_text(value) or ""
        if text.startswith("https://doi.org/") or text.startswith("doi:"):
            return True
        return text.startswith("10.")

    def _year_from_date(self, value: Any) -> int | None:
        text = self._clean_text(value)
        if not text:
            return None
        try:
            return date.fromisoformat(text[:10]).year
        except ValueError:
            try:
                return int(text[:4])
            except ValueError:
                return None

    def _total_results(self, payload: dict[str, Any]) -> int | None:
        for key in ("resultsFound", "totalResults", "opensearch:totalResults"):
            value = payload.get(key)
            if value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
        return None

    def _bool_or_none(self, value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        text = self._clean_text(value).lower()
        if text in {"true", "yes", "1", "open"}:
            return True
        if text in {"false", "no", "0", "closed"}:
            return False
        return None

    def _first_text(self, *values: Any) -> str | None:
        for value in values:
            text = self._clean_text(value)
            if text:
                return text
        return None

    def _clean_text(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, dict):
            for key in ("$", "_", "text"):
                if key in value:
                    return self._clean_text(value[key])
            return None
        text = str(value).strip()
        return text or None
