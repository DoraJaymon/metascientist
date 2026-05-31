"""Private service request/response contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from metasci_universe.schemas.works import WorksGetRequest, WorksSearchRequest as PublicWorksSearchRequest
from metasci_universe.schemas.authors import AuthorProfileRequest, AuthorSearchRequest, WorkAuthorsRequest


ProviderRoute = Literal["auto", "api", "database"]


class WorkQueryPlan(BaseModel):
    """Structured execution plan for works search."""

    model_config = ConfigDict(extra="forbid")

    route: ProviderRoute = "auto"
    count_route: Literal["auto", "api", "database", "fact", "none"] = "auto"
    dominant_filter: Literal["keyword", "source_year", "topic_year", "author", "institution", "mixed"] = "mixed"
    use_source_fact: bool = False
    use_topic_fact: bool = False
    use_api_count: bool = False
    use_db_count: bool = False
    use_db_fetch: bool = False
    use_api_fetch: bool = False
    candidate_filters: list[str] = Field(default_factory=list)
    secondary_filters: list[str] = Field(default_factory=list)
    include: list[str] = Field(default_factory=list)
    include_raw: list[str] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class WorksSearchServiceRequest(PublicWorksSearchRequest):
    """Private service request that reuses the public works schema."""

    model_config = ConfigDict(extra="forbid")
    use_unbounded: bool = False
    allow_db_count: bool = True
    allow_api_fallback: bool = True

    @model_validator(mode="after")
    def validate_private_flags(self) -> "WorksSearchServiceRequest":
        return self


class WorksServiceResponse(BaseModel):
    """Structured response returned by the private service."""

    model_config = ConfigDict(extra="forbid")

    command: str
    input: dict[str, Any]
    data: Any = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[str] = Field(default_factory=list)
    plan: dict[str, Any] | None = None


class AuthorsServiceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str
    input: dict[str, Any]
    data: Any = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[str] = Field(default_factory=list)


__all__ = [
    "AuthorProfileRequest",
    "AuthorSearchRequest",
    "AuthorsServiceResponse",
    "WorkAuthorsRequest",
    "WorkQueryPlan",
    "WorksGetRequest",
    "WorksSearchServiceRequest",
    "WorksServiceResponse",
]
