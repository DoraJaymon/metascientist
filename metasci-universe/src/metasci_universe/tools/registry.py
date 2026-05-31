"""Runtime tool registry for agent-native discovery and execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from metasci_universe.schemas.analysis import (
    AnalysisReadinessRequest,
    AnalysisRecommendationRequest,
    AuthorLandscapeRequest,
    BibliometricsRequest,
    CitationOverviewRequest,
    CoWordAnalysisRequest,
    MacroAnalysisRequest,
    TopicLandscapeRequest,
    TopicModelingRequest,
)
from metasci_universe.schemas.authors import AuthorProfileRequest, AuthorSearchRequest, WorkAuthorsRequest
from metasci_universe.schemas.common import DatasetInfoRequest, MetaSciResult
from metasci_universe.schemas.conferences import ConferencePapersRequest
from metasci_universe.schemas.embeddings import EmbedWorksRequest
from metasci_universe.schemas.works import WorksGetRequest, WorksSearchRequest
from metasci_universe.storage.saved_dataset import SavedDataset


ToolHandler = Callable[[dict[str, Any]], Awaitable[MetaSciResult]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type
    handler: ToolHandler
    examples: list[str]
    required_fields: list[str] | None = None
    recommended_fetch_args: dict[str, Any] | None = None

    def to_card(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputs": self.input_model.model_json_schema(),
            "examples": self.examples,
            "required_fields": self.required_fields or [],
            "recommended_fetch_args": self.recommended_fetch_args or {},
        }


async def _works_search(payload: dict[str, Any]) -> MetaSciResult:
    from metasci_universe.api import works

    request = WorksSearchRequest(**payload)
    return await works.search(**request.model_dump())


async def _works_get(payload: dict[str, Any]) -> MetaSciResult:
    from metasci_universe.api import works

    request = WorksGetRequest(**payload)
    return await works.get(**request.model_dump())


async def _conferences_papers(payload: dict[str, Any]) -> MetaSciResult:
    from metasci_universe.api import conferences

    request = ConferencePapersRequest(**payload)
    return await conferences.papers(**request.model_dump())


async def _authors_search(payload: dict[str, Any]) -> MetaSciResult:
    from metasci_universe.api import authors

    request = AuthorSearchRequest(**payload)
    return await authors.search(**request.model_dump())


async def _authors_profile(payload: dict[str, Any]) -> MetaSciResult:
    from metasci_universe.api import authors

    request = AuthorProfileRequest(**payload)
    return await authors.profile(**request.model_dump())


async def _authors_from_work(payload: dict[str, Any]) -> MetaSciResult:
    from metasci_universe.api import authors

    request = WorkAuthorsRequest(**payload)
    return await authors.from_work(**request.model_dump())


async def _dataset_info(payload: dict[str, Any]) -> MetaSciResult:
    request = DatasetInfoRequest(**payload)
    dataset = SavedDataset.load(request.path)
    info = dataset.info()
    return MetaSciResult(
        command="dataset.info",
        input=request.model_dump(mode="json"),
        data=info,
        metadata={"record_count": info["record_count"], "schema_name": info["schema_name"]},
    )


async def _analysis_bibliometrics(payload: dict[str, Any]) -> MetaSciResult:
    from metasci_universe import analysis

    request = BibliometricsRequest(**payload)
    return await analysis.bibliometrics(**request.model_dump())


async def _analysis_author_landscape(payload: dict[str, Any]) -> MetaSciResult:
    from metasci_universe import analysis

    request = AuthorLandscapeRequest(**payload)
    return await analysis.author_landscape(**request.model_dump())


async def _analysis_inspect_readiness(payload: dict[str, Any]) -> MetaSciResult:
    from metasci_universe import analysis

    request = AnalysisReadinessRequest(**payload)
    return await analysis.inspect_readiness(**request.model_dump())


async def _analysis_recommend(payload: dict[str, Any]) -> MetaSciResult:
    from metasci_universe import analysis

    request = AnalysisRecommendationRequest(**payload)
    return await analysis.recommend(**request.model_dump())


async def _analysis_preflight(payload: dict[str, Any]) -> MetaSciResult:
    from metasci_universe import analysis

    request = AnalysisRecommendationRequest(**payload)
    return await analysis.preflight(**request.model_dump())


async def _analysis_macro(payload: dict[str, Any]) -> MetaSciResult:
    from metasci_universe import analysis

    request = MacroAnalysisRequest(**payload)
    return await analysis.macro(**request.model_dump())


async def _analysis_coword(payload: dict[str, Any]) -> MetaSciResult:
    from metasci_universe import analysis

    request = CoWordAnalysisRequest(**payload)
    return await analysis.coword(**request.model_dump())


async def _analysis_topic_modeling(payload: dict[str, Any]) -> MetaSciResult:
    from metasci_universe import analysis

    request = TopicModelingRequest(**payload)
    return await analysis.topic_modeling(**request.model_dump())


async def _analysis_topic_landscape(payload: dict[str, Any]) -> MetaSciResult:
    from metasci_universe import analysis

    request = TopicLandscapeRequest(**payload)
    return await analysis.topic_landscape(**request.model_dump())


async def _analysis_citation_overview(payload: dict[str, Any]) -> MetaSciResult:
    from metasci_universe import analysis

    request = CitationOverviewRequest(**payload)
    return await analysis.citation_overview(**request.model_dump())


async def _embeddings_embed_works(payload: dict[str, Any]) -> MetaSciResult:
    from metasci_universe import embeddings

    request = EmbedWorksRequest(**payload)
    return await embeddings.embed_works(**request.model_dump())


# ── DeepSearch (metasci-deepsearch optional integration) ─────────────────────

class _DeepSearchRequest(BaseModel):
    """Request schema for CiteFlow deep search."""

    query: str = Field(description="Natural-language research question.")
    max_papers: int = Field(default=100, ge=1, le=500, description="Max papers to return.")
    max_search_rounds: int = Field(default=3, ge=1, le=5)
    search_limit_per_round: int = Field(default=50, ge=10, le=200)
    year_upper_limit: int | None = Field(default=None, description="S2 search year upper limit.")


async def _deep_search(payload: dict[str, Any]) -> MetaSciResult:
    try:
        from metasci_deepsearch import deep_search, DeepSearchConfig
    except ImportError:
        return MetaSciResult(
            command="search.deep",
            input=payload,
            diagnostics=["metasci-deepsearch is not installed. Run: pip install -e ./metasci-deepsearch"],
        )
    request = _DeepSearchRequest(**payload)
    cfg = DeepSearchConfig(
        max_search_rounds=request.max_search_rounds,
        search_limit_per_round=request.search_limit_per_round,
        year_upper_limit=request.year_upper_limit,
    )
    result = await deep_search(request.query, config=cfg, max_papers=request.max_papers)
    return result.to_metasci_result()


TOOLS: dict[str, ToolDefinition] = {
    "embeddings.embed_works": ToolDefinition(
        name="embeddings.embed_works",
        description="Create reusable text embedding artifacts for a saved works dataset.",
        input_model=EmbedWorksRequest,
        handler=_embeddings_embed_works,
        examples=[
            "await ms.run_tool('embeddings.embed_works', {'dataset_path': 'metasci_outputs/.../papers.json', 'backend': 'spacy'})",
            "await ms.embeddings.embed_works('metasci_outputs/.../papers.json', backend='sentence_transformers')",
        ],
        required_fields=["title or abstract"],
        recommended_fetch_args={},
    ),
    "analysis.inspect_readiness": ToolDefinition(
        name="analysis.inspect_readiness",
        description="Inspect field coverage and readiness for all analysis tools on a saved works dataset.",
        input_model=AnalysisReadinessRequest,
        handler=_analysis_inspect_readiness,
        examples=[
            "await ms.run_tool('analysis.inspect_readiness', {'dataset_path': 'metasci_outputs/.../papers.json'})",
        ],
        required_fields=["title", "publication_year"],
        recommended_fetch_args={"include": ["authors", "references"]},
    ),
    "analysis.recommend": ToolDefinition(
        name="analysis.recommend",
        description="Compatibility alias for analysis.preflight.",
        input_model=AnalysisRecommendationRequest,
        handler=_analysis_recommend,
        examples=[
            "await ms.run_tool('analysis.recommend', {'dataset_path': 'metasci_outputs/.../papers.json', 'intent': 'science_landscape'})",
        ],
        required_fields=["title", "publication_year"],
        recommended_fetch_args={"include": ["authors", "references"]},
    ),
    "analysis.preflight": ToolDefinition(
        name="analysis.preflight",
        description="Inspect a saved works dataset and return runnable analysis tools, missing fields, fetch suggestions, and safe defaults.",
        input_model=AnalysisRecommendationRequest,
        handler=_analysis_preflight,
        examples=[
            "await ms.run_tool('analysis.preflight', {'dataset_path': 'metasci_outputs/.../papers.json', 'intent': 'science_landscape'})",
        ],
        required_fields=["title", "publication_year"],
        recommended_fetch_args={"include": ["authors", "references"]},
    ),
    "analysis.bibliometrics": ToolDefinition(
        name="analysis.bibliometrics",
        description="Compute bibliometric summary tables and visualizations for a saved works dataset.",
        input_model=BibliometricsRequest,
        handler=_analysis_bibliometrics,
        examples=[
            "await ms.run_tool('analysis.bibliometrics', {'dataset_path': 'metasci_outputs/.../papers.json'})",
        ],
        required_fields=["title", "publication_year", "cited_by_count"],
        recommended_fetch_args={"include": ["authors"]},
    ),
    "analysis.macro": ToolDefinition(
        name="analysis.macro",
        description="Analyze country, institution, and collaboration patterns in a saved works dataset.",
        input_model=MacroAnalysisRequest,
        handler=_analysis_macro,
        examples=[
            "await ms.run_tool('analysis.macro', {'dataset_path': 'metasci_outputs/.../papers.json'})",
        ],
        required_fields=["authors.institutions", "publication_year"],
        recommended_fetch_args={"include": ["authors"]},
    ),
    "analysis.author_landscape": ToolDefinition(
        name="analysis.author_landscape",
        description="Analyze corpus-level author productivity, roles, affiliations, topics, and coauthor networks.",
        input_model=AuthorLandscapeRequest,
        handler=_analysis_author_landscape,
        examples=[
            "await ms.run_tool('analysis.author_landscape', {'dataset_path': 'metasci_outputs/.../papers.json'})",
        ],
        required_fields=["authors"],
        recommended_fetch_args={"include": ["authors"]},
    ),
    "analysis.coword": ToolDefinition(
        name="analysis.coword",
        description="Run co-word analysis and generate term, edge, evolution, and network visualization artifacts.",
        input_model=CoWordAnalysisRequest,
        handler=_analysis_coword,
        examples=[
            "await ms.run_tool('analysis.coword', {'dataset_path': 'metasci_outputs/.../papers.json', 'text_fields': ['title', 'abstract']})",
        ],
        required_fields=["title or abstract"],
        recommended_fetch_args={},
    ),
    "analysis.topic_modeling": ToolDefinition(
        name="analysis.topic_modeling",
        description="Run topic modeling with sklearn LDA or BERTopic and save topic visualizations.",
        input_model=TopicModelingRequest,
        handler=_analysis_topic_modeling,
        examples=[
            "await ms.run_tool('analysis.topic_modeling', {'dataset_path': 'metasci_outputs/.../papers.json', 'backend': 'sklearn_lda'})",
        ],
        required_fields=["title or abstract"],
        recommended_fetch_args={},
    ),
    "analysis.topic_landscape": ToolDefinition(
        name="analysis.topic_landscape",
        description="Combine OpenAlex topics, co-word analysis, topic modeling, and temporal evolution.",
        input_model=TopicLandscapeRequest,
        handler=_analysis_topic_landscape,
        examples=[
            "await ms.run_tool('analysis.topic_landscape', {'dataset_path': 'metasci_outputs/.../papers.json'})",
        ],
        required_fields=["topics and/or title/abstract"],
        recommended_fetch_args={},
    ),
    "analysis.citation_overview": ToolDefinition(
        name="analysis.citation_overview",
        description="Summarize citation distributions and referenced-work frequencies for a works dataset.",
        input_model=CitationOverviewRequest,
        handler=_analysis_citation_overview,
        examples=[
            "await ms.run_tool('analysis.citation_overview', {'dataset_path': 'metasci_outputs/.../papers.json'})",
        ],
        required_fields=["cited_by_count"],
        recommended_fetch_args={"include": ["references"]},
    ),
    "works.search": ToolDefinition(
        name="works.search",
        description="Search scholarly works through supported providers and save a dataset artifact.",
        input_model=WorksSearchRequest,
        handler=_works_search,
        examples=[
            "await ms.run_tool('works.search', {'query': 'science of science', 'from_year': 2020})",
        ],
    ),
    "works.get": ToolDefinition(
        name="works.get",
        description="Get one scholarly work by OpenAlex ID, DOI, PMID, or URL.",
        input_model=WorksGetRequest,
        handler=_works_get,
        examples=["await ms.run_tool('works.get', {'identifier': '10.7717/peerj.4375'})"],
    ),
    "conferences.papers": ToolDefinition(
        name="conferences.papers",
        description=(
            "Retrieve accepted/proceedings papers for a CS conference/year from OpenReview, ACL Anthology, "
            "CVF, PMLR, or DBLP and save a works dataset."
        ),
        input_model=ConferencePapersRequest,
        handler=_conferences_papers,
        examples=[
            "await ms.run_tool('conferences.papers', {'venue': 'iclr', 'year': 2024, 'source': 'openreview'})",
            "await ms.run_tool('conferences.papers', {'venue': 'acl', 'year': 2024, 'source': 'acl'})",
            "await ms.run_tool('conferences.papers', {'venue': 'cvpr', 'year': 2024, 'source': 'cvf'})",
            "await ms.run_tool('conferences.papers', {'venue': 'aistats', 'year': 2024, 'source': 'pmlr'})",
        ],
    ),
    "authors.search": ToolDefinition(
        name="authors.search",
        description="Search candidate OpenAlex authors by name for disambiguation.",
        input_model=AuthorSearchRequest,
        handler=_authors_search,
        examples=["await ms.run_tool('authors.search', {'name': 'Massimo Aria', 'limit': 5})"],
    ),
    "authors.profile": ToolDefinition(
        name="authors.profile",
        description="Get an author profile by OpenAlex author ID.",
        input_model=AuthorProfileRequest,
        handler=_authors_profile,
        examples=["await ms.run_tool('authors.profile', {'identifier': 'A5069892096'})"],
    ),
    "authors.from_work": ToolDefinition(
        name="authors.from_work",
        description="Get authorship information from a DOI or OpenAlex work ID.",
        input_model=WorkAuthorsRequest,
        handler=_authors_from_work,
        examples=[
            "await ms.run_tool('authors.from_work', {'identifier': '10.1038/s41597-020-0543-2', 'all_authors': True})",
        ],
    ),
    "dataset.info": ToolDefinition(
        name="dataset.info",
        description="Inspect a saved MetaSci dataset artifact.",
        input_model=DatasetInfoRequest,
        handler=_dataset_info,
        examples=["ms.run_tool('dataset.info', {'path': 'metasci_outputs/.../papers.json'})"],
    ),
    "search.deep": ToolDefinition(
        name="search.deep",
        description=(
            "CiteFlow-based deep academic paper search. "
            "Given a natural-language research question, iteratively retrieves papers via "
            "Semantic Scholar keyword search, expands coverage through citation network "
            "exploration (OpenAlex), and ranks results by relevance, recency, and centrality. "
            "Requires OPENAI_API_KEY, OPENAI_BASE_URL, and OPENALEX_EMAIL env vars. "
            "Optional: S2_API_KEY for higher rate limits."
        ),
        input_model=_DeepSearchRequest,
        handler=_deep_search,
        examples=[
            "ms.run_tool('search.deep', {'query': 'graph neural networks for drug discovery'})",
            "ms.run_tool('search.deep', {'query': 'large language model mathematical reasoning', 'max_papers': 50})",
        ],
        required_fields=["query"],
    ),
}


def list_tools() -> list[str]:
    """List available agent tools."""
    return sorted(TOOLS)


def describe_tool(name: str) -> dict[str, Any]:
    """Return a compact tool card."""
    return _get_tool(name).to_card()


def tool_schema(name: str) -> dict[str, Any]:
    """Return the input JSON schema for a tool."""
    return _get_tool(name).input_model.model_json_schema()


async def run_tool(name: str, arguments: dict[str, Any]) -> MetaSciResult:
    """Validate and execute a registered tool by name."""
    tool = _get_tool(name)
    return await tool.handler(arguments)


def _get_tool(name: str) -> ToolDefinition:
    try:
        return TOOLS[name]
    except KeyError as exc:
        raise KeyError(f"Unknown MetaSci tool: {name}") from exc
