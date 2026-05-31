"""Contracts for scholarly work retrieval."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ProviderName = Literal["auto", "openalex", "service"]
SortBy = Literal[
    "cited_by_count:desc",
    "publication_date:desc",
    "publication_year:desc",
    "publication_year:asc",
    "relevance_score:desc",
]
WorkInclude = Literal["authors", "references"]


class WorksSearchRequest(BaseModel):
    """Search works across supported providers."""

    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(default=None, description="Keyword/full-text search query.")
    topic_name: str | None = Field(default=None, description="OpenAlex topic-like name to resolve.")
    source_name: str | None = Field(default=None, description="Journal, conference, or venue name to resolve.")
    author_name: str | None = Field(default=None, description="Author name to resolve.")
    institution_name: str | None = Field(default=None, description="Institution name to resolve.")
    topic_id: str | None = Field(default=None, description="OpenAlex topic ID.")
    source_id: str | None = Field(default=None, description="OpenAlex source ID.")
    author_id: str | None = Field(default=None, description="OpenAlex author ID.")
    institution_id: str | None = Field(default=None, description="OpenAlex institution ID.")
    from_year: int | None = Field(default=None, ge=1800)
    to_year: int | None = Field(default=None, ge=1800)
    country_code: str | None = Field(default=None, description="Author institution country code, e.g. US or CN.")
    work_type: str | None = Field(default="article", description="OpenAlex work type filter; set to None for any type.")
    is_oa: bool | None = Field(default=None, description="Filter by Open Access status.")
    min_cited_by_count: int | None = Field(default=None, ge=0)
    max_cited_by_count: int | None = Field(default=None, ge=0)
    limit: int = Field(default=100, gt=0, le=10000)
    sort_by: SortBy = "cited_by_count:desc"
    include: list[WorkInclude] = Field(default_factory=list)
    include_raw: list[str] = Field(default_factory=list)
    provider: ProviderName = "auto"
    output_dir: str | None = Field(default=None, description="Directory for saved dataset artifacts.")

    @field_validator("include")
    @classmethod
    def deduplicate_include(cls, value: list[WorkInclude]) -> list[WorkInclude]:
        return sorted(set(value))

    @field_validator("include_raw")
    @classmethod
    def deduplicate_include_raw(cls, value: list[str]) -> list[str]:
        return sorted({item for item in value if item})

    @field_validator("country_code")
    @classmethod
    def normalize_country_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        return normalized or None

    @field_validator("work_type")
    @classmethod
    def normalize_work_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        return normalized or None

    @model_validator(mode="after")
    def validate_constraints(self) -> "WorksSearchRequest":
        if self.from_year is not None and self.to_year is not None and self.from_year > self.to_year:
            raise ValueError("from_year cannot be greater than to_year")
        if (
            self.min_cited_by_count is not None
            and self.max_cited_by_count is not None
            and self.min_cited_by_count > self.max_cited_by_count
        ):
            raise ValueError("min_cited_by_count cannot be greater than max_cited_by_count")

        has_constraint = any(
            [
                self.query,
                self.topic_name,
                self.source_name,
                self.author_name,
                self.institution_name,
                self.topic_id,
                self.source_id,
                self.author_id,
                self.institution_id,
                self.from_year,
                self.to_year,
                self.country_code,
                self.is_oa is not None,
                self.min_cited_by_count is not None,
                self.max_cited_by_count is not None,
            ]
        )
        if not has_constraint:
            raise ValueError("works.search requires at least one search or filter constraint")
        return self


class WorksGetRequest(BaseModel):
    """Get one work by OpenAlex ID, DOI, PMID, or URL."""

    model_config = ConfigDict(extra="forbid")

    identifier: str
    provider: ProviderName = "auto"
    output_dir: str | None = None
