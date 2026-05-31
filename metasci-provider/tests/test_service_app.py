from __future__ import annotations

import asyncio

from metasci_provider.schemas import WorksSearchServiceRequest
from metasci_provider.service import create_app


def test_service_app_exposes_health_and_search() -> None:
    app = create_app()
    assert app.title == "MetaSci Provider"
    assert "/v1/works/search" in {route.path for route in app.routes}


def test_service_search_uses_planner_and_executor() -> None:
    async def executor(request: WorksSearchServiceRequest, plan: dict[str, object]) -> dict[str, object]:
        return {
            "works": [{"id": "W1"}],
            "artifacts": {"dataset_file": "papers.json"},
            "source": "database",
            "filtered_total": 1,
            "execution_time": 0.1,
            "diagnostics": ["executor note"],
        }

    app = create_app(works_executor=executor)
    route = next(route for route in app.routes if getattr(route, "path", "") == "/v1/works/search")
    handler = route.endpoint

    response = asyncio.run(handler(WorksSearchServiceRequest(query="science", limit=10)))
    assert response.command == "works.search"
    assert response.data == [{"id": "W1"}]
    assert response.metadata["provider"] == "database"
    assert response.metadata["filtered_total"] == 1
    assert "executor note" in response.diagnostics
