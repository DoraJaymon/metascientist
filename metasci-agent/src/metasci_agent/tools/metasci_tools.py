"""Direct light-agent tools over the public metasci_universe API."""

from __future__ import annotations

import json
from typing import Any

import metasci_universe as ms
from light_agent.core.tool import AsyncTool, ToolResult
from metasci_universe.schemas.authors import AuthorProfileRequest, AuthorSearchRequest, WorkAuthorsRequest
from metasci_universe.schemas.common import DatasetInfoRequest, MetaSciResult
from metasci_universe.schemas.conferences import ConferencePapersRequest
from metasci_universe.schemas.works import WorksFullTextRequest, WorksGetRequest, WorksSearchRequest


_METASCI_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {"type": "string"},
        "input": {"type": "object"},
        "artifacts": {"type": "object"},
        "metadata": {"type": "object"},
        "diagnostics": {"type": "array", "items": {"type": "string"}},
    },
}


class MetaSciSearchWorksTool(AsyncTool):
    """Search scholarly works through metasci_universe."""

    name: str = "metasci_search_works"
    description: str = (
        "Search scholarly works with MetaSci Universe. Use the default OpenAlex-backed route for "
        "topic, source, author, institution, year, and citation-sorted retrieval; use "
        "provider='sciencedirect' only for explicit ScienceDirect/Elsevier keyword retrieval. "
        "The Springer provider is DOI/URL-level only and does not support works search. "
        "Saves a reusable dataset artifact and returns artifact paths, counts, diagnostics, and "
        "a short preview."
    )
    parameters: dict = WorksSearchRequest.model_json_schema()
    output_schema: dict = _METASCI_RESULT_SCHEMA
    tags: list[str] = ["metasci", "works", "data-fetch"]

    async def forward(self, **kwargs: Any) -> ToolResult:
        try:
            result = await ms.works.search(**kwargs)
        except Exception as exc:
            return ToolResult(output=None, error=f"{self.name} failed: {exc}")
        return _to_tool_result(result, preview_key="preview_works")


class MetaSciGetWorkTool(AsyncTool):
    """Get one scholarly work through metasci_universe."""

    name: str = "metasci_get_work"
    description: str = (
        "Get metadata for one scholarly work by DOI, OpenAlex ID, PMID, URL, or ScienceDirect "
        "PII when provider='sciencedirect'. Use provider='springer' for Springer DOI or article "
        "URL metadata. Saves a small work artifact and returns the normalized record plus artifact paths."
    )
    parameters: dict = WorksGetRequest.model_json_schema()
    output_schema: dict = _METASCI_RESULT_SCHEMA
    tags: list[str] = ["metasci", "works", "data-fetch"]

    async def forward(self, **kwargs: Any) -> ToolResult:
        try:
            result = await ms.works.get(**kwargs)
        except Exception as exc:
            return ToolResult(output=None, error=f"{self.name} failed: {exc}")
        return _to_tool_result(result, preview_key="preview_work")


class MetaSciGetWorkFullTextTool(AsyncTool):
    """Fetch full-text XML for one work through metasci_universe."""

    name: str = "metasci_get_work_fulltext"
    description: str = (
        "Fetch full text for one work. ScienceDirect saves entitlement-dependent fulltext.xml; "
        "Springer saves fulltext.md, work.json, and optionally article.pdf when download_pdf=true."
    )
    parameters: dict = WorksFullTextRequest.model_json_schema()
    output_schema: dict = _METASCI_RESULT_SCHEMA
    tags: list[str] = ["metasci", "works", "fulltext", "data-fetch"]

    async def forward(self, **kwargs: Any) -> ToolResult:
        try:
            result = await ms.works.fulltext(**kwargs)
        except Exception as exc:
            return ToolResult(output=None, error=f"{self.name} failed: {exc}")
        return _to_tool_result(result, preview_key="fulltext")


class MetaSciFetchConferencePapersTool(AsyncTool):
    """Fetch accepted conference papers through metasci_universe."""

    name: str = "metasci_fetch_conference_papers"
    description: str = (
        "Retrieve accepted papers for a CS conference/year from OpenReview, ACL Anthology, CVF, "
        "PMLR, or DBLP. Saves a reusable works dataset and returns artifact paths, counts, "
        "diagnostics, and a short preview."
    )
    parameters: dict = ConferencePapersRequest.model_json_schema()
    output_schema: dict = _METASCI_RESULT_SCHEMA
    tags: list[str] = ["metasci", "conferences", "works", "data-fetch"]

    async def forward(self, **kwargs: Any) -> ToolResult:
        try:
            result = await ms.conferences.papers(**kwargs)
        except Exception as exc:
            return ToolResult(output=None, error=f"{self.name} failed: {exc}")
        return _to_tool_result(result, preview_key="preview_works")


class MetaSciSearchAuthorsTool(AsyncTool):
    """Search candidate authors through metasci_universe."""

    name: str = "metasci_search_authors"
    description: str = (
        "Search OpenAlex author candidates by name for disambiguation. Use this before author "
        "filtered paper retrieval when a name may refer to multiple people."
    )
    parameters: dict = AuthorSearchRequest.model_json_schema()
    output_schema: dict = _METASCI_RESULT_SCHEMA
    tags: list[str] = ["metasci", "authors", "data-fetch"]

    async def forward(self, **kwargs: Any) -> ToolResult:
        try:
            result = await ms.authors.search(**kwargs)
        except Exception as exc:
            return ToolResult(output=None, error=f"{self.name} failed: {exc}")
        return _to_tool_result(result, preview_key="preview_authors")


class MetaSciGetAuthorProfileTool(AsyncTool):
    """Get one author profile through metasci_universe."""

    name: str = "metasci_get_author_profile"
    description: str = (
        "Get a single author profile by OpenAlex author ID or URL. Use after author search "
        "when detailed author metadata is needed."
    )
    parameters: dict = AuthorProfileRequest.model_json_schema()
    output_schema: dict = _METASCI_RESULT_SCHEMA
    tags: list[str] = ["metasci", "authors", "data-fetch"]

    async def forward(self, **kwargs: Any) -> ToolResult:
        try:
            result = await ms.authors.profile(**kwargs)
        except Exception as exc:
            return ToolResult(output=None, error=f"{self.name} failed: {exc}")
        return _to_tool_result(result, preview_key="preview_author")


class MetaSciGetWorkAuthorsTool(AsyncTool):
    """Get authorship data for a work through metasci_universe."""

    name: str = "metasci_get_work_authors"
    description: str = (
        "Get author information from a DOI, OpenAlex work ID, PMID, or URL. Use this to fetch "
        "first author, a specific author position, or all summary authors for a paper."
    )
    parameters: dict = WorkAuthorsRequest.model_json_schema()
    output_schema: dict = _METASCI_RESULT_SCHEMA
    tags: list[str] = ["metasci", "authors", "works", "data-fetch"]

    async def forward(self, **kwargs: Any) -> ToolResult:
        try:
            result = await ms.authors.from_work(**kwargs)
        except Exception as exc:
            return ToolResult(output=None, error=f"{self.name} failed: {exc}")
        return _to_tool_result(result, preview_key="preview_authors")


class MetaSciDatasetInfoTool(AsyncTool):
    """Inspect a saved MetaSci dataset artifact."""

    name: str = "metasci_dataset_info"
    description: str = (
        "Inspect a saved MetaSci dataset artifact path or artifact directory. Use after a data "
        "fetch when record counts, schema name, diagnostics, or metadata need to be confirmed."
    )
    parameters: dict = DatasetInfoRequest.model_json_schema()
    output_schema: dict = _METASCI_RESULT_SCHEMA
    tags: list[str] = ["metasci", "storage"]

    async def forward(self, **kwargs: Any) -> ToolResult:
        try:
            request = DatasetInfoRequest(**kwargs)
            dataset = ms.SavedDataset.load(request.path)
            info = dataset.info()
            result = MetaSciResult(
                command="dataset.info",
                input=request.model_dump(mode="json"),
                data=info,
                metadata={
                    "record_count": info["record_count"],
                    "schema_name": info["schema_name"],
                },
                diagnostics=info.get("diagnostics", []),
            )
        except Exception as exc:
            return ToolResult(output=None, error=f"{self.name} failed: {exc}")
        return _to_tool_result(result, preview_key="dataset_info")


def metasci_agent_tools(*, include_dataset_info: bool = True) -> list[AsyncTool]:
    """Return the direct MetaSci tools intended for a ReAct agent."""
    tools: list[AsyncTool] = [
        MetaSciSearchWorksTool(),
        MetaSciGetWorkTool(),
        MetaSciGetWorkFullTextTool(),
        MetaSciFetchConferencePapersTool(),
        MetaSciSearchAuthorsTool(),
        MetaSciGetAuthorProfileTool(),
        MetaSciGetWorkAuthorsTool(),
    ]
    if include_dataset_info:
        tools.append(MetaSciDatasetInfoTool())
    return tools


def get_metasci_agent_tool(name: str) -> AsyncTool:
    """Return one direct MetaSci light-agent tool by name."""
    for tool in metasci_agent_tools():
        if tool.name == name:
            return tool
    raise KeyError(f"Unknown MetaSci agent tool: {name}")


def list_metasci_agent_tool_names() -> list[str]:
    """List direct MetaSci light-agent tool names."""
    return sorted(tool.name for tool in metasci_agent_tools())


def _to_tool_result(result: MetaSciResult, *, preview_key: str) -> ToolResult:
    payload = result.to_dict()
    display = _format_metasci_result(payload)
    structured = _compact_structured_output(payload, preview_key=preview_key)
    return ToolResult(
        output=display,
        structured_output=structured,
        display_text=display,
        artifacts=payload.get("artifacts") or None,
        metadata=payload.get("metadata") or None,
    )


def _compact_structured_output(payload: dict[str, Any], *, preview_key: str) -> dict[str, Any]:
    metadata = payload.get("metadata") or {}
    compact_metadata = {
        key: metadata[key]
        for key in (
            "provider",
            "returned_count",
            "filtered_total",
            "record_count",
            "schema_name",
        )
        if key in metadata
    }

    structured: dict[str, Any] = {
        "command": payload.get("command"),
        "input": payload.get("input") or {},
        "artifacts": payload.get("artifacts") or {},
        "metadata": compact_metadata,
        "diagnostics": payload.get("diagnostics") or [],
    }

    preview = _preview(payload.get("data"))
    if preview is not None:
        structured[preview_key] = preview

    return structured


def _format_metasci_result(payload: dict[str, Any]) -> str:
    lines = [f"command: {payload.get('command')}"]
    metadata = payload.get("metadata") or {}
    if metadata.get("returned_count") is not None:
        lines.append(f"returned_count: {metadata['returned_count']}")
    if metadata.get("filtered_total") is not None:
        lines.append(f"filtered_total: {metadata['filtered_total']}")
    if metadata.get("provider"):
        lines.append(f"provider: {metadata['provider']}")

    artifacts = payload.get("artifacts") or {}
    for key, value in artifacts.items():
        lines.append(f"{key}: {value}")

    diagnostics = payload.get("diagnostics") or []
    if diagnostics:
        lines.append("diagnostics:")
        for item in diagnostics:
            lines.append(f"- {item}")

    data = payload.get("data")
    if isinstance(data, list):
        lines.append(f"data_items: {len(data)}")
        if data:
            lines.append("preview:")
            lines.append(json.dumps(data[:3], ensure_ascii=False, indent=2))
    elif data is not None:
        lines.append("data:")
        lines.append(json.dumps(data, ensure_ascii=False, indent=2))

    return "\n".join(lines)


def _preview(data: Any, *, limit: int = 3) -> Any:
    if data is None:
        return None
    if isinstance(data, list):
        return data[:limit]
    return data
