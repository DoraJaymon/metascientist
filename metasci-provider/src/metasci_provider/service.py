"""Private MetaSci HTTP service skeleton."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, FastAPI

from metasci_provider.planner import plan_works_search
from metasci_provider.schemas import (
    AuthorsServiceResponse,
    AuthorProfileRequest,
    AuthorSearchRequest,
    WorkAuthorsRequest,
    WorksGetRequest,
    WorksSearchServiceRequest,
    WorksServiceResponse,
)


def _default_executor() -> Callable[[WorksSearchServiceRequest, dict[str, Any]], Any]:
    async def _executor(request: WorksSearchServiceRequest, plan: dict[str, Any]) -> dict[str, Any]:
        return {
            "works": [],
            "plan": plan,
            "source": request.provider,
            "execution_time": 0,
            "filtered_total": None,
        }

    return _executor


def create_app(*, works_executor: Callable[[WorksSearchServiceRequest, dict[str, Any]], Any] | None = None) -> FastAPI:
    app = FastAPI(
        title="MetaSci Provider",
        version="0.1.0",
        description="Private MetaSci retrieval service for DB-backed and API-assisted queries.",
    )
    executor = works_executor or _default_executor()

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "service": "metasci-provider"}

    @app.post("/v1/works/search")
    async def search_works(request: WorksSearchServiceRequest) -> WorksServiceResponse:
        plan_result = plan_works_search(request)
        result = await executor(request, plan_result.plan.model_dump(mode="json"))
        return WorksServiceResponse(
            command="works.search",
            input=request.model_dump(mode="json"),
            data=result.get("works", []),
            artifacts=result.get("artifacts", {}),
            metadata={
                "provider": result.get("source", request.provider),
                "filtered_total": result.get("filtered_total"),
                "execution_time": result.get("execution_time"),
            },
            diagnostics=list(result.get("diagnostics", [])) + list(plan_result.plan.diagnostics),
            plan=plan_result.plan.model_dump(mode="json"),
        )

    @app.post("/v1/works/get")
    async def get_work(request: WorksGetRequest) -> WorksServiceResponse:
        return WorksServiceResponse(
            command="works.get",
            input=request.model_dump(mode="json"),
            data=[],
            metadata={"provider": "database"},
            diagnostics=["works.get is stubbed in the private service skeleton"],
        )

    @app.post("/v1/authors/search")
    async def search_authors(request: AuthorSearchRequest) -> AuthorsServiceResponse:
        return AuthorsServiceResponse(
            command="authors.search",
            input=request.model_dump(mode="json"),
            data=[],
            metadata={"provider": "database"},
            diagnostics=["authors.search is stubbed in the private service skeleton"],
        )

    @app.post("/v1/authors/profile")
    async def profile_author(request: AuthorProfileRequest) -> AuthorsServiceResponse:
        return AuthorsServiceResponse(
            command="authors.profile",
            input=request.model_dump(mode="json"),
            data={},
            metadata={"provider": "database"},
            diagnostics=["authors.profile is stubbed in the private service skeleton"],
        )

    @app.post("/v1/authors/from-work")
    async def authors_from_work(request: WorkAuthorsRequest) -> AuthorsServiceResponse:
        return AuthorsServiceResponse(
            command="authors.from_work",
            input=request.model_dump(mode="json"),
            data=[],
            metadata={"provider": "database"},
            diagnostics=["authors.from_work is stubbed in the private service skeleton"],
        )

    return app
