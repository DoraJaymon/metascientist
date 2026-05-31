from __future__ import annotations

import os
from typing import Any

from .http import request_json


DEFAULT_WOS_BASE_URL = "https://api.clarivate.com/apis/wos-starter/v1"


class WebOfScienceClient:
    """Small client for the Clarivate Web of Science Starter API."""

    def __init__(self, api_key: str | None = None, base_url: str = DEFAULT_WOS_BASE_URL) -> None:
        self.api_key = api_key or os.getenv("CLARIVATE_API_KEY") or os.getenv("WOS_API_KEY")
        if not self.api_key:
            raise ValueError("Set CLARIVATE_API_KEY or WOS_API_KEY for Web of Science access.")
        self.base_url = base_url.rstrip("/")

    @property
    def headers(self) -> dict[str, str]:
        return {"X-ApiKey": self.api_key}

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        page: int = 1,
        db: str = "WOS",
        sort_field: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "db": db,
            "q": query,
            "limit": limit,
            "page": page,
            "sortField": sort_field,
        }
        return request_json(f"{self.base_url}/documents", headers=self.headers, params=params)

    def get_by_uid(self, uid: str, *, db: str = "WOS") -> dict[str, Any]:
        return request_json(
            f"{self.base_url}/documents/{uid}",
            headers=self.headers,
            params={"db": db},
        )

    def get_by_doi(self, doi: str, *, limit: int = 5, db: str = "WOS") -> dict[str, Any]:
        return self.search(f'DO="{doi}"', limit=limit, db=db)


def extract_wos_records(response: dict[str, Any]) -> list[dict[str, Any]]:
    records = response.get("hits")
    if isinstance(records, list):
        return records
    records = response.get("Data", {}).get("Records", {}).get("records", {}).get("REC")
    if isinstance(records, list):
        return records
    if isinstance(records, dict):
        return [records]
    return []
