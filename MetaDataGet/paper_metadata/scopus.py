from __future__ import annotations

import os
from typing import Any

from .http import request_json


SCOPUS_SEARCH_URL = "https://api.elsevier.com/content/search/scopus"
SCOPUS_ABSTRACT_URL = "https://api.elsevier.com/content/abstract"


class ScopusClient:
    """Small client for Elsevier Scopus Search and Abstract Retrieval APIs."""

    def __init__(
        self,
        api_key: str | None = None,
        inst_token: str | None = None,
        search_url: str = SCOPUS_SEARCH_URL,
        abstract_url: str = SCOPUS_ABSTRACT_URL,
    ) -> None:
        self.api_key = api_key or os.getenv("ELSEVIER_API_KEY") or os.getenv("SCOPUS_API_KEY")
        if not self.api_key:
            raise ValueError("Set ELSEVIER_API_KEY or SCOPUS_API_KEY for Scopus access.")
        self.inst_token = inst_token or os.getenv("ELSEVIER_INST_TOKEN") or os.getenv("SCOPUS_INST_TOKEN")
        self.search_url = search_url
        self.abstract_url = abstract_url.rstrip("/")

    @property
    def headers(self) -> dict[str, str]:
        headers = {"X-ELS-APIKey": self.api_key}
        if self.inst_token:
            headers["X-ELS-Insttoken"] = self.inst_token
        return headers

    def search(
        self,
        query: str,
        *,
        count: int = 10,
        start: int = 0,
        view: str = "STANDARD",
        sort: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "query": query,
            "count": count,
            "start": start,
            "view": view,
            "sort": sort,
        }
        return request_json(self.search_url, headers=self.headers, params=params)

    def get_abstract(
        self,
        identifier: str,
        *,
        id_type: str = "doi",
        view: str = "FULL",
    ) -> dict[str, Any]:
        id_type = id_type.lower()
        if id_type not in {"doi", "eid", "scopus_id", "pii", "pubmed_id"}:
            raise ValueError("id_type must be one of doi, eid, scopus_id, pii, pubmed_id.")
        params = {"view": view}
        return request_json(
            f"{self.abstract_url}/{id_type}/{identifier}",
            headers=self.headers,
            params=params,
        )

    def get_by_doi(self, doi: str, *, view: str = "FULL") -> dict[str, Any]:
        return self.get_abstract(doi, id_type="doi", view=view)


def extract_scopus_records(response: dict[str, Any]) -> list[dict[str, Any]]:
    entries = response.get("search-results", {}).get("entry", [])
    return entries if isinstance(entries, list) else []
