"""Semantic relevance via a cross-encoder rerank API.

Despite the store field being called ``embedding_sim``, this is **not** an embedding
similarity: it is a cross-encoder (``BAAI/bge-reranker-v2-m3``) that reads the query and
the document together and emits one relevance score.  That matters because the score
distribution is far sharper than cosine similarity — a genuinely on-topic paper lands
near 0.96 while a merely adjacent one can sit at 0.015 — which is what makes the
``HIGH_REL_THRESHOLD = 0.93`` boost in the ranker meaningful.

Scoring is skipped for records that already have a score unless ``force`` is set, so
re-running is cheap.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

DEFAULT_URL = os.getenv("RERANKER_URL", "https://yunwu.ai/v1/rerank")
DEFAULT_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
BATCH_SIZE = 100
TIMEOUT = 30.0


class RerankerUnavailable(RuntimeError):
    pass


def document_text(record: Any) -> str:
    """Reranker input: ``"{title}. {abstract}"``.

    Records without an abstract fall back to the title alone, which is materially
    weaker — worth checking abstract coverage before trusting these scores.
    """
    title = (getattr(record, "title", "") or "").strip()
    abstract = (getattr(record, "abstract", "") or "").strip()
    return f"{title}. {abstract}" if abstract else title


def normalise_scores(raw: Sequence[float]) -> List[float]:
    """Keep scores as-is when already in [0, 1], otherwise scale by the max."""
    if not raw:
        return []
    low, high = min(raw), max(raw)
    if low >= 0.0 and high <= 1.0:
        return list(raw)
    return [value / high if high > 0 else 0.0 for value in raw]


class BGEReranker:
    """HTTP cross-encoder client."""

    def __init__(
        self,
        api_token: Optional[str] = None,
        url: Optional[str] = None,
        model: Optional[str] = None,
        client: Any = None,
    ) -> None:
        self.api_token = api_token or os.getenv("RERANKER_API_TOKEN")
        self.url = url or DEFAULT_URL
        self.model = model or DEFAULT_MODEL
        self._client = client

    async def _get_client(self):
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(timeout=TIMEOUT)
        return self._client

    async def rerank(self, query: str, documents: Sequence[str]) -> List[float]:
        """Return one score per document, aligned by index."""
        if not documents:
            return []
        if not self.api_token:
            raise RerankerUnavailable(
                "RERANKER_API_TOKEN is not set; semantic relevance scoring is unavailable."
            )

        client = await self._get_client()
        scores: List[float] = [0.0] * len(documents)

        for start in range(0, len(documents), BATCH_SIZE):
            batch = list(documents[start : start + BATCH_SIZE])
            response = await client.post(
                self.url,
                json={"model": self.model, "query": query, "documents": batch, "top_n": len(batch)},
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": "application/json",
                },
            )
            if response.status_code != 200:
                raise RerankerUnavailable(
                    f"Reranker HTTP {response.status_code}: {response.text[:200]}"
                )
            results = (response.json() or {}).get("results") or []
            raw = [0.0] * len(batch)
            for item in results:
                index = item.get("index", -1)
                if 0 <= index < len(batch):
                    raw[index] = float(item.get("relevance_score", 0.0))
            for offset, value in enumerate(normalise_scores(raw)):
                scores[start + offset] = value

        return scores


async def score_relevance(
    records: Sequence[Any],
    query_text: str,
    reranker: Any,
    *,
    force: bool = False,
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """Score records and return ``({paper_id: score}, report)``."""
    pending: List[Any] = []
    texts: List[str] = []
    skipped = 0

    for record in records:
        if not force and record.embedding_sim is not None:
            skipped += 1
            continue
        text = document_text(record)
        if not text.strip(". "):
            continue
        pending.append(record)
        texts.append(text)

    if not pending:
        return {}, {"scored": 0, "skipped": skipped}

    values = await reranker.rerank(query_text, texts)
    scores = {
        (record.openalex_id or record.corpus_id): value
        for record, value in zip(pending, values)
    }
    return scores, {
        "scored": len(scores),
        "skipped": skipped,
        "min": round(min(values), 4) if values else 0.0,
        "max": round(max(values), 4) if values else 0.0,
        "mean": round(sum(values) / len(values), 4) if values else 0.0,
    }
