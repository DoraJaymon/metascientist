"""Topic modeling backends for works datasets."""

from __future__ import annotations

from collections import Counter
import os
from pathlib import Path
import tempfile
from typing import Any

import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import LatentDirichletAllocation
from sklearn.feature_extraction.text import CountVectorizer

from metasci_universe.analysis import _normalize as norm
from metasci_universe.analysis._artifacts import save_analysis_artifacts
from metasci_universe.analysis._dataset import load_records
from metasci_universe.analysis._viz import bar, line, stacked_area, wide_matrix
from metasci_universe.schemas.analysis import TopicModelingRequest
from metasci_universe.schemas.common import MetaSciResult


async def topic_modeling(
    dataset_path: str,
    *,
    backend: str = "embedding_kmeans",
    text_fields: list[str] | None = None,
    text_backend: str = "spacy",
    language: str = "en",
    spacy_model: str | None = None,
    lemmatize: bool = True,
    nr_topics: int | None = None,
    min_topic_size: int = 10,
    max_docs: int | None = None,
    max_features: int = 5000,
    include_evolution: bool = True,
    year_field: str = "publication_year",
    embedding_model: str | None = "allenai/scibert_scivocab_uncased",
    embedding_artifact: str | None = None,
    random_state: int = 42,
    output_dir: str | None = None,
) -> MetaSciResult:
    """Run topic modeling with LDA or BERTopic."""
    request = TopicModelingRequest(
        dataset_path=dataset_path,
        backend=backend,  # type: ignore[arg-type]
        text_fields=text_fields or ["title", "abstract"],
        text_backend=text_backend,  # type: ignore[arg-type]
        language=language,
        spacy_model=spacy_model,
        lemmatize=lemmatize,
        nr_topics=nr_topics,
        min_topic_size=min_topic_size,
        max_docs=max_docs,
        max_features=max_features,
        include_evolution=include_evolution,
        year_field=year_field,
        embedding_model=embedding_model,
        embedding_artifact=embedding_artifact,
        random_state=random_state,
        output_dir=output_dir,
    )
    records, dataset_metadata, resolved_path = load_records(request.dataset_path)
    data, diagnostics = compute_topic_modeling(records, request)
    input_payload = request.model_dump(mode="json")
    artifacts = save_analysis_artifacts(
        command="analysis.topic_modeling",
        input_payload=input_payload,
        data=data,
        summary_markdown=_summary_markdown(data, resolved_path=resolved_path, diagnostics=diagnostics),
        tables={
            "topics": data.get("topics", []),
            "document_topics": data.get("document_topics", []),
            "representative_docs": _flatten_representative_docs(data.get("representative_docs", [])),
            "topic_by_year": data.get("topic_by_year", []),
            "topic_by_year_matrix": data.get("topic_by_year_matrix", []),
        },
        figures=_figures(data),
        output_dir=request.output_dir,
        diagnostics=diagnostics,
    )
    return MetaSciResult(
        command="analysis.topic_modeling",
        input=input_payload,
        data=data,
        artifacts=artifacts,
        metadata={
            "record_count": len(records),
            "dataset_path": resolved_path,
            "dataset_schema": dataset_metadata.get("schema_name"),
            "backend": request.backend,
            "status": data.get("status", "ok"),
        },
        diagnostics=diagnostics,
    )


def compute_topic_modeling(works: list[dict[str, Any]], request: TopicModelingRequest) -> tuple[dict[str, Any], list[str]]:
    """Compute topic modeling data without writing artifacts."""
    docs, doc_meta = _documents(works, request)
    diagnostics: list[str] = []
    if not docs:
        diagnostics.append("No usable title or abstract text found for topic modeling.")
        return ({"status": "no_data", "overview": {"document_count": 0}, "topics": [], "document_topics": [], "topic_by_year": []}, diagnostics)

    if request.backend == "bertopic":
        return _compute_bertopic(docs, doc_meta, request)
    if request.backend in {"embedding_kmeans", "embedding_hdbscan"}:
        return _compute_embedding_clusters(docs, doc_meta, request)
    return _compute_lda(docs, doc_meta, request)


def _documents(works: list[dict[str, Any]], request: TopicModelingRequest) -> tuple[list[str], list[dict[str, Any]]]:
    docs: list[str] = []
    metadata: list[dict[str, Any]] = []
    for work in works:
        text = norm.text_for_fields(work, list(request.text_fields))
        if len(text.split()) < 3:
            continue
        docs.append(text)
        metadata.append({"id": norm.work_id(work), "title": norm.title(work), "year": norm.year(work, request.year_field)})
        if request.max_docs and len(docs) >= request.max_docs:
            break
    return docs, metadata


def _compute_lda(
    docs: list[str],
    doc_meta: list[dict[str, Any]],
    request: TopicModelingRequest,
) -> tuple[dict[str, Any], list[str]]:
    diagnostics: list[str] = []
    topic_count = request.nr_topics or min(10, max(2, len(docs) // 10 or 2))
    vectorizer = CountVectorizer(stop_words="english", max_features=request.max_features, min_df=1)
    matrix = vectorizer.fit_transform(docs)
    if matrix.shape[1] < topic_count:
        topic_count = max(2, min(topic_count, matrix.shape[1]))
        diagnostics.append(f"Reduced nr_topics to {topic_count} because the vocabulary is small.")

    model = LatentDirichletAllocation(n_components=topic_count, random_state=request.random_state, learning_method="batch")
    doc_topic = model.fit_transform(matrix)
    feature_names = vectorizer.get_feature_names_out()
    dominant_topics = doc_topic.argmax(axis=1)
    topic_doc_counts = Counter(int(topic_id) for topic_id in dominant_topics)

    topics = []
    for topic_id, weights in enumerate(model.components_):
        top_indexes = weights.argsort()[-12:][::-1]
        words = [{"term": str(feature_names[index]), "weight": round(float(weights[index]), 6)} for index in top_indexes]
        label = ", ".join(word["term"] for word in words[:4])
        topics.append(
            {
                "topic_id": topic_id,
                "label": label,
                "doc_count": topic_doc_counts.get(topic_id, 0),
                "words": words,
            }
        )
    topics.sort(key=lambda row: row["doc_count"], reverse=True)

    document_topics = []
    topic_by_year_counter: Counter[tuple[int, int]] = Counter()
    for index, topic_id in enumerate(dominant_topics):
        topic_id_int = int(topic_id)
        probability = float(doc_topic[index, topic_id_int])
        meta = doc_meta[index]
        document_topics.append(
            {
                "work_id": meta["id"],
                "title": meta["title"],
                "year": meta["year"],
                "topic_id": topic_id_int,
                "probability": round(probability, 6),
            }
        )
        if request.include_evolution and meta["year"] is not None:
            topic_by_year_counter[(meta["year"], topic_id_int)] += 1

    topic_by_year = [
        {"year": year, "topic_id": topic_id, "count": count}
        for (year, topic_id), count in sorted(topic_by_year_counter.items())
    ]
    representative_docs = _representative_docs(document_topics)
    return (
        {
            "status": "ok",
            "backend": "sklearn_lda",
            "overview": {
                "document_count": len(docs),
                "topic_count": topic_count,
                "vocabulary_size": int(matrix.shape[1]),
            },
            "topics": topics,
            "document_topics": document_topics,
            "representative_docs": representative_docs,
            "topic_by_year": topic_by_year,
            "topic_by_year_matrix": wide_matrix(topic_by_year, index="year", columns="topic_id", values="count"),
        },
        diagnostics,
    )


def _compute_embedding_clusters(
    docs: list[str],
    doc_meta: list[dict[str, Any]],
    request: TopicModelingRequest,
) -> tuple[dict[str, Any], list[str]]:
    diagnostics: list[str] = []
    embedding_source = "computed"
    embeddings = None
    if request.embedding_artifact:
        embeddings, artifact_diagnostics = _load_embedding_artifact(request.embedding_artifact, expected_rows=len(docs))
        diagnostics.extend(artifact_diagnostics)
        if embeddings is not None:
            embedding_source = "artifact"

    if embeddings is None:
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:  # pragma: no cover - environment-specific
            diagnostics.append(f"sentence-transformers could not be imported: {exc}")
            return _unavailable_embedding_result(request, len(docs), diagnostics)

        try:
            model = SentenceTransformer(request.embedding_model or "sentence-transformers/all-MiniLM-L6-v2")
            embeddings = model.encode(docs, show_progress_bar=False, convert_to_numpy=True, normalize_embeddings=True)
        except Exception as exc:  # pragma: no cover - model/runtime-specific
            diagnostics.append(f"Sentence embedding failed with model {request.embedding_model!r}: {exc}")
            return _unavailable_embedding_result(request, len(docs), diagnostics)

    if request.backend == "embedding_hdbscan":
        try:
            import hdbscan

            clusterer = hdbscan.HDBSCAN(min_cluster_size=request.min_topic_size, metric="euclidean")
            labels = clusterer.fit_predict(embeddings)
            probabilities = getattr(clusterer, "probabilities_", None)
        except Exception as exc:  # pragma: no cover - environment-specific
            diagnostics.append(f"HDBSCAN clustering failed: {exc}")
            return _unavailable_embedding_result(request, len(docs), diagnostics)
    else:
        topic_count = request.nr_topics or min(10, max(2, len(docs) // 10 or 2))
        topic_count = min(topic_count, len(docs))
        clusterer = KMeans(n_clusters=topic_count, random_state=request.random_state, n_init="auto")
        labels = clusterer.fit_predict(embeddings)
        probabilities = None

    label_values = [int(label) for label in labels]
    cluster_ids = sorted({label for label in label_values if label >= 0})
    if not cluster_ids:
        diagnostics.append("Embedding clustering produced no non-outlier clusters.")

    topics = _label_clusters(docs, label_values, cluster_ids, request)
    topic_by_year_counter: Counter[tuple[int, int]] = Counter()
    document_topics = []
    for index, topic_id in enumerate(label_values):
        meta = doc_meta[index]
        probability = None
        if probabilities is not None:
            try:
                probability = round(float(probabilities[index]), 6)
            except Exception:
                probability = None
        document_topics.append(
            {
                "work_id": meta["id"],
                "title": meta["title"],
                "year": meta["year"],
                "topic_id": topic_id,
                "probability": probability,
            }
        )
        if request.include_evolution and meta["year"] is not None and topic_id >= 0:
            topic_by_year_counter[(meta["year"], topic_id)] += 1

    topic_by_year = [
        {"year": year, "topic_id": topic_id, "count": count}
        for (year, topic_id), count in sorted(topic_by_year_counter.items())
    ]
    return (
        {
            "status": "ok",
            "backend": request.backend,
            "embedding_model": request.embedding_model,
            "embedding_source": embedding_source,
            "overview": {
                "document_count": len(docs),
                "topic_count": len(cluster_ids),
                "outlier_count": sum(1 for label in label_values if label < 0),
            },
            "topics": topics,
            "document_topics": document_topics,
            "representative_docs": _representative_docs(document_topics),
            "topic_by_year": topic_by_year,
            "topic_by_year_matrix": wide_matrix(topic_by_year, index="year", columns="topic_id", values="count"),
        },
        diagnostics,
    )


def _unavailable_embedding_result(
    request: TopicModelingRequest,
    document_count: int,
    diagnostics: list[str],
) -> tuple[dict[str, Any], list[str]]:
    return (
        {
            "status": "backend_unavailable",
            "backend": request.backend,
            "embedding_model": request.embedding_model,
            "embedding_source": "unavailable",
            "overview": {"document_count": document_count, "topic_count": 0},
            "topics": [],
            "document_topics": [],
            "topic_by_year": [],
        },
        diagnostics,
    )


def _label_clusters(
    docs: list[str],
    labels: list[int],
    cluster_ids: list[int],
    request: TopicModelingRequest,
) -> list[dict[str, Any]]:
    topics: list[dict[str, Any]] = []
    for cluster_id in cluster_ids:
        cluster_docs = [docs[index] for index, label in enumerate(labels) if label == cluster_id]
        words = _top_words_for_docs(cluster_docs, max_features=request.max_features)
        label = ", ".join(word["term"] for word in words[:4]) or f"topic {cluster_id}"
        topics.append(
            {
                "topic_id": cluster_id,
                "label": label,
                "doc_count": len(cluster_docs),
                "words": words,
            }
        )
    topics.sort(key=lambda row: row["doc_count"], reverse=True)
    return topics


def _load_embedding_artifact(path: str, *, expected_rows: int) -> tuple[Any | None, list[str]]:
    artifact_path = Path(path).expanduser()
    if artifact_path.is_dir():
        embedding_path = artifact_path / "embeddings.npy"
    elif artifact_path.name == "metadata.json":
        embedding_path = artifact_path.parent / "embeddings.npy"
    else:
        embedding_path = artifact_path

    if not embedding_path.exists():
        return None, [f"Embedding artifact not found at {embedding_path}; computing embeddings instead."]

    try:
        import numpy as np

        embeddings = np.load(embedding_path)
    except Exception as exc:
        return None, [f"Could not load embedding artifact {embedding_path}: {exc}; computing embeddings instead."]

    if embeddings.ndim != 2:
        return None, [f"Embedding artifact {embedding_path} is not a 2D matrix; computing embeddings instead."]
    if embeddings.shape[0] != expected_rows:
        return None, [
            f"Embedding artifact row count ({embeddings.shape[0]}) does not match usable documents ({expected_rows}); "
            "computing embeddings instead."
        ]
    return embeddings, [f"Loaded embeddings from artifact: {embedding_path}"]


def _top_words_for_docs(docs: list[str], *, max_features: int) -> list[dict[str, Any]]:
    if not docs:
        return []
    try:
        vectorizer = CountVectorizer(stop_words="english", max_features=max_features, ngram_range=(1, 2), min_df=1)
        matrix = vectorizer.fit_transform(docs)
    except ValueError:
        return []
    feature_names = vectorizer.get_feature_names_out()
    weights = matrix.sum(axis=0).A1
    top_indexes = weights.argsort()[-12:][::-1]
    return [
        {"term": str(feature_names[index]), "weight": round(float(weights[index]), 6)}
        for index in top_indexes
        if weights[index] > 0
    ]


def _compute_bertopic(
    docs: list[str],
    doc_meta: list[dict[str, Any]],
    request: TopicModelingRequest,
) -> tuple[dict[str, Any], list[str]]:
    diagnostics: list[str] = []
    _ensure_numba_cache_dir(diagnostics)
    try:
        from bertopic import BERTopic
    except Exception as exc:  # pragma: no cover - environment-specific
        diagnostics.append(f"BERTopic could not be imported: {exc}")
        return (
            {
                "status": "backend_unavailable",
                "backend": "bertopic",
                "overview": {"document_count": len(docs), "topic_count": 0},
                "topics": [],
                "document_topics": [],
                "topic_by_year": [],
            },
            diagnostics,
        )

    try:
        model = BERTopic(
            nr_topics=request.nr_topics,
            min_topic_size=request.min_topic_size,
            embedding_model=request.embedding_model,
            verbose=False,
        )
        topic_ids, probabilities = model.fit_transform(docs)
    except Exception as exc:  # pragma: no cover - model/runtime-specific
        diagnostics.append(f"BERTopic failed during fitting: {exc}")
        return (
            {
                "status": "fit_failed",
                "backend": "bertopic",
                "overview": {"document_count": len(docs), "topic_count": 0},
                "topics": [],
                "document_topics": [],
                "topic_by_year": [],
            },
            diagnostics,
        )

    topic_info = model.get_topic_info()
    topic_doc_counts = Counter(int(topic_id) for topic_id in topic_ids if int(topic_id) >= 0)
    topics = []
    for _, row in topic_info.iterrows():
        topic_id = int(row["Topic"])
        if topic_id < 0:
            continue
        words = [
            {"term": str(term), "weight": round(float(weight), 6)}
            for term, weight in (model.get_topic(topic_id) or [])[:12]
        ]
        topics.append(
            {
                "topic_id": topic_id,
                "label": str(row.get("Name") or ", ".join(word["term"] for word in words[:4])),
                "doc_count": topic_doc_counts.get(topic_id, 0),
                "words": words,
            }
        )

    topic_by_year_counter: Counter[tuple[int, int]] = Counter()
    document_topics = []
    for index, topic_id in enumerate(topic_ids):
        topic_id_int = int(topic_id)
        meta = doc_meta[index]
        probability = None
        if probabilities is not None:
            try:
                probability = float(probabilities[index])
            except Exception:
                probability = None
        document_topics.append(
            {
                "work_id": meta["id"],
                "title": meta["title"],
                "year": meta["year"],
                "topic_id": topic_id_int,
                "probability": probability,
            }
        )
        if request.include_evolution and meta["year"] is not None and topic_id_int >= 0:
            topic_by_year_counter[(meta["year"], topic_id_int)] += 1

    topic_by_year = [
        {"year": year, "topic_id": topic_id, "count": count}
        for (year, topic_id), count in sorted(topic_by_year_counter.items())
    ]
    return (
        {
            "status": "ok",
            "backend": "bertopic",
            "overview": {"document_count": len(docs), "topic_count": len(topics)},
            "topics": sorted(topics, key=lambda row: row["doc_count"], reverse=True),
            "document_topics": document_topics,
            "representative_docs": _representative_docs(document_topics),
            "topic_by_year": topic_by_year,
            "topic_by_year_matrix": wide_matrix(topic_by_year, index="year", columns="topic_id", values="count"),
        },
        diagnostics,
    )


def _ensure_numba_cache_dir(diagnostics: list[str]) -> None:
    """Set a writable Numba cache directory before importing UMAP/BERTopic."""
    if os.environ.get("NUMBA_CACHE_DIR"):
        return

    cache_dir = Path(os.environ.get("METASCI_NUMBA_CACHE_DIR") or tempfile.gettempdir()) / "metasci-numba-cache"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ["NUMBA_CACHE_DIR"] = str(cache_dir)
    except OSError as exc:
        diagnostics.append(f"Could not create NUMBA_CACHE_DIR at {cache_dir}: {exc}")


def _figures(data: dict[str, Any]) -> dict[str, Any]:
    topics = data.get("topics", [])
    topic_by_year = data.get("topic_by_year", [])
    return {
        "topic_sizes": bar(
            list(reversed(topics[:30])),
            x="doc_count",
            y="label",
            title="Topic Model Topic Sizes",
            orientation="h",
        ),
        "topic_evolution": line(
            topic_by_year,
            x="year",
            y="count",
            color="topic_id",
            title="Modeled Topic Evolution",
        ),
        "topic_evolution_stacked": stacked_area(
            topic_by_year,
            x="year",
            y="count",
            color="topic_id",
            title="Modeled Topic Evolution",
        ),
    }


def _summary_markdown(data: dict[str, Any], *, resolved_path: str, diagnostics: list[str]) -> str:
    lines = [
        "# Topic Modeling",
        "",
        f"Dataset: `{resolved_path}`",
        "",
        f"- Status: {data.get('status')}",
        f"- Backend: {data.get('backend')}",
        f"- Documents: {data.get('overview', {}).get('document_count')}",
        f"- Topics: {data.get('overview', {}).get('topic_count')}",
    ]
    if diagnostics:
        lines.extend(["", "## Diagnostics"])
        lines.extend(f"- {item}" for item in diagnostics)
    lines.extend(["", "## Topics"])
    for row in data.get("topics", [])[:10]:
        lines.append(f"- Topic {row['topic_id']}: {row['label']} ({row['doc_count']} docs)")
    return "\n".join(lines)


def _representative_docs(document_topics: list[dict[str, Any]], *, per_topic: int = 5) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in document_topics:
        topic_id = row.get("topic_id")
        if topic_id is None or topic_id < 0:
            continue
        grouped.setdefault(int(topic_id), []).append(row)

    representative: list[dict[str, Any]] = []
    for topic_id, rows in grouped.items():
        ranked = sorted(rows, key=lambda item: item.get("probability") if item.get("probability") is not None else 0, reverse=True)
        representative.append(
            {
                "topic_id": topic_id,
                "documents": [
                    {
                        "work_id": row.get("work_id"),
                        "title": row.get("title"),
                        "year": row.get("year"),
                        "score": row.get("probability"),
                    }
                    for row in ranked[:per_topic]
                ],
            }
        )
    return sorted(representative, key=lambda row: len(row["documents"]), reverse=True)


def _flatten_representative_docs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for topic in rows:
        topic_id = topic.get("topic_id")
        for rank, doc in enumerate(topic.get("documents", []), start=1):
            flattened.append({"topic_id": topic_id, "rank": rank, **doc})
    return flattened
