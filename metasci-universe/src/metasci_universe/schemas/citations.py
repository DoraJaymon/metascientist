"""Contracts for citation graph lookup."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CitationProvider = Literal["auto", "openalex"]


class CitationLookupRequest(BaseModel):
    """Resolve one paper and fetch its references, citations, or both."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, description="Paper title.")
    doi: str | None = Field(default=None, description="DOI, with or without https://doi.org/.")
    arxiv_id: str | None = Field(default=None, description="arXiv identifier, with or without arXiv: prefix.")
    openalex_id: str | None = Field(default=None, description="OpenAlex work ID, e.g. W123 or URL.")
    s2_id: str | None = Field(default=None, description="Semantic Scholar paperId.")
    s2_corpus_id: str | None = Field(default=None, description="Semantic Scholar CorpusId.")
    provider: CitationProvider = "auto"
    limit: int = Field(default=1000, gt=0, le=1000)
    year_start: int | None = Field(default=None, ge=1800)
    year_end: int | None = Field(default=None, ge=1800)
    min_citations: int = Field(default=0, ge=0)

    @field_validator("title", "doi", "arxiv_id", "openalex_id", "s2_id", "s2_corpus_id")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def validate_identity_and_dates(self) -> "CitationLookupRequest":
        if not any([self.title, self.doi, self.arxiv_id, self.openalex_id, self.s2_id, self.s2_corpus_id]):
            raise ValueError("Provide at least one paper identifier: title, doi, arxiv_id, openalex_id, s2_id, or s2_corpus_id")
        if self.year_start is not None and self.year_end is not None and self.year_start > self.year_end:
            raise ValueError("year_start cannot be greater than year_end")
        return self


class CitationResolveRequest(BaseModel):
    """Resolve one paper identity without fetching citation edges."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    openalex_id: str | None = None
    s2_id: str | None = None
    s2_corpus_id: str | None = None
    provider: CitationProvider = "auto"

    @field_validator("title", "doi", "arxiv_id", "openalex_id", "s2_id", "s2_corpus_id")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def validate_identity(self) -> "CitationResolveRequest":
        if not any([self.title, self.doi, self.arxiv_id, self.openalex_id, self.s2_id, self.s2_corpus_id]):
            raise ValueError("Provide at least one paper identifier: title, doi, arxiv_id, openalex_id, s2_id, or s2_corpus_id")
        return self
