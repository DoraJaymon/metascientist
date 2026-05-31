"""Combined topic landscape analysis."""

from __future__ import annotations

from collections import Counter
from typing import Any

from metasci_universe.analysis import _normalize as norm
from metasci_universe.analysis._artifacts import save_analysis_artifacts
from metasci_universe.analysis._dataset import load_records
from metasci_universe.analysis._viz import bar, line, stacked_area, wide_matrix
from metasci_universe.analysis.coword import compute_coword
from metasci_universe.analysis.topic_modeling import compute_topic_modeling
from metasci_universe.schemas.analysis import CoWordAnalysisRequest, TopicLandscapeRequest, TopicModelingRequest
from metasci_universe.schemas.common import MetaSciResult


async def topic_landscape(
    dataset_path: str,
    *,
    methods: list[str] | None = None,
    top_n: int = 30,
    min_count: int = 2,
    include_evolution: bool = True,
    year_field: str = "publication_year",
    text_fields: list[str] | None = None,
    text_backend: str = "spacy",
    language: str = "en",
    spacy_model: str | None = None,
    lemmatize: bool = True,
    ngram_min: int = 1,
    ngram_max: int = 2,
    selected_topics: list[str] | None = None,
    selected_terms: list[str] | None = None,
    modeling_backend: str = "embedding_kmeans",
    nr_topics: int | None = None,
    max_docs: int | None = None,
    max_features: int = 5000,
    output_dir: str | None = None,
) -> MetaSciResult:
    """Analyze topic landscape using OpenAlex topics, co-word analysis, and topic modeling."""
    request = TopicLandscapeRequest(
        dataset_path=dataset_path,
        methods=methods or ["openalex_topics", "coword", "topic_modeling"],
        top_n=top_n,
        min_count=min_count,
        include_evolution=include_evolution,
        year_field=year_field,
        text_fields=text_fields or ["title", "abstract"],
        text_backend=text_backend,  # type: ignore[arg-type]
        language=language,
        spacy_model=spacy_model,
        lemmatize=lemmatize,
        ngram_min=ngram_min,
        ngram_max=ngram_max,
        selected_topics=selected_topics,
        selected_terms=selected_terms,
        modeling_backend=modeling_backend,  # type: ignore[arg-type]
        nr_topics=nr_topics,
        max_docs=max_docs,
        max_features=max_features,
        output_dir=output_dir,
    )
    records, dataset_metadata, resolved_path = load_records(request.dataset_path)
    data, diagnostics = _compute_topic_landscape(records, request)
    input_payload = request.model_dump(mode="json")
    artifacts = save_analysis_artifacts(
        command="analysis.topic_landscape",
        input_payload=input_payload,
        data=data,
        summary_markdown=_summary_markdown(data, resolved_path=resolved_path, diagnostics=diagnostics),
        tables={
            "openalex_topics": data.get("openalex_topics", {}).get("topics", []),
            "openalex_topic_by_year": data.get("openalex_topics", {}).get("topic_by_year", []),
            "openalex_topic_by_year_matrix": data.get("openalex_topics", {}).get("topic_by_year_matrix", []),
            "coword_terms": data.get("coword", {}).get("terms", []),
            "coword_edges": data.get("coword", {}).get("edges", []),
            "coword_term_by_year_matrix": data.get("coword", {}).get("term_by_year_matrix", []),
            "modeled_topics": data.get("topic_modeling", {}).get("topics", []),
            "modeled_topic_by_year": data.get("topic_modeling", {}).get("topic_by_year", []),
            "modeled_topic_by_year_matrix": data.get("topic_modeling", {}).get("topic_by_year_matrix", []),
        },
        figures=_figures(data),
        output_dir=request.output_dir,
        diagnostics=diagnostics,
    )
    return MetaSciResult(
        command="analysis.topic_landscape",
        input=input_payload,
        data=data,
        artifacts=artifacts,
        metadata={
            "record_count": len(records),
            "dataset_path": resolved_path,
            "dataset_schema": dataset_metadata.get("schema_name"),
            "methods": request.methods,
        },
        diagnostics=diagnostics,
    )


def _compute_topic_landscape(
    works: list[dict[str, Any]],
    request: TopicLandscapeRequest,
) -> tuple[dict[str, Any], list[str]]:
    diagnostics: list[str] = []
    data: dict[str, Any] = {
        "overview": {
            "total_papers": len(works),
            "methods": request.methods,
        }
    }

    if "openalex_topics" in request.methods:
        openalex_data, openalex_diagnostics = _compute_openalex_topics(works, request)
        data["openalex_topics"] = openalex_data
        diagnostics.extend(openalex_diagnostics)

    if "coword" in request.methods:
        coword_request = CoWordAnalysisRequest(
            dataset_path=request.dataset_path,
            text_fields=request.text_fields,
            text_backend=request.text_backend,
            language=request.language,
            spacy_model=request.spacy_model,
            lemmatize=request.lemmatize,
            ngram_min=request.ngram_min,
            ngram_max=request.ngram_max,
            min_term_count=request.min_count,
            min_edge_weight=request.min_count,
            top_terms=max(request.top_n, 100),
            top_edges=300,
            selected_terms=request.selected_terms,
            include_evolution=request.include_evolution,
            year_field=request.year_field,
        )
        coword_data, coword_diagnostics = compute_coword(works, coword_request)
        data["coword"] = coword_data
        diagnostics.extend(coword_diagnostics)

    if "topic_modeling" in request.methods:
        modeling_request = TopicModelingRequest(
            dataset_path=request.dataset_path,
            backend=request.modeling_backend,
            text_fields=request.text_fields,
            text_backend=request.text_backend,
            language=request.language,
            spacy_model=request.spacy_model,
            lemmatize=request.lemmatize,
            nr_topics=request.nr_topics,
            max_docs=request.max_docs,
            max_features=request.max_features,
            include_evolution=request.include_evolution,
            year_field=request.year_field,
        )
        modeling_data, modeling_diagnostics = compute_topic_modeling(works, modeling_request)
        data["topic_modeling"] = modeling_data
        diagnostics.extend(modeling_diagnostics)

    return data, diagnostics


def _compute_openalex_topics(
    works: list[dict[str, Any]],
    request: TopicLandscapeRequest,
) -> tuple[dict[str, Any], list[str]]:
    diagnostics: list[str] = []
    topic_counter: Counter[str] = Counter()
    topic_scores: dict[str, list[float]] = {}
    topic_names: dict[str, str] = {}
    topic_year_counter: Counter[tuple[int, str]] = Counter()
    topic_citations: Counter[str] = Counter()

    for work in works:
        publication_year = norm.year(work, request.year_field)
        for topic in norm.topics(work):
            topic_id = topic.get("id") or topic.get("name")
            if not topic_id:
                continue
            topic_counter[topic_id] += 1
            topic_names[topic_id] = topic.get("name") or topic_id
            topic_scores.setdefault(topic_id, []).append(float(topic.get("score") or 0))
            topic_citations[topic_id] += norm.citations(work)
            if publication_year is not None and request.include_evolution:
                topic_year_counter[(publication_year, topic_id)] += 1

    if not topic_counter:
        diagnostics.append("No OpenAlex topics found in the dataset.")

    topics = []
    for topic_id, count in topic_counter.most_common():
        if count < request.min_count:
            continue
        scores = topic_scores.get(topic_id) or []
        topics.append(
            {
                "id": topic_id,
                "name": topic_names.get(topic_id, topic_id),
                "frequency": count,
                "percentage": round(count / len(works) * 100, 3) if works else 0,
                "avg_score": round(sum(scores) / len(scores), 4) if scores else 0,
                "total_citations": topic_citations[topic_id],
                "avg_citations": round(topic_citations[topic_id] / count, 3) if count else 0,
            }
        )
        if len(topics) >= request.top_n:
            break

    selected = set(request.selected_topics or [])
    selected_lower = {item.lower() for item in selected}
    top_topic_ids = {row["id"] for row in topics}
    top_topic_ids.update(
        topic_id
        for topic_id, name in topic_names.items()
        if topic_id in selected or name.lower() in selected_lower
    )
    topic_by_year = [
        {
            "year": year,
            "topic_id": topic_id,
            "topic": topic_names.get(topic_id, topic_id),
            "count": count,
        }
        for (year, topic_id), count in sorted(topic_year_counter.items())
        if topic_id in top_topic_ids
    ]
    topic_by_year_matrix = wide_matrix(topic_by_year, index="year", columns="topic", values="count")
    return (
        {
            "overview": {
                "topic_count": len(topic_counter),
                "topics_returned": len(topics),
            },
            "topics": topics,
            "topic_by_year": topic_by_year,
            "topic_by_year_matrix": topic_by_year_matrix,
        },
        diagnostics,
    )


def _figures(data: dict[str, Any]) -> dict[str, Any]:
    figures: dict[str, Any] = {}
    openalex_topics = data.get("openalex_topics") or {}
    if openalex_topics:
        figures["openalex_topics"] = bar(
            list(reversed(openalex_topics.get("topics", [])[:30])),
            x="frequency",
            y="name",
            title="OpenAlex Topic Frequencies",
            orientation="h",
        )
        figures["openalex_topic_evolution"] = line(
            openalex_topics.get("topic_by_year", []),
            x="year",
            y="count",
            color="topic",
            title="OpenAlex Topic Evolution",
        )
        figures["openalex_topic_evolution_stacked"] = stacked_area(
            openalex_topics.get("topic_by_year", []),
            x="year",
            y="count",
            color="topic",
            title="OpenAlex Topic Evolution",
        )
    coword = data.get("coword") or {}
    if coword:
        figures["coword_terms"] = bar(
            list(reversed(coword.get("terms", [])[:30])),
            x="count",
            y="term",
            title="Co-Word Terms",
            orientation="h",
        )
        figures["coword_term_evolution_stacked"] = stacked_area(
            coword.get("term_by_year", []),
            x="year",
            y="count",
            color="term",
            title="Co-Word Term Evolution",
        )
    modeling = data.get("topic_modeling") or {}
    if modeling:
        figures["modeled_topics"] = bar(
            list(reversed(modeling.get("topics", [])[:30])),
            x="doc_count",
            y="label",
            title="Modeled Topic Sizes",
            orientation="h",
        )
        figures["modeled_topic_evolution"] = line(
            modeling.get("topic_by_year", []),
            x="year",
            y="count",
            color="topic_id",
            title="Modeled Topic Evolution",
        )
        figures["modeled_topic_evolution_stacked"] = stacked_area(
            modeling.get("topic_by_year", []),
            x="year",
            y="count",
            color="topic_id",
            title="Modeled Topic Evolution",
        )
    return figures


def _summary_markdown(data: dict[str, Any], *, resolved_path: str, diagnostics: list[str]) -> str:
    lines = [
        "# Topic Landscape",
        "",
        f"Dataset: `{resolved_path}`",
        "",
        f"- Papers: {data['overview']['total_papers']}",
        f"- Methods: {', '.join(data['overview']['methods'])}",
    ]
    if diagnostics:
        lines.extend(["", "## Diagnostics"])
        lines.extend(f"- {item}" for item in diagnostics)
    if data.get("openalex_topics"):
        lines.extend(["", "## OpenAlex Topics"])
        for row in data["openalex_topics"]["topics"][:10]:
            lines.append(f"- {row['name']}: {row['frequency']} papers")
    if data.get("coword"):
        lines.extend(["", "## Co-Word Terms"])
        for row in data["coword"]["terms"][:10]:
            lines.append(f"- {row['term']}: {row['count']}")
    if data.get("topic_modeling"):
        lines.extend(["", "## Modeled Topics"])
        for row in data["topic_modeling"].get("topics", [])[:10]:
            lines.append(f"- Topic {row['topic_id']}: {row['label']} ({row['doc_count']} docs)")
    return "\n".join(lines)
