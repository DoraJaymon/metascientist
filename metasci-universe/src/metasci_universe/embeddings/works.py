"""Embedding artifact generation for saved works datasets."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from metasci_universe.analysis import _normalize as norm
from metasci_universe.analysis._dataset import load_records
from metasci_universe.schemas.common import MetaSciResult
from metasci_universe.schemas.embeddings import EmbedWorksRequest
from metasci_universe.storage.output_writer import DEFAULT_OUTPUT_DIR


async def embed_works(
    dataset_path: str,
    *,
    text_fields: list[str] | None = None,
    backend: str = "sentence_transformers",
    model: str | None = "sentence-transformers/all-MiniLM-L6-v2",
    language: str = "en",
    batch_size: int = 32,
    max_docs: int | None = None,
    min_text_words: int = 3,
    normalize: bool = True,
    dimensions: int = 384,
    api_base_url: str | None = None,
    api_key: str | None = None,
    api_key_env: str | None = "OPENAI_API_KEY",
    output_dir: str | None = None,
) -> MetaSciResult:
    """Embed works text and save reusable vector artifacts."""
    request = EmbedWorksRequest(
        dataset_path=dataset_path,
        text_fields=text_fields or ["title", "abstract"],
        backend=backend,  # type: ignore[arg-type]
        model=model,
        language=language,
        batch_size=batch_size,
        max_docs=max_docs,
        min_text_words=min_text_words,
        normalize=normalize,
        dimensions=dimensions,
        api_base_url=api_base_url,
        api_key=api_key,
        api_key_env=api_key_env,
        output_dir=output_dir,
    )
    records, dataset_metadata, resolved_path = load_records(request.dataset_path)
    docs, index_rows, doc_diagnostics = _documents(records, request)
    diagnostics = list(doc_diagnostics)
    input_payload = request.model_dump(mode="json")

    if not docs:
        diagnostics.append("No usable text found for embeddings.")
        data = {
            "status": "no_data",
            "overview": {"record_count": len(records), "embedded_count": 0, "skipped_count": len(records)},
        }
        artifacts = _write_artifacts(
            request=request,
            input_payload=input_payload,
            data=data,
            embeddings=None,
            index_rows=[],
            resolved_path=resolved_path,
            dataset_metadata=dataset_metadata,
            diagnostics=diagnostics,
        )
        return MetaSciResult(
            command="embeddings.embed_works",
            input=input_payload,
            data=data,
            artifacts=artifacts,
            metadata={"record_count": len(records), "dataset_path": resolved_path, "status": "no_data"},
            diagnostics=diagnostics,
        )

    embeddings, backend_metadata, backend_diagnostics = await _embed(docs, request)
    diagnostics.extend(backend_diagnostics)
    if embeddings is None:
        data = {
            "status": "backend_unavailable",
            "overview": {"record_count": len(records), "embedded_count": 0, "skipped_count": len(records) - len(docs)},
            "backend": request.backend,
            "model": request.model,
        }
        artifacts = _write_artifacts(
            request=request,
            input_payload=input_payload,
            data=data,
            embeddings=None,
            index_rows=index_rows,
            resolved_path=resolved_path,
            dataset_metadata=dataset_metadata,
            diagnostics=diagnostics,
        )
        return MetaSciResult(
            command="embeddings.embed_works",
            input=input_payload,
            data=data,
            artifacts=artifacts,
            metadata={"record_count": len(records), "dataset_path": resolved_path, "status": "backend_unavailable"},
            diagnostics=diagnostics,
        )

    data = {
        "status": "ok",
        "overview": {
            "record_count": len(records),
            "embedded_count": int(embeddings.shape[0]),
            "skipped_count": len(records) - int(embeddings.shape[0]),
            "dimension": int(embeddings.shape[1]) if embeddings.ndim == 2 else 0,
            "text_fields": request.text_fields,
        },
        "backend": request.backend,
        "model": request.model,
        "normalized": request.normalize,
        "backend_metadata": backend_metadata,
    }
    artifacts = _write_artifacts(
        request=request,
        input_payload=input_payload,
        data=data,
        embeddings=embeddings,
        index_rows=index_rows,
        resolved_path=resolved_path,
        dataset_metadata=dataset_metadata,
        diagnostics=diagnostics,
    )
    return MetaSciResult(
        command="embeddings.embed_works",
        input=input_payload,
        data=data,
        artifacts=artifacts,
        metadata={
            "record_count": len(records),
            "embedded_count": int(embeddings.shape[0]),
            "dimension": int(embeddings.shape[1]) if embeddings.ndim == 2 else 0,
            "dataset_path": resolved_path,
            "dataset_schema": dataset_metadata.get("schema_name"),
            "backend": request.backend,
            "status": "ok",
        },
        diagnostics=diagnostics,
    )


def _documents(
    works: list[dict[str, Any]],
    request: EmbedWorksRequest,
) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    docs: list[str] = []
    index_rows: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    skipped_short = 0
    for work in works:
        text = norm.text_for_fields(work, list(request.text_fields))
        if len(text.split()) < request.min_text_words:
            skipped_short += 1
            continue
        authors = norm.authors(work)
        source = norm.source(work)
        docs.append(text)
        index_rows.append(
            {
                "row": len(index_rows),
                "work_id": norm.work_id(work),
                "title": norm.title(work),
                "year": norm.year(work),
                "source": source.get("name") or "",
                "author_names": "; ".join(author.get("name", "") for author in authors if author.get("name")),
                "text_chars": len(text),
                "text_words": len(text.split()),
            }
        )
        if request.max_docs and len(docs) >= request.max_docs:
            break
    if skipped_short:
        diagnostics.append(f"Skipped {skipped_short} records with fewer than {request.min_text_words} text words.")
    return docs, index_rows, diagnostics


async def _embed(
    docs: list[str],
    request: EmbedWorksRequest,
) -> tuple[np.ndarray | None, dict[str, Any], list[str]]:
    if request.backend == "sentence_transformers":
        return _embed_sentence_transformers(docs, request)
    if request.backend == "transformers_pooling":
        return _embed_transformers_pooling(docs, request)
    if request.backend == "spacy":
        return _embed_spacy(docs, request)
    return await _embed_api(docs, request)


def _embed_sentence_transformers(
    docs: list[str],
    request: EmbedWorksRequest,
) -> tuple[np.ndarray | None, dict[str, Any], list[str]]:
    diagnostics: list[str] = []
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:  # pragma: no cover - environment-specific
        return None, {}, [f"sentence-transformers could not be imported: {exc}"]

    try:
        model_name = request.model or "sentence-transformers/all-MiniLM-L6-v2"
        model = SentenceTransformer(model_name)
        vectors = model.encode(
            docs,
            batch_size=request.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=request.normalize,
        )
    except Exception as exc:  # pragma: no cover - model/runtime-specific
        return None, {}, [f"SentenceTransformer embedding failed with model {request.model!r}: {exc}"]
    return np.asarray(vectors, dtype=np.float32), {"provider": "sentence_transformers"}, diagnostics


def _embed_transformers_pooling(
    docs: list[str],
    request: EmbedWorksRequest,
) -> tuple[np.ndarray | None, dict[str, Any], list[str]]:
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
    except Exception as exc:  # pragma: no cover - environment-specific
        return None, {}, [f"transformers/torch could not be imported: {exc}"]

    try:
        model_name = request.model or "allenai/scibert_scivocab_uncased"
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModel.from_pretrained(model_name)
        model.eval()
        batches: list[np.ndarray] = []
        with torch.no_grad():
            for start in range(0, len(docs), request.batch_size):
                batch_docs = docs[start : start + request.batch_size]
                encoded = tokenizer(batch_docs, padding=True, truncation=True, return_tensors="pt", max_length=512)
                output = model(**encoded)
                token_embeddings = output.last_hidden_state
                attention_mask = encoded["attention_mask"].unsqueeze(-1).expand(token_embeddings.size()).float()
                pooled = (token_embeddings * attention_mask).sum(dim=1) / attention_mask.sum(dim=1).clamp(min=1e-9)
                batches.append(pooled.cpu().numpy())
        vectors = np.vstack(batches).astype(np.float32)
    except Exception as exc:  # pragma: no cover - model/runtime-specific
        return None, {}, [f"Transformers pooling embedding failed with model {request.model!r}: {exc}"]
    return _normalize(vectors) if request.normalize else vectors, {"provider": "transformers_pooling", "pooling": "mean"}, []


def _embed_spacy(
    docs: list[str],
    request: EmbedWorksRequest,
) -> tuple[np.ndarray | None, dict[str, Any], list[str]]:
    diagnostics: list[str] = []
    try:
        import spacy
    except Exception as exc:  # pragma: no cover - environment-specific
        return None, {}, [f"spaCy could not be imported: {exc}"]

    model_name = request.model or request.language
    try:
        if request.model:
            nlp = spacy.load(request.model)
        else:
            nlp = spacy.blank(request.language)
    except Exception as exc:
        diagnostics.append(f"spaCy model {model_name!r} could not be loaded; using blank {request.language!r}: {exc}")
        nlp = spacy.blank(request.language)

    if getattr(nlp.vocab, "vectors_length", 0):
        vectors = np.asarray([doc.vector for doc in nlp.pipe(docs, batch_size=request.batch_size)], dtype=np.float32)
        metadata = {"provider": "spacy", "model": model_name, "fallback": None}
    else:
        diagnostics.append("spaCy model has no word vectors; using deterministic lexical hash fallback.")
        vectors = np.asarray([_hash_text_vector(doc, request.dimensions) for doc in docs], dtype=np.float32)
        metadata = {"provider": "spacy", "model": model_name, "fallback": "hash_text_vector"}
    return _normalize(vectors) if request.normalize else vectors, metadata, diagnostics


async def _embed_api(
    docs: list[str],
    request: EmbedWorksRequest,
) -> tuple[np.ndarray | None, dict[str, Any], list[str]]:
    try:
        import httpx
    except Exception as exc:  # pragma: no cover - environment-specific
        return None, {}, [f"httpx could not be imported: {exc}"]

    api_key = request.api_key or (os.environ.get(request.api_key_env) if request.api_key_env else None)
    if not api_key:
        return None, {}, [f"No API key provided for embedding API; set api_key or {request.api_key_env}."]

    base_url = (request.api_base_url or "https://api.openai.com/v1").rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    vectors: list[list[float]] = []
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            for start in range(0, len(docs), request.batch_size):
                batch_docs = docs[start : start + request.batch_size]
                response = await client.post(
                    f"{base_url}/embeddings",
                    headers=headers,
                    json={"model": request.model, "input": batch_docs},
                )
                response.raise_for_status()
                payload = response.json()
                data = sorted(payload.get("data", []), key=lambda row: row.get("index", 0))
                vectors.extend(row["embedding"] for row in data)
    except Exception as exc:  # pragma: no cover - network/runtime-specific
        return None, {}, [f"Embedding API request failed: {exc}"]

    array = np.asarray(vectors, dtype=np.float32)
    return _normalize(array) if request.normalize else array, {"provider": "api", "base_url": base_url}, []


def _write_artifacts(
    *,
    request: EmbedWorksRequest,
    input_payload: dict[str, Any],
    data: dict[str, Any],
    embeddings: np.ndarray | None,
    index_rows: list[dict[str, Any]],
    resolved_path: str,
    dataset_metadata: dict[str, Any],
    diagnostics: list[str],
) -> dict[str, str]:
    artifact_dir = _embedding_dir(input_payload=input_payload, output_dir=request.output_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {"embedding_dir": str(artifact_dir)}

    if embeddings is not None:
        embedding_path = artifact_dir / "embeddings.npy"
        np.save(embedding_path, embeddings)
        artifacts["embeddings_npy"] = str(embedding_path)

    index_jsonl = artifact_dir / "works_index.jsonl"
    index_jsonl.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in index_rows),
        encoding="utf-8",
    )
    artifacts["works_index_jsonl"] = str(index_jsonl)

    index_csv = artifact_dir / "works_index.csv"
    pd.DataFrame(index_rows).to_csv(index_csv, index=False)
    artifacts["works_index_csv"] = str(index_csv)

    metadata = {
        "schema_name": "work_embeddings",
        "command": "embeddings.embed_works",
        "input": input_payload,
        "data": data,
        "dataset_path": resolved_path,
        "dataset_schema": dataset_metadata.get("schema_name"),
        "diagnostics": diagnostics,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    metadata_path = artifact_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifacts["metadata_json"] = str(metadata_path)
    return artifacts


def _embedding_dir(*, input_payload: dict[str, Any], output_dir: str | Path | None) -> Path:
    stable_json = json.dumps(input_payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha1(stable_json.encode("utf-8")).hexdigest()[:12]
    slug = _slugify(Path(str(input_payload.get("dataset_path") or "embeddings")).stem)
    return Path(output_dir or DEFAULT_OUTPUT_DIR).expanduser() / f"embeddings_{slug}_{digest}"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80] or "works"


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return (vectors / norms).astype(np.float32)


def _hash_text_vector(text: str, dimensions: int) -> np.ndarray:
    vector = np.zeros(dimensions, dtype=np.float32)
    tokens = re.findall(r"[A-Za-z0-9_]+", text.lower())
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    return vector
