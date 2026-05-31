"""OpenAlex public REST API provider."""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any

import httpx
from dotenv import load_dotenv

from metasci_universe.schemas.authors import AuthorProfileRequest, AuthorSearchRequest, WorkAuthorsRequest
from metasci_universe.schemas.works import WorksGetRequest, WorksSearchRequest
from metasci_universe.providers.base import ProviderResult


DEFAULT_BASE_URL = "https://api.openalex.org"


class OpenAlexAPIProvider:
    """Provider backed by the public OpenAlex REST API."""

    name = "openalex"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        mailto: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        load_dotenv()
        self.api_key = api_key or os.getenv("OPENALEX_API_KEY") or os.getenv("PYALEX_API_KEY")
        self.mailto = mailto or os.getenv("OPENALEX_EMAIL") or os.getenv("PYALEX_EMAIL")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client

    async def search_works(self, request: WorksSearchRequest) -> ProviderResult:
        diagnostics: list[str] = []
        resolved_entities: dict[str, Any] = {}
        filters: list[str] = []

        if request.from_year is not None:
            filters.append(f"from_publication_date:{request.from_year}-01-01")
        if request.to_year is not None:
            filters.append(f"to_publication_date:{request.to_year}-12-31")
        if request.country_code:
            filters.append(f"authorships.institutions.country_code:{request.country_code}")
        if request.work_type:
            filters.append(f"type:{request.work_type}")
        if request.is_oa is not None:
            filters.append(f"is_oa:{str(request.is_oa).lower()}")
        if request.min_cited_by_count is not None and request.min_cited_by_count > 0:
            filters.append(f"cited_by_count:>{request.min_cited_by_count - 1}")
        if request.max_cited_by_count is not None:
            filters.append(f"cited_by_count:<{request.max_cited_by_count + 1}")

        topic_id = request.topic_id
        if request.topic_name and not topic_id:
            entity = await self._resolve_topic_hierarchical(request.topic_name, diagnostics)
            topic_id = entity.get("id")
            resolved_entities["topic"] = entity
        if topic_id:
            filters.append(self._topic_filter(topic_id))

        source_id = request.source_id
        if request.source_name and not source_id:
            entity = await self._resolve_entity("sources", request.source_name, diagnostics)
            source_id = entity.get("id")
            resolved_entities["source"] = entity
        if source_id:
            filters.append(f"primary_location.source.id:{self._compact_openalex_id(source_id)}")

        author_id = request.author_id
        if request.author_name and not author_id:
            entity = await self._resolve_entity("authors", request.author_name, diagnostics)
            author_id = entity.get("id")
            resolved_entities["author"] = entity
            diagnostics.append(
                "author_name was resolved to the top OpenAlex search result; use author_id for disambiguated retrieval."
            )
        if author_id:
            filters.append(f"authorships.author.id:{self._compact_openalex_id(author_id)}")

        institution_id = request.institution_id
        if request.institution_name and not institution_id:
            entity = await self._resolve_entity("institutions", request.institution_name, diagnostics)
            institution_id = entity.get("id")
            resolved_entities["institution"] = entity
        if institution_id:
            filters.append(f"authorships.institutions.id:{self._compact_openalex_id(institution_id)}")

        params: dict[str, Any] = {
            "per_page": min(request.limit, 100),
            "cursor": "*",
        }
        if request.query:
            params["search"] = request.query
        if filters:
            params["filter"] = ",".join(filters)
        if request.sort_by:
            params["sort"] = request.sort_by

        select = self._works_select_fields(request)
        if select:
            params["select"] = ",".join(select)

        records, meta = await self._fetch_cursor("/works", params=params, limit=request.limit)
        works = [self._normalize_work(record, include=request.include, include_raw=request.include_raw) for record in records]
        metadata = {
            "provider": self.name,
            "returned_count": len(works),
            "filtered_total": meta.get("count"),
            "openalex_meta": meta,
            "resolved_entities": resolved_entities,
            "filters": filters,
            "select": select,
        }
        return ProviderResult(data=works, metadata=metadata, diagnostics=diagnostics)

    async def get_work(self, request: WorksGetRequest) -> ProviderResult:
        data = await self._get_json(f"/works/{self._work_identifier(request.identifier)}")
        work = self._normalize_work(data, include=["authors", "references"], include_raw=[])
        metadata = {"provider": self.name, "returned_count": 1}
        return ProviderResult(data=work, metadata=metadata)

    async def search_authors(self, request: AuthorSearchRequest) -> ProviderResult:
        payload = await self._get_json(
            "/authors",
            params={
                "search": request.name,
                "per_page": request.limit,
                "select": self._author_select(request.detail_level),
            },
        )
        results = payload.get("results", [])
        authors = [self._normalize_author(author, detail_level=request.detail_level) for author in results]
        metadata = {
            "provider": self.name,
            "returned_count": len(authors),
            "filtered_total": (payload.get("meta") or {}).get("count"),
            "openalex_meta": payload.get("meta") or {},
        }
        return ProviderResult(data=authors, metadata=metadata)

    async def get_author(self, request: AuthorProfileRequest) -> ProviderResult:
        author = await self._get_json(f"/authors/{self._author_identifier(request.identifier)}")
        data = self._normalize_author(author, detail_level=request.detail_level)
        return ProviderResult(data=data, metadata={"provider": self.name, "returned_count": 1})

    async def authors_from_work(self, request: WorkAuthorsRequest) -> ProviderResult:
        work = await self._get_json(f"/works/{self._work_identifier(request.identifier)}")
        authorships = work.get("authorships") or []
        authors = [self._normalize_authorship(authorship, index=index) for index, authorship in enumerate(authorships, start=1)]

        diagnostics: list[str] = []
        data: Any
        if request.all_authors:
            data = authors
        else:
            if request.author_position > len(authors):
                data = None
                diagnostics.append(
                    f"Requested author_position={request.author_position}, but the work has {len(authors)} authors."
                )
            else:
                data = authors[request.author_position - 1]
                if request.detail_level == "full" and data and data.get("id"):
                    profile_request = AuthorProfileRequest(
                        identifier=data["id"],
                        detail_level="full",
                        provider=request.provider,
                        output_dir=request.output_dir,
                    )
                    profile = await self.get_author(profile_request)
                    data = {
                        **data,
                        "profile": profile.data,
                    }

        metadata = {
            "provider": self.name,
            "work": {
                "id": self._compact_openalex_id(work.get("id")),
                "doi": work.get("doi"),
                "title": work.get("title") or work.get("display_name"),
                "publication_year": work.get("publication_year"),
            },
            "returned_count": len(data) if isinstance(data, list) else (1 if data else 0),
            "total_authors": len(authors),
        }
        return ProviderResult(data=data, metadata=metadata, diagnostics=diagnostics)

    async def _resolve_entity(self, endpoint: str, name: str, diagnostics: list[str]) -> dict[str, Any]:
        payload = await self._get_json(endpoint if endpoint.startswith("/") else f"/{endpoint}", params={"search": name, "per_page": 3})
        results = payload.get("results") or []
        if not results:
            raise ValueError(f"OpenAlex {endpoint} search returned no result for {name!r}")

        selected = results[0]
        candidates = [
            {
                "id": self._compact_openalex_id(item.get("id")),
                "display_name": item.get("display_name"),
                "works_count": item.get("works_count"),
                "cited_by_count": item.get("cited_by_count"),
            }
            for item in results
        ]
        if len(candidates) > 1:
            diagnostics.append(
                f"{endpoint} name {name!r} resolved to top result {candidates[0]['display_name']!r}; "
                "inspect resolved_entities for alternatives."
            )
        return {
            "input": name,
            "id": self._compact_openalex_id(selected.get("id")),
            "display_name": selected.get("display_name"),
            "candidates": candidates,
        }

    async def _resolve_topic_hierarchical(self, name: str, diagnostics: list[str]) -> dict[str, Any]:
        payload = await self._get_json("/topics", params={"search": name, "per_page": 20})
        results = payload.get("results") or []
        if not results:
            raise ValueError(f"OpenAlex topics search returned no result for {name!r}")

        candidates = [self._topic_candidate(item) for item in results]
        for topic in results:
            for level in ("domain", "field", "subfield"):
                entity = topic.get(level)
                if self._hierarchical_match(name, (entity or {}).get("display_name")):
                    resolved = {
                        "input": name,
                        "id": self._compact_openalex_id(entity.get("id")),
                        "display_name": entity.get("display_name"),
                        "type": level,
                        "match_level": "hierarchical",
                        "matched_via_topic": {
                            "id": self._compact_openalex_id(topic.get("id")),
                            "display_name": topic.get("display_name"),
                        },
                        "candidates": candidates,
                    }
                    diagnostics.append(
                        f"topics name {name!r} resolved to {level} {resolved['display_name']!r} through topic hierarchy."
                    )
                    return resolved

        selected = results[0]
        diagnostics.append(
            f"topics name {name!r} resolved to top topic {selected.get('display_name')!r}; "
            "inspect resolved_entities for alternatives."
        )
        return {
            "input": name,
            "id": self._compact_openalex_id(selected.get("id")),
            "display_name": selected.get("display_name"),
            "type": "topic",
            "match_level": "fuzzy",
            "candidates": candidates,
        }

    def _topic_candidate(self, topic: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": self._compact_openalex_id(topic.get("id")),
            "display_name": topic.get("display_name"),
            "works_count": topic.get("works_count"),
            "cited_by_count": topic.get("cited_by_count"),
            "domain": self._topic_hierarchy_entity(topic.get("domain")),
            "field": self._topic_hierarchy_entity(topic.get("field")),
            "subfield": self._topic_hierarchy_entity(topic.get("subfield")),
        }

    def _topic_hierarchy_entity(self, entity: Any) -> dict[str, Any] | None:
        if not isinstance(entity, dict):
            return None
        return {
            "id": self._compact_openalex_id(entity.get("id")),
            "display_name": entity.get("display_name"),
        }

    def _hierarchical_match(self, query: str, candidate: Any) -> bool:
        if not isinstance(candidate, str) or not candidate.strip():
            return False

        normalized_query = self._normalize_topic_text(query)
        normalized_candidate = self._normalize_topic_text(candidate)
        if not normalized_query or not normalized_candidate:
            return False
        if normalized_query == normalized_candidate:
            return True
        if normalized_candidate.startswith(f"{normalized_query} "):
            return True
        return False

    def _normalize_topic_text(self, text: str) -> str:
        normalized = text.lower().strip()
        replacements = {
            "sciences": "science",
            "studies": "study",
        }
        for old, new in replacements.items():
            normalized = normalized.replace(old, new)
        return " ".join(normalized.split())

    def _topic_filter(self, topic_id: Any) -> str:
        compact_id = self._compact_openalex_id(topic_id)
        if isinstance(compact_id, str):
            if compact_id.startswith("domains/"):
                return f"topics.domain.id:{compact_id}"
            if compact_id.startswith("fields/"):
                return f"topics.field.id:{compact_id}"
            if compact_id.startswith("subfields/"):
                return f"topics.subfield.id:{compact_id}"
        return f"topics.id:{compact_id}"

    async def _fetch_cursor(self, endpoint: str, *, params: dict[str, Any], limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        records: list[dict[str, Any]] = []
        next_cursor = params.get("cursor", "*")
        last_meta: dict[str, Any] = {}

        while next_cursor and len(records) < limit:
            page_params = dict(params)
            page_params["cursor"] = next_cursor
            page_params["per_page"] = min(100, limit - len(records))
            payload = await self._get_json(endpoint, params=page_params)
            last_meta = payload.get("meta") or {}
            results = payload.get("results") or []
            records.extend(results)
            next_cursor = last_meta.get("next_cursor")
            if not results:
                break

        return records[:limit], last_meta

    async def _get_json(self, endpoint: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        request_params = self._with_auth_params(params or {})

        if self._client is not None:
            response = await self._client.get(url, params=request_params)
            response.raise_for_status()
            return response.json()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=request_params)
            response.raise_for_status()
            return response.json()

    def _with_auth_params(self, params: dict[str, Any]) -> dict[str, Any]:
        request_params = dict(params)
        if self.api_key:
            request_params["api_key"] = self.api_key
        elif self.mailto:
            request_params["mailto"] = self.mailto
        return request_params

    def _works_select_fields(self, request: WorksSearchRequest) -> list[str]:
        fields = [
            "id",
            "doi",
            "title",
            "display_name",
            "publication_year",
            "publication_date",
            "type",
            "cited_by_count",
            "open_access",
            "primary_location",
            "topics",
            "abstract_inverted_index",
        ]
        if "authors" in request.include:
            fields.append("authorships")
        if "references" in request.include:
            fields.append("referenced_works")
        for raw_field in request.include_raw:
            if raw_field not in fields:
                fields.append(raw_field)
        return fields

    def _author_select(self, detail_level: str) -> str | None:
        if detail_level == "full":
            return None
        return ",".join(
            [
                "id",
                "display_name",
                "orcid",
                "works_count",
                "cited_by_count",
                "summary_stats",
                "last_known_institutions",
                "affiliations",
            ]
        )

    def _normalize_work(
        self,
        work: dict[str, Any],
        *,
        include: Iterable[str],
        include_raw: Iterable[str],
    ) -> dict[str, Any]:
        include_set = set(include)
        raw_fields = set(include_raw)
        source = ((work.get("primary_location") or {}).get("source") or {})
        normalized = {
            "id": self._compact_openalex_id(work.get("id")),
            "doi": work.get("doi"),
            "title": work.get("title") or work.get("display_name"),
            "publication_year": work.get("publication_year"),
            "publication_date": work.get("publication_date"),
            "type": work.get("type"),
            "cited_by_count": work.get("cited_by_count", 0),
            "is_oa": (work.get("open_access") or {}).get("is_oa"),
            "source": {
                "id": self._compact_openalex_id(source.get("id")),
                "name": source.get("display_name"),
                "type": source.get("type"),
                "issn_l": source.get("issn_l"),
            },
            "topics": [
                {
                    "id": self._compact_openalex_id(topic.get("id")),
                    "name": topic.get("display_name"),
                    "score": topic.get("score"),
                }
                for topic in (work.get("topics") or [])[:5]
            ],
        }

        abstract = work.get("abstract_inverted_index")
        if abstract:
            normalized["abstract_inverted_index"] = abstract

        if "authors" in include_set:
            normalized["authors"] = [
                self._normalize_authorship(authorship, index=index)
                for index, authorship in enumerate(work.get("authorships") or [], start=1)
            ]

        if "references" in include_set:
            normalized["referenced_works"] = [
                self._compact_openalex_id(reference) for reference in (work.get("referenced_works") or [])
            ]

        if raw_fields:
            normalized["_raw"] = {field: work[field] for field in raw_fields if field in work}

        return normalized

    def _normalize_authorship(self, authorship: dict[str, Any], *, index: int) -> dict[str, Any]:
        author = authorship.get("author") or {}
        return {
            "id": self._compact_openalex_id(author.get("id")),
            "display_name": author.get("display_name"),
            "orcid": author.get("orcid"),
            "position": index,
            "author_position": authorship.get("author_position"),
            "is_corresponding": authorship.get("is_corresponding"),
            "institutions": [
                {
                    "id": self._compact_openalex_id(institution.get("id")),
                    "display_name": institution.get("display_name"),
                    "country_code": institution.get("country_code"),
                    "type": institution.get("type"),
                }
                for institution in (authorship.get("institutions") or [])
            ],
        }

    def _normalize_author(self, author: dict[str, Any], *, detail_level: str) -> dict[str, Any]:
        if detail_level == "full":
            normalized = dict(author)
            normalized["id"] = self._compact_openalex_id(normalized.get("id"))
            return normalized

        institutions = author.get("last_known_institutions") or []
        primary_affiliation = institutions[0] if institutions else None
        return {
            "id": self._compact_openalex_id(author.get("id")),
            "display_name": author.get("display_name"),
            "orcid": author.get("orcid"),
            "works_count": author.get("works_count"),
            "cited_by_count": author.get("cited_by_count"),
            "summary_stats": author.get("summary_stats"),
            "primary_affiliation": primary_affiliation,
        }

    def _work_identifier(self, identifier: str) -> str:
        value = identifier.strip()
        if value.startswith("http://") or value.startswith("https://"):
            if "openalex.org/" in value:
                return self._compact_openalex_id(value)
            if "doi.org/" in value:
                return value
            return value
        if value.startswith("10."):
            return f"doi:{value}"
        return value

    def _author_identifier(self, identifier: str) -> str:
        return self._compact_openalex_id(identifier.strip())

    def _compact_openalex_id(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        return value.replace("https://openalex.org/", "")
