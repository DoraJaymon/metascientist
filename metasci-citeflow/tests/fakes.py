"""Hand-written test doubles, injected via CiteFlowDeps.

Following the metasci-universe convention: no unittest.mock, and every double raises
AssertionError on an unexpected call so a wrong call path fails loudly instead of
silently returning empty results (which is how the previous port's citation expansion
failed unnoticed).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple


class FakeLLM:
    """Scripted LLM keyed by prompt key.

    ``script`` maps a prompt key to the successive responses for that key.  Passing an
    ``Exception`` instance in the list makes that call raise, which is how retry paths
    are exercised.
    """

    def __init__(self, script: Optional[Dict[str, List[Any]]] = None) -> None:
        self.script = {key: list(values) for key, values in (script or {}).items()}
        self.calls: List[Dict[str, Any]] = []

    async def complete(
        self,
        *,
        system: str,
        user: str,
        model: str,
        temperature: float = 0.5,
        history: Optional[Sequence[Dict[str, str]]] = None,
        prompt_key: str = "",
    ) -> str:
        self.calls.append(
            {
                "prompt_key": prompt_key,
                "system": system,
                "user": user,
                "model": model,
                "temperature": temperature,
                "history": list(history or []),
            }
        )
        if prompt_key not in self.script:
            raise AssertionError(
                f"unscripted LLM call: {prompt_key!r} (scripted: {sorted(self.script)})"
            )
        queue = self.script[prompt_key]
        if not queue:
            raise AssertionError(f"LLM call {prompt_key!r} invoked more times than scripted")
        response = queue.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def calls_for(self, prompt_key: str) -> List[Dict[str, Any]]:
        return [call for call in self.calls if call["prompt_key"] == prompt_key]


class FakeS2:
    """Keyword search keyed by exact query string."""

    def __init__(self, results: Dict[str, List[Dict[str, Any]]]) -> None:
        self.results = results
        self.calls: List[Dict[str, Any]] = []

    async def search(
        self, query: str, *, limit: int = 50, year: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        self.calls.append({"query": query, "limit": limit, "year": year})
        if query not in self.results:
            raise AssertionError(
                f"unexpected S2 query: {query!r} (known: {sorted(self.results)})"
            )
        return [dict(paper) for paper in self.results[query][:limit]]


class FakeOpenAlex:
    """Citation-graph double.

    ``works`` maps OpenAlex id -> parsed paper dict.  ``by_doi`` / ``by_mag`` / ``by_title``
    map resolution keys to OpenAlex ids.  ``citations`` maps a seed id to citing papers.
    """

    def __init__(
        self,
        works: Optional[Dict[str, Dict[str, Any]]] = None,
        by_doi: Optional[Dict[str, str]] = None,
        by_mag: Optional[Dict[str, str]] = None,
        by_title: Optional[Dict[str, str]] = None,
        citations: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    ) -> None:
        self.works = works or {}
        self.by_doi = by_doi or {}
        self.by_mag = by_mag or {}
        self.by_title = by_title or {}
        self.citations = citations or {}
        self.get_by_ids_calls: List[List[str]] = []
        self.resolve_calls: List[List[Dict[str, str]]] = []
        self.citation_calls: List[Dict[str, Any]] = []
        self.reference_calls: List[Dict[str, Any]] = []

    async def get_by_ids(self, openalex_ids: Sequence[str]) -> List[Optional[Dict[str, Any]]]:
        ids = list(openalex_ids)
        self.get_by_ids_calls.append(ids)
        for value in ids:
            if value and not str(value).startswith("W"):
                raise AssertionError(f"non-OpenAlex id sent to get_by_ids: {value!r}")
        if len(ids) > 50:
            # Mirrors the real 50-per-filter limit; batching is the caller's job.
            raise AssertionError(f"get_by_ids batch too large: {len(ids)}")
        return [self.works.get(value) for value in ids]

    async def resolve_many(
        self, queries: Sequence[Dict[str, str]]
    ) -> List[Optional[Dict[str, Any]]]:
        self.resolve_calls.append([dict(query) for query in queries])
        resolved: List[Optional[Dict[str, Any]]] = []
        for query in queries:
            oa_id = None
            doi = (query.get("doi") or "").lower()
            if doi and doi in self.by_doi:
                oa_id = self.by_doi[doi]
            elif query.get("mag") and str(query["mag"]) in self.by_mag:
                oa_id = self.by_mag[str(query["mag"])]
            elif query.get("title") and query["title"] in self.by_title:
                oa_id = self.by_title[query["title"]]
            resolved.append(self.works.get(oa_id) if oa_id else None)
        return resolved

    async def batch_get_references(
        self, openalex_ids: Sequence[str], *, limit_per_work: int = 100
    ) -> Dict[str, List[Dict[str, Any]]]:
        self.reference_calls.append(
            {"ids": list(openalex_ids), "limit_per_work": limit_per_work}
        )
        out: Dict[str, List[Dict[str, Any]]] = {}
        for seed in openalex_ids:
            work = self.works.get(seed) or {}
            ref_ids = work.get("reference_ids", [])[:limit_per_work]
            out[seed] = [self.works[ref] for ref in ref_ids if ref in self.works]
        return out

    async def get_references(self, openalex_id: str, *, limit: int = 100) -> List[Dict[str, Any]]:
        result = await self.batch_get_references([openalex_id], limit_per_work=limit)
        return result.get(openalex_id, [])

    async def get_citations(
        self,
        openalex_ids: Sequence[str],
        *,
        year_range: Optional[Tuple[Optional[int], Optional[int]]] = None,
        min_cited_by: int = 0,
        field_id: Optional[str] = None,
        max_per_work: Optional[int] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        self.citation_calls.append(
            {
                "ids": list(openalex_ids),
                "year_range": year_range,
                "min_cited_by": min_cited_by,
                "field_id": field_id,
                "max_per_work": max_per_work,
            }
        )
        out: Dict[str, List[Dict[str, Any]]] = {}
        for seed in openalex_ids:
            papers = self.citations.get(seed, [])
            if year_range:
                start, end = year_range
                papers = [
                    p
                    for p in papers
                    if p.get("year") is not None
                    and (start is None or p["year"] >= start)
                    and (end is None or p["year"] <= end)
                ]
            if min_cited_by > 0:
                papers = [p for p in papers if (p.get("cited_by_count") or 0) >= min_cited_by]
            if max_per_work is not None:
                papers = papers[:max_per_work]
            out[seed] = [dict(p) for p in papers]
        return out


class FakeReranker:
    """Deterministic relevance: 1/(1+index) over the supplied document order."""

    def __init__(self, scores: Optional[Dict[str, float]] = None) -> None:
        self.scores = scores or {}
        self.calls: List[Dict[str, Any]] = []

    async def rerank(self, query: str, documents: Sequence[str]) -> List[float]:
        self.calls.append({"query": query, "documents": list(documents)})
        if len(documents) > 100:
            raise AssertionError(f"reranker batch too large: {len(documents)}")
        return [
            self.scores.get(doc, 1.0 / (1 + index)) for index, doc in enumerate(documents)
        ]


class RecordingSleep:
    """Async sleep that records durations instead of waiting."""

    def __init__(self) -> None:
        self.waits: List[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def oa_work(
    oa_id: str,
    *,
    title: Optional[str] = None,
    year: int = 2020,
    cited_by: int = 50,
    refs: Optional[List[str]] = None,
    abstract: str = "",
    doi: Optional[str] = None,
    mag: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a parsed OpenAlex paper dict for tests."""
    refs = refs or []
    return {
        "id": oa_id,
        "openalex_id": oa_id,
        "corpus_id": "",
        "mag_id": mag,
        "doi": (doi or "").lower(),
        "title": title or f"Work {oa_id}",
        "abstract": abstract,
        "year": year,
        "publication_year": year,
        "authors": [],
        "venue": "",
        "citation_count": cited_by,
        "cited_by_count": cited_by,
        "reference_count": len(refs),
        "referenced_works": list(refs),
        "reference_ids": list(refs),
        "url": f"https://openalex.org/{oa_id}",
        "_source": "openalex",
    }


def s2_paper(
    corpus_id: str,
    *,
    title: Optional[str] = None,
    year: int = 2020,
    cited_by: int = 30,
    doi: Optional[str] = None,
    mag: Optional[str] = None,
    abstract: str = "",
) -> Dict[str, Any]:
    """Build a parsed Semantic Scholar paper dict for tests."""
    return {
        "corpus_id": corpus_id,
        "paper_id": f"s2-{corpus_id}",
        "openalex_id": None,
        "doi": doi,
        "mag_id": mag,
        "arxiv_id": None,
        "title": title or f"Paper {corpus_id}",
        "abstract": abstract,
        "year": year,
        "publication_year": year,
        "authors": [],
        "venue": "",
        "url": "",
        "citation_count": cited_by,
        "cited_by_count": cited_by,
        "reference_count": 0,
        "influential_citation_count": 0,
        "fields_of_study": [],
        "_source": "semantic_scholar",
    }
