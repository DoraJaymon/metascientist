"""Contracts for conference-paper retrieval."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ConferenceSourceName = Literal["auto", "openreview", "dblp", "acl", "cvf", "pmlr"]
ConferencePaperStatus = Literal["accepted"]


class ConferencePapersRequest(BaseModel):
    """Retrieve papers from a named conference/year entry point."""

    model_config = ConfigDict(extra="forbid")

    venue: str = Field(description="Conference acronym or venue label, e.g. iclr, neurips, cvpr.")
    year: int = Field(ge=1900, le=2100)
    source: ConferenceSourceName = Field(default="auto", description="Conference data source to query.")
    status: ConferencePaperStatus = Field(default="accepted", description="Current scope is proceedings/accepted papers.")
    openreview_venue_id: str | None = Field(
        default=None,
        description="Explicit OpenReview venue id, e.g. ICLR.cc/2024/Conference.",
    )
    source_collection_id: str | None = Field(
        default=None,
        description="Source-specific collection id, e.g. a PMLR volume id or ACL Anthology proceedings slug.",
    )
    query: str | None = Field(default=None, description="Optional title/metadata query within the venue source.")
    limit: int = Field(default=100, gt=0, le=10000)
    include_raw: bool = Field(default=False, description="Include raw provider payloads for debugging/provenance.")
    output_dir: str | None = Field(default=None, description="Directory for saved dataset artifacts.")

    @field_validator("venue")
    @classmethod
    def normalize_venue(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("venue cannot be empty")
        return normalized

    @field_validator("openreview_venue_id")
    @classmethod
    def normalize_openreview_venue_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("source_collection_id")
    @classmethod
    def normalize_source_collection_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
