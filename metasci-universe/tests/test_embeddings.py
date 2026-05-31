from __future__ import annotations

import asyncio
import json

import numpy as np

import metasci_universe as ms


def _write_dataset(tmp_path):
    rows = [
        {
            "id": "W1",
            "title": "Semantic change in science mapping",
            "abstract": "Embedding models quantify topic movement and field evolution.",
            "publication_year": 2022,
            "source": {"name": "Journal A"},
            "authors": [{"display_name": "Ada Lovelace"}],
        },
        {
            "id": "W2",
            "title": "Journal differences in bibliometrics",
            "abstract": "Vector spaces measure similarity and distance between journals.",
            "publication_year": 2023,
            "source": {"name": "Journal B"},
            "authors": [{"display_name": "Grace Hopper"}],
        },
    ]
    path = tmp_path / "papers.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def test_embed_works_spacy_backend_writes_artifacts(tmp_path) -> None:
    dataset = _write_dataset(tmp_path)
    result = asyncio.run(
        ms.embeddings.embed_works(
            str(dataset),
            backend="spacy",
            dimensions=32,
            output_dir=str(tmp_path / "embeddings"),
        )
    )

    assert result.command == "embeddings.embed_works"
    assert result.data["status"] == "ok"
    assert result.data["overview"]["embedded_count"] == 2
    assert result.data["overview"]["dimension"] == 32
    assert "embeddings_npy" in result.artifacts
    assert "works_index_jsonl" in result.artifacts
    matrix = np.load(result.artifacts["embeddings_npy"])
    assert matrix.shape == (2, 32)


def test_embed_works_tool_registry(tmp_path) -> None:
    dataset = _write_dataset(tmp_path)
    result = asyncio.run(
        ms.run_tool(
            "embeddings.embed_works",
            {
                "dataset_path": str(dataset),
                "backend": "spacy",
                "dimensions": 16,
                "output_dir": str(tmp_path / "tool_embeddings"),
            },
        )
    )

    assert result.metadata["backend"] == "spacy"
    assert result.metadata["dimension"] == 16


def test_topic_modeling_reuses_embedding_artifact(tmp_path) -> None:
    dataset = _write_dataset(tmp_path)
    embedding_result = asyncio.run(
        ms.embeddings.embed_works(
            str(dataset),
            backend="spacy",
            dimensions=16,
            output_dir=str(tmp_path / "embeddings"),
        )
    )

    modeling_result = asyncio.run(
        ms.analysis.topic_modeling(
            str(dataset),
            backend="embedding_kmeans",
            nr_topics=2,
            embedding_artifact=embedding_result.artifacts["embedding_dir"],
            output_dir=str(tmp_path / "topics"),
        )
    )

    assert modeling_result.data["status"] == "ok"
    assert modeling_result.data["embedding_source"] == "artifact"
    assert any("Loaded embeddings from artifact" in item for item in modeling_result.diagnostics)
