"""Public citation graph lookup API."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

import httpx

from metasci_universe.providers.openalex_api import OpenAlexAPIProvider
from metasci_universe.providers.semantic_scholar_api import SemanticScholarAPIProvider, SemanticScholarPartialError
from metasci_universe.schemas.citations import CitationLookupRequest, CitationResolveRequest
from metasci_universe.schemas.common import MetaSciResult


def _compact_openalex_id(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return value.replace("https://openalex.org/", "")


def _openalex_url(value: str | None) -> str | None:
    if not value:
        return None
    compact = _compact_openalex_id(value)
    return compact if str(compact).startswith("http") else f"https://openalex.org/{compact}"


def _normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    doi = value.strip()
    doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
    doi = doi.replace("doi:", "").replace("DOI:", "").strip()
    return doi or None


def _normalize_arxiv(value: str | None) -> str | None:
    if not value:
        return None
    arxiv = value.strip()
    arxiv = re.sub(r"^https?://arxiv\.org/(abs|pdf)/", "", arxiv, flags=re.I)
    arxiv = re.sub(r"\.pdf$", "", arxiv, flags=re.I)
    arxiv = re.sub(r"^arxiv:", "", arxiv, flags=re.I)
    return arxiv.strip() or None


def _title_score(query: str | None, candidate: str | None) -> float | None:
    if not query or not candidate:
        return None
    return round(SequenceMatcher(None, query.lower().strip(), candidate.lower().strip()).ratio(), 3)


def _external_ids_from_s2(paper: dict[str, Any]) -> dict[str, Any]:
    return paper.get("externalIds") or {}


def _normalize_openalex_work(work: dict[str, Any] | None, *, provider: str = "openalex") -> dict[str, Any] | None:
    if not work:
        return None
    source = ((work.get("primary_location") or {}).get("source") or {})
    doi = _normalize_doi(work.get("doi"))
    return {
        "id": _compact_openalex_id(work.get("id")),
        "openalex_id": _compact_openalex_id(work.get("id")),
        "s2_id": None,
        "s2_corpus_id": None,
        "doi": doi,
        "arxiv_id": None,
        "title": work.get("title") or work.get("display_name"),
        "year": work.get("publication_year"),
        "venue": source.get("display_name"),
        "authors": [
            ((authorship.get("author") or {}).get("display_name"))
            for authorship in (work.get("authorships") or [])
            if (authorship.get("author") or {}).get("display_name")
        ],
        "citation_count": work.get("cited_by_count", 0) or 0,
        "reference_count": len(work.get("referenced_works") or []),
        "url": work.get("doi") or _openalex_url(_compact_openalex_id(work.get("id"))),
        "provider": provider,
        "provider_ids": {"openalex": _compact_openalex_id(work.get("id"))},
        "referenced_works": [_compact_openalex_id(item) for item in (work.get("referenced_works") or [])],
    }


def _normalize_s2_paper(paper: dict[str, Any] | None, *, provider: str = "semantic_scholar") -> dict[str, Any] | None:
    if not paper:
        return None
    external_ids = _external_ids_from_s2(paper)
    doi = _normalize_doi(external_ids.get("DOI"))
    arxiv_id = _normalize_arxiv(external_ids.get("ArXiv"))
    openalex_id = _compact_openalex_id(external_ids.get("OpenAlex"))
    return {
        "id": paper.get("paperId") or (str(paper.get("corpusId")) if paper.get("corpusId") else None),
        "openalex_id": openalex_id,
        "s2_id": paper.get("paperId"),
        "s2_corpus_id": str(paper.get("corpusId")) if paper.get("corpusId") else None,
        "doi": doi,
        "arxiv_id": arxiv_id,
        "title": paper.get("title"),
        "year": paper.get("year"),
        "venue": paper.get("venue"),
        "authors": [author.get("name") for author in (paper.get("authors") or []) if author.get("name")],
        "citation_count": paper.get("citationCount", 0) or 0,
        "reference_count": paper.get("referenceCount", 0) or 0,
        "url": paper.get("url"),
        "provider": provider,
        "provider_ids": {
            "openalex": openalex_id,
            "semantic_scholar": paper.get("paperId"),
            "s2_corpus_id": str(paper.get("corpusId")) if paper.get("corpusId") else None,
        },
    }


def _merge_identity(primary: dict[str, Any] | None, secondary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not primary:
        return secondary
    if not secondary:
        return primary
    merged = dict(primary)
    for key in ("openalex_id", "s2_id", "s2_corpus_id", "doi", "arxiv_id", "title", "year", "venue", "url"):
        if not merged.get(key) and secondary.get(key):
            merged[key] = secondary[key]
    if not merged.get("authors") and secondary.get("authors"):
        merged["authors"] = secondary["authors"]
    provider_ids = dict(secondary.get("provider_ids") or {})
    provider_ids.update({k: v for k, v in (primary.get("provider_ids") or {}).items() if v})
    merged["provider_ids"] = provider_ids
    merged["resolved_providers"] = sorted({primary.get("provider"), secondary.get("provider")} - {None})
    return merged


def _paper_key(paper: dict[str, Any]) -> str:
    for key in ("doi", "openalex_id", "s2_id", "s2_corpus_id"):
        value = paper.get(key)
        if value:
            return f"{key}:{str(value).lower()}"
    title = (paper.get("title") or "").strip().lower()
    year = paper.get("year") or ""
    return f"title:{title}:{year}"


def _merge_papers(*paper_lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for papers in paper_lists:
        for paper in papers:
            key = _paper_key(paper)
            if key in merged:
                merged[key] = _merge_identity(merged[key], paper) or merged[key]
            else:
                merged[key] = paper
    return list(merged.values())


def _apply_filters(papers: list[dict[str, Any]], request: CitationLookupRequest) -> list[dict[str, Any]]:
    filtered = papers
    if request.year_start is not None:
        filtered = [paper for paper in filtered if paper.get("year") is None or paper.get("year") >= request.year_start]
    if request.year_end is not None:
        filtered = [paper for paper in filtered if paper.get("year") is None or paper.get("year") <= request.year_end]
    if request.min_citations:
        filtered = [paper for paper in filtered if (paper.get("citation_count") or 0) >= request.min_citations]
    return filtered[: request.limit]


class CitationGraphService:
    """Resolve paper identities and query citation graph providers."""

    def __init__(
        self,
        *,
        openalex: OpenAlexAPIProvider | None = None,
        semantic_scholar: SemanticScholarAPIProvider | None = None,
    ) -> None:
        self.openalex = openalex or OpenAlexAPIProvider()
        self.semantic_scholar = semantic_scholar or SemanticScholarAPIProvider()

    async def resolve(self, request: CitationResolveRequest) -> tuple[dict[str, Any] | None, list[str], dict[str, Any]]:
        diagnostics: list[str] = []
        metadata: dict[str, Any] = {"provider": request.provider}

        openalex_identity: dict[str, Any] | None = None
        s2_identity: dict[str, Any] | None = None

        openalex_identity = await self._resolve_openalex(request, diagnostics)

        if request.provider == "auto" and not openalex_identity:
            diagnostics.append("OpenAlex could not resolve the identity; trying Semantic Scholar fallback.")
            s2_identity = await self._resolve_s2(request, diagnostics)
            if s2_identity:
                openalex_identity = await self._resolve_openalex_from_identity(s2_identity, diagnostics)

        identity = _merge_identity(openalex_identity, s2_identity)
        if identity and request.title:
            identity["title_match_score"] = _title_score(request.title, identity.get("title"))
        metadata["resolved_from"] = [item for item, data in [("openalex", openalex_identity), ("semantic_scholar", s2_identity)] if data]
        return identity, diagnostics, metadata

    async def lookup(self, request: CitationLookupRequest, *, direction: str = "both") -> MetaSciResult:
        resolve_request = CitationResolveRequest(
            title=request.title,
            doi=request.doi,
            arxiv_id=request.arxiv_id,
            openalex_id=request.openalex_id,
            s2_id=request.s2_id,
            s2_corpus_id=request.s2_corpus_id,
            provider=request.provider,
        )
        identity, diagnostics, metadata = await self.resolve(resolve_request)
        if not identity:
            return MetaSciResult(
                command="citations.lookup",
                input=request.model_dump(mode="json"),
                data={"resolved_identity": None, "references": [], "citations": []},
                metadata={**metadata, "returned_count": 0},
                diagnostics=diagnostics or ["Could not resolve paper identity."],
            )

        references: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        provider_counts: dict[str, Any] = {}

        if direction in ("references", "both"):
            references, ref_diag = await self._fetch_openalex_edges(identity, request, direction="references")
            diagnostics.extend(ref_diag)
        if direction in ("citations", "both"):
            citations, cit_diag = await self._fetch_openalex_edges(identity, request, direction="citations")
            diagnostics.extend(cit_diag)

        openalex_reference_count = len(references)
        openalex_citation_count = len(citations)
        s2_references: list[dict[str, Any]] = []
        s2_citations: list[dict[str, Any]] = []
        supplement_directions = self._s2_supplement_directions(identity, request, references, citations, direction=direction)
        if supplement_directions:
            s2_identifier = await self._s2_identifier_for_identity(identity, diagnostics)
            if not s2_identifier:
                diagnostics.append(
                    f"Semantic Scholar supplement skipped for {', '.join(supplement_directions)}: no S2 paper ID resolved."
                )
            else:
                for supplement_direction in supplement_directions:
                    diagnostics.append(
                        f"Semantic Scholar {supplement_direction} supplement triggered after OpenAlex returned "
                        f"{len(references) if supplement_direction == 'references' else len(citations)} records."
                    )
                    s2_papers, s2_diag = await self._fetch_s2_edges(
                        s2_identifier, request, direction=supplement_direction
                    )
                    diagnostics.extend(s2_diag)
                    if supplement_direction == "references":
                        s2_references = s2_papers
                    else:
                        s2_citations = s2_papers

        references = _apply_filters(_merge_papers(references, s2_references), request)
        citations = _apply_filters(_merge_papers(citations, s2_citations), request)

        if direction in ("references", "both"):
            provider_counts["references"] = {
                "openalex": openalex_reference_count,
                "semantic_scholar": len(s2_references),
                "merged": len(references),
            }
        if direction in ("citations", "both"):
            provider_counts["citations"] = {
                "openalex": openalex_citation_count,
                "semantic_scholar": len(s2_citations),
                "merged": len(citations),
            }

        returned_count = len(references) + len(citations)
        return MetaSciResult(
            command="citations.lookup",
            input=request.model_dump(mode="json"),
            data={
                "resolved_identity": identity,
                "references": references,
                "citations": citations,
                "provider_counts": provider_counts,
            },
            metadata={**metadata, "returned_count": returned_count},
            diagnostics=diagnostics,
        )

    async def _fetch_openalex_edges(
        self,
        identity: dict[str, Any],
        request: CitationLookupRequest,
        *,
        direction: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        diagnostics: list[str] = []
        openalex_papers: list[dict[str, Any]] = []

        if identity.get("openalex_id"):
            try:
                if direction == "references":
                    openalex_papers = await self._openalex_references(identity["openalex_id"], limit=request.limit)
                else:
                    openalex_papers = await self._openalex_citations(identity["openalex_id"], limit=request.limit)
            except httpx.HTTPError as exc:
                diagnostics.append(f"OpenAlex {direction} lookup failed: {exc}")
        else:
            diagnostics.append(f"OpenAlex {direction} lookup skipped: no OpenAlex work ID resolved.")

        return _apply_filters(openalex_papers, request), diagnostics

    async def _fetch_s2_edges(
        self,
        s2_identifier: str,
        request: CitationLookupRequest,
        *,
        direction: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        diagnostics: list[str] = []
        try:
            raw = (
                await self.semantic_scholar.references(s2_identifier, limit=request.limit)
                if direction == "references"
                else await self.semantic_scholar.citations(s2_identifier, limit=request.limit)
            )
            return [paper for paper in (_normalize_s2_paper(item) for item in raw) if paper], diagnostics
        except SemanticScholarPartialError as exc:
            diagnostics.append(f"Semantic Scholar {direction} supplement partially failed: {exc}")
            return [paper for paper in (_normalize_s2_paper(item) for item in exc.records) if paper], diagnostics
        except httpx.HTTPError as exc:
            diagnostics.append(f"Semantic Scholar {direction} supplement failed: {exc}")
            return [], diagnostics

    def _s2_supplement_directions(
        self,
        identity: dict[str, Any],
        request: CitationLookupRequest,
        references: list[dict[str, Any]],
        citations: list[dict[str, Any]],
        *,
        direction: str,
    ) -> list[str]:
        if request.provider != "auto":
            return []
        requested = [item for item in ("references", "citations") if direction in (item, "both")]
        missing_or_gappy = [
            item
            for item in requested
            if self._should_supplement_with_s2(
                identity,
                item,
                len(references) if item == "references" else len(citations),
                request.limit,
            )
        ]
        if direction == "both" and missing_or_gappy:
            return requested
        return missing_or_gappy

    def _should_supplement_with_s2(self, identity: dict[str, Any], direction: str, openalex_count: int, limit: int) -> bool:
        if openalex_count == 0:
            return True
        expected_key = "reference_count" if direction == "references" else "citation_count"
        expected = identity.get(expected_key) or 0
        if expected <= 0 or expected > limit:
            return False
        return abs(expected - openalex_count) / expected >= 0.33

    async def _s2_identifier_for_identity(self, identity: dict[str, Any], diagnostics: list[str]) -> str | None:
        if identity.get("s2_id"):
            return identity["s2_id"]
        if identity.get("s2_corpus_id"):
            return f"CorpusId:{identity['s2_corpus_id']}"
        s2_identity = await self._resolve_s2_from_identity(identity, diagnostics)
        if not s2_identity:
            return None
        identity.update(_merge_identity(identity, s2_identity) or identity)
        if identity.get("s2_id"):
            return identity["s2_id"]
        if identity.get("s2_corpus_id"):
            return f"CorpusId:{identity['s2_corpus_id']}"
        return None

    async def _resolve_openalex(self, request: CitationResolveRequest, diagnostics: list[str]) -> dict[str, Any] | None:
        identifier = request.openalex_id
        doi = _normalize_doi(request.doi)
        arxiv = _normalize_arxiv(request.arxiv_id)
        if not identifier and doi:
            identifier = f"doi:{doi}"
        if not identifier and arxiv:
            identifier = f"https://arxiv.org/abs/{arxiv}"
        if identifier:
            try:
                work = await self.openalex._get_json(f"/works/{self.openalex._work_identifier(identifier)}")
                return _normalize_openalex_work(work)
            except httpx.HTTPError as exc:
                diagnostics.append(f"OpenAlex identity lookup failed for {identifier!r}: {exc}")
        if request.title:
            try:
                payload = await self.openalex._get_json(
                    "/works",
                    params={"search": request.title, "per_page": 3, "select": "id,doi,title,display_name,publication_year,cited_by_count,primary_location,authorships,referenced_works"},
                )
                results = payload.get("results") or []
                if not results:
                    return None
                if len(results) > 1:
                    diagnostics.append("OpenAlex title lookup returned multiple candidates; selected the top search result.")
                return _normalize_openalex_work(results[0])
            except httpx.HTTPError as exc:
                diagnostics.append(f"OpenAlex title lookup failed: {exc}")
        return None

    async def _resolve_openalex_from_identity(self, identity: dict[str, Any], diagnostics: list[str]) -> dict[str, Any] | None:
        request = CitationResolveRequest(
            title=identity.get("title"),
            doi=identity.get("doi"),
            arxiv_id=identity.get("arxiv_id"),
            openalex_id=identity.get("openalex_id"),
            provider="openalex",
        )
        return await self._resolve_openalex(request, diagnostics)

    async def _resolve_s2(self, request: CitationResolveRequest, diagnostics: list[str]) -> dict[str, Any] | None:
        identifier = request.s2_id
        doi = _normalize_doi(request.doi)
        arxiv = _normalize_arxiv(request.arxiv_id)
        if not identifier and request.s2_corpus_id:
            identifier = f"CorpusId:{request.s2_corpus_id}"
        if not identifier and doi:
            identifier = f"DOI:{doi}"
        if not identifier and arxiv:
            identifier = f"ARXIV:{arxiv}"
        if identifier:
            try:
                paper = await self.semantic_scholar.get_paper(identifier)
                return _normalize_s2_paper(paper)
            except httpx.HTTPError as exc:
                diagnostics.append(f"Semantic Scholar identity lookup failed for {identifier!r}: {exc}")
        if request.title:
            try:
                results = await self.semantic_scholar.search_paper(request.title, limit=3)
                if not results:
                    return None
                if len(results) > 1:
                    diagnostics.append("Semantic Scholar title lookup returned multiple candidates; selected the top search result.")
                return _normalize_s2_paper(results[0])
            except httpx.HTTPError as exc:
                diagnostics.append(f"Semantic Scholar title lookup failed: {exc}")
        return None

    async def _resolve_s2_from_identity(self, identity: dict[str, Any], diagnostics: list[str]) -> dict[str, Any] | None:
        request = CitationResolveRequest(
            title=identity.get("title"),
            doi=identity.get("doi"),
            arxiv_id=identity.get("arxiv_id"),
            s2_id=identity.get("s2_id"),
            s2_corpus_id=identity.get("s2_corpus_id"),
            provider="auto",
        )
        return await self._resolve_s2(request, diagnostics)

    async def _openalex_references(self, openalex_id: str, *, limit: int) -> list[dict[str, Any]]:
        work = await self.openalex._get_json(f"/works/{self.openalex._work_identifier(openalex_id)}")
        ref_ids = [_compact_openalex_id(item) for item in (work.get("referenced_works") or [])][:limit]
        return await self._openalex_get_many(ref_ids, limit=limit)

    async def _openalex_citations(self, openalex_id: str, *, limit: int) -> list[dict[str, Any]]:
        records, _meta = await self.openalex._fetch_cursor(
            "/works",
            params={
                "filter": f"cites:{_openalex_url(openalex_id)}",
                "per_page": min(limit, 100),
                "cursor": "*",
                "select": "id,doi,title,display_name,publication_year,cited_by_count,primary_location,authorships,referenced_works",
            },
            limit=limit,
        )
        return [paper for paper in (_normalize_openalex_work(item) for item in records) if paper][:limit]

    async def _openalex_get_many(self, openalex_ids: list[str], *, limit: int) -> list[dict[str, Any]]:
        if not openalex_ids:
            return []
        papers: list[dict[str, Any]] = []
        for start in range(0, min(len(openalex_ids), limit), 50):
            batch = openalex_ids[start : start + 50]
            filter_value = "|".join(_openalex_url(item) or item for item in batch)
            payload = await self.openalex._get_json(
                "/works",
                params={
                    "filter": f"openalex:{filter_value}",
                    "per_page": len(batch),
                    "select": "id,doi,title,display_name,publication_year,cited_by_count,primary_location,authorships,referenced_works",
                },
            )
            papers.extend(paper for paper in (_normalize_openalex_work(item) for item in (payload.get("results") or [])) if paper)
        return papers[:limit]

async def resolve(**kwargs: Any) -> MetaSciResult:
    """Resolve one paper identity across citation graph providers."""
    request = CitationResolveRequest(**kwargs)
    service = CitationGraphService()
    identity, diagnostics, metadata = await service.resolve(request)
    return MetaSciResult(
        command="citations.resolve",
        input=request.model_dump(mode="json"),
        data=identity,
        metadata={**metadata, "returned_count": 1 if identity else 0},
        diagnostics=diagnostics,
    )


async def lookup(**kwargs: Any) -> MetaSciResult:
    """Resolve one paper and fetch references, citations, or both."""
    request = CitationLookupRequest(**kwargs)
    return await CitationGraphService().lookup(request)


async def references(**kwargs: Any) -> MetaSciResult:
    """Resolve one paper and fetch works it references."""
    request = CitationLookupRequest(**kwargs)
    return await CitationGraphService().lookup(request, direction="references")


async def citations(**kwargs: Any) -> MetaSciResult:
    """Resolve one paper and fetch works that cite it."""
    request = CitationLookupRequest(**kwargs)
    return await CitationGraphService().lookup(request, direction="citations")
