"""Benchmark loading.

The paper-finder benchmark pairs a natural-language research question with the papers
that genuinely answer it.  Ground truth carries **both** a Semantic Scholar corpus id and
an OpenAlex work id, and a prediction counts as a hit on either — which is why the
store must preserve both identifiers through resolution rather than replacing one with
the other.

Ground-truth sets are small (median 1 paper, max 26), so per-query results are noisy and
should be reported individually rather than averaged over a handful of queries.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set

DEFAULT_BENCHMARK = Path(
    os.getenv(
        "CITEFLOW_BENCHMARK",
        "/home/dell/Desktop/AcaDeepR/data/paper_finder/test_2025_05_cn.json",
    )
)


def normalise_id(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("https://openalex.org/"):
        text = text.rsplit("/", 1)[-1]
    return text


@dataclass(frozen=True)
class BenchmarkQuery:
    query_id: str
    query: str
    papers: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.papers)

    def id_sets(self) -> List[Set[str]]:
        """One id set per ground-truth paper; a hit on any member counts."""
        sets = []
        for paper in self.papers:
            ids = {
                normalise_id(paper.get("openalex_id")),
                normalise_id(paper.get("corpus_id")),
            }
            ids.discard("")
            if ids:
                sets.append(ids)
        return sets

    def titles(self) -> List[str]:
        return [paper.get("title_en") or paper.get("title_cn") or "" for paper in self.papers]


class Benchmark:
    """The paper-finder benchmark, indexed by query id."""

    def __init__(self, queries: List[BenchmarkQuery]) -> None:
        self._queries = {query.query_id: query for query in queries}

    @classmethod
    def load(cls, path: Optional[str | Path] = None) -> "Benchmark":
        target = Path(path) if path else DEFAULT_BENCHMARK
        if not target.exists():
            raise FileNotFoundError(f"Benchmark not found at {target}")
        with open(target, encoding="utf-8") as handle:
            raw = json.load(handle)

        queries = [
            BenchmarkQuery(
                query_id=entry["query_id"],
                query=entry.get("query_en") or entry.get("query_cn") or "",
                papers=entry.get("papers") or [],
            )
            for entry in raw
        ]
        return cls(queries)

    def __contains__(self, query_id: str) -> bool:
        return query_id in self._queries

    def __iter__(self) -> Iterator[BenchmarkQuery]:
        return iter(self._queries.values())

    def __len__(self) -> int:
        return len(self._queries)

    def get(self, query_id: str) -> BenchmarkQuery:
        try:
            return self._queries[query_id]
        except KeyError as exc:
            raise KeyError(
                f"Unknown benchmark query {query_id!r} ({len(self._queries)} available)"
            ) from exc

    def query_ids(self) -> List[str]:
        return sorted(self._queries)
