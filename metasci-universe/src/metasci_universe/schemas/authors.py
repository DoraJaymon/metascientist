"""Contracts for author lookup."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DetailLevel = Literal["summary", "full"]
AuthorProviderName = Literal["auto", "openalex", "service"]
WorkAuthorsProviderName = Literal["auto", "openalex", "sciencedirect", "springer", "service"]


class AuthorSearchRequest(BaseModel):
    """Search candidate authors by name."""

    model_config = ConfigDict(extra="forbid")

    name: str
    limit: int = Field(default=10, gt=0, le=200)
    detail_level: DetailLevel = "summary"
    provider: AuthorProviderName = "auto"
    output_dir: str | None = None


class AuthorProfileRequest(BaseModel):
    """Get a single author profile by OpenAlex author ID or URL."""

    model_config = ConfigDict(extra="forbid")

    identifier: str
    detail_level: DetailLevel = "full"
    provider: AuthorProviderName = "auto"
    output_dir: str | None = None


class WorkAuthorsRequest(BaseModel):
    """Get authorship information from a DOI or OpenAlex work ID."""

    model_config = ConfigDict(extra="forbid")

    identifier: str
    author_position: int = Field(default=1, gt=0)
    all_authors: bool = False
    detail_level: DetailLevel = "summary"
    provider: WorkAuthorsProviderName = "auto"
    output_dir: str | None = None

    @model_validator(mode="after")
    def validate_detail_level(self) -> "WorkAuthorsRequest":
        if self.all_authors and self.detail_level == "full":
            raise ValueError(
                "Avoid all_authors with detail_level='full'; request summary authors first, "
                "then profile specific author IDs."
            )
        return self
