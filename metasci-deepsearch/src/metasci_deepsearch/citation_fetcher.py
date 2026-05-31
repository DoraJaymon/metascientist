"""Citation fetcher — fetch references and citations from OpenAlex (primary) + S2 (fallback).

Ported from AcaDeepR/src/tools/paper_bigbang/citation_fetcher.py.
Removed: DB client dependency, src.* imports.
OpenAlex is primary for citation graph; S2 supplements when OA count gap ≥ 33%.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _get_paper_id(paper: Any) -> Optional[str]:
    """Extract the best available paper identifier."""
    if isinstance(paper, dict):
        pid = (paper.get("openalex_id") or paper.get("corpus_id")
               or paper.get("id") or paper.get("corpusId"))
    else:
        pid = (getattr(paper, "openalex_id", None) or getattr(paper, "corpus_id", None)
               or getattr(paper, "id", None))
    return str(pid) if pid else None


def _normalize_paper(paper: Any) -> Dict:
    """Ensure a paper is a plain dict with canonical field aliases."""
    if isinstance(paper, dict):
        d = paper.copy()
    elif hasattr(paper, "to_dict"):
        d = paper.to_dict()
    else:
        d = dict(paper)
    # Normalise citation_count ↔ cited_by_count
    if "cited_by_count" in d and "citation_count" not in d:
        d["citation_count"] = d["cited_by_count"]
    if "citation_count" in d and "cited_by_count" not in d:
        d["cited_by_count"] = d["citation_count"]
    if "publication_year" in d and "year" not in d:
        d["year"] = d["publication_year"]
    return d


class CitationFetcher:
    """Fetch references and citations with caching and S2 supplementation.

    Uses OpenAlex as the primary source.  S2 supplements citations when:
    - OpenAlex returns 0 results, OR
    - citation_count gap ≥ 33% and total citations > 300.
    """

    def __init__(
        self,
        openalex_client: Any = None,
        s2_client: Any = None,
    ) -> None:
        self._openalex = openalex_client
        self._s2 = s2_client

        self._refs_cache: Dict[str, List[str]] = {}
        self._citations_cache: Dict[str, List[str]] = {}
        self._paper_cache: Dict[str, Dict] = {}
        self._last_expanded_ids: List[str] = []
        self._last_expanded_ids_detail: Dict[str, List[str]] = {"openalex_ids": [], "corpus_ids": []}

    # -------------------------------------------------------------------------
    # Lazy clients
    # -------------------------------------------------------------------------

    @property
    def openalex(self) -> Any:
        if self._openalex is None:
            from metasci_deepsearch.providers.openalex_cite import OpenAlexCiteClient
            self._openalex = OpenAlexCiteClient()
        return self._openalex

    @property
    def s2(self) -> Any:
        if self._s2 is None:
            from metasci_deepsearch.providers.semantic_scholar import SemanticScholarSearchClient
            self._s2 = SemanticScholarSearchClient()
        return self._s2

    @property
    def paper_cache(self) -> Dict[str, Dict]:
        return self._paper_cache

    @property
    def last_expanded_ids(self) -> List[str]:
        return self._last_expanded_ids

    def add_to_cache(self, papers: List[Dict]) -> None:
        for p in papers:
            pid = _get_paper_id(p)
            if pid and pid not in self._paper_cache:
                self._paper_cache[pid] = _normalize_paper(p)

    def clear_cache(self) -> None:
        self._refs_cache.clear()
        self._citations_cache.clear()
        self._paper_cache.clear()
        self._last_expanded_ids.clear()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def fetch_refs(
        self,
        work_ids: List[str],
        limit_per_work: int = 100,
        force: bool = False,
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, List[Dict]]:
        """Fetch referenced works (backward citations) for a list of OpenAlex work IDs."""
        if not work_ids:
            return {}

        to_fetch = work_ids if force else [wid for wid in work_ids if wid not in self._refs_cache]

        if to_fetch:
            logger.info("Fetching refs for %d papers via OpenAlex...", len(to_fetch))
            batch_results = await self.openalex.batch_get_refs(
                work_ids=to_fetch,
                limit_per_work=limit_per_work,
                progress_callback=progress_callback,
            )
            for work_id, refs in batch_results.items():
                ref_ids = []
                for ref in refs:
                    ref = _normalize_paper(ref)
                    rid = _get_paper_id(ref)
                    if rid:
                        ref_ids.append(rid)
                        self._paper_cache.setdefault(rid, ref)
                self._refs_cache[work_id] = ref_ids

        result: Dict[str, List[Dict]] = {}
        expanded_ids, openalex_ids, corpus_ids = [], [], []

        for work_id in work_ids:
            if work_id in self._refs_cache:
                ref_ids = self._refs_cache[work_id]
                refs = [self._paper_cache[rid] for rid in ref_ids if rid in self._paper_cache]
                result[work_id] = refs
                expanded_ids.extend(ref_ids)
                for rid in ref_ids:
                    p = self._paper_cache.get(rid, {})
                    oaid = p.get("openalex_id") or p.get("id")
                    if oaid:
                        openalex_ids.append(str(oaid))
                    cid = p.get("corpus_id") or p.get("corpusId")
                    if cid:
                        corpus_ids.append(str(cid))

        self._last_expanded_ids = list(set(expanded_ids))
        self._last_expanded_ids_detail = {
            "openalex_ids": list(set(openalex_ids)),
            "corpus_ids": list(set(corpus_ids)),
        }
        return result

    async def fetch_citations(
        self,
        work_ids: List[str],
        year_range: Optional[Tuple[int, int]] = None,
        min_cited_by: int = 0,
        max_per_work: Optional[int] = None,
        supplement_with_s2: bool = False,
        force: bool = False,
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, List[Dict]]:
        """Fetch citing papers (forward citations) for a list of OpenAlex work IDs."""
        if not work_ids:
            return {}

        to_fetch = work_ids if force else [wid for wid in work_ids if wid not in self._citations_cache]

        if to_fetch:
            batch_results = await self._fetch_citations_openalex(
                to_fetch, year_range, min_cited_by, max_per_work,
                supplement_with_s2, progress_callback,
            )
            for work_id, cits in batch_results.items():
                cit_ids = []
                for cit in cits:
                    cit = _normalize_paper(cit)
                    cid = _get_paper_id(cit)
                    if cid:
                        cit_ids.append(cid)
                        self._paper_cache.setdefault(cid, cit)
                self._citations_cache[work_id] = cit_ids

        all_ids, openalex_ids, corpus_ids = [], [], []
        result: Dict[str, List[Dict]] = {}

        for work_id in work_ids:
            if work_id in self._citations_cache:
                cit_ids = self._citations_cache[work_id]
                result[work_id] = [self._paper_cache[cid] for cid in cit_ids if cid in self._paper_cache]
                all_ids.extend(cit_ids)
                for cid in cit_ids:
                    p = self._paper_cache.get(cid, {})
                    oaid = p.get("openalex_id") or p.get("id")
                    if oaid:
                        openalex_ids.append(str(oaid))
                    c = p.get("corpus_id") or p.get("corpusId")
                    if c:
                        corpus_ids.append(str(c))

        self._last_expanded_ids = list(set(all_ids))
        self._last_expanded_ids_detail = {
            "openalex_ids": list(set(openalex_ids)),
            "corpus_ids": list(set(corpus_ids)),
        }
        return result

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    async def _fetch_citations_openalex(
        self,
        work_ids: List[str],
        year_range: Optional[Tuple[int, int]],
        min_cited_by: int,
        max_per_work: Optional[int],
        supplement_with_s2: bool,
        progress_callback: Optional[Callable],
    ) -> Dict[str, List[Dict]]:
        batch_results = await self.openalex.batch_get_citations(
            work_ids=work_ids,
            year_range=year_range,
            min_cited_by=min_cited_by,
            max_per_work=max_per_work,
            progress_callback=progress_callback,
        )

        if not supplement_with_s2:
            return batch_results

        # S2 supplementation
        for work_id in work_ids:
            oa_cits = batch_results.get(work_id, [])
            paper_info = self._paper_cache.get(work_id, {})
            cit_count = paper_info.get("cited_by_count", 0) or paper_info.get("citation_count", 0)
            if not self._should_supplement(cit_count, len(oa_cits)):
                continue
            s2_cits = await self._s2_citations(paper_info)
            if s2_cits:
                merged = self._merge_by_title(oa_cits, s2_cits)
                if len(merged) > len(oa_cits):
                    batch_results[work_id] = merged

        return batch_results

    def _should_supplement(self, citation_count: int, fetched_count: int) -> bool:
        if fetched_count == 0:
            return True
        if citation_count <= 300:
            return False
        return abs(citation_count - fetched_count) / citation_count >= 0.33

    async def _s2_citations(self, paper_info: Dict) -> List[Dict]:
        title = (paper_info.get("title") or "").strip()
        if not title:
            return []
        try:
            async with self.s2 as s2:
                s2_papers = await s2.get_all_citations(title=title, max_citations=500, batch_size=100)
            return [_s2_to_oa(p) for p in (s2_papers or [])]
        except Exception as exc:
            logger.warning("S2 citation fallback failed: %s", exc)
            return []

    @staticmethod
    def _merge_by_title(primary: List[Dict], secondary: List[Dict]) -> List[Dict]:
        titles = {(p.get("title") or "").strip().lower() for p in primary}
        merged = list(primary)
        for p in secondary:
            t = (p.get("title") or "").strip().lower()
            if t and t not in titles:
                merged.append(p)
                titles.add(t)
        return merged

    @staticmethod
    def _apply_filters(
        papers: List[Dict],
        year_range: Optional[Tuple[int, int]],
        min_cited_by: int,
    ) -> List[Dict]:
        if year_range:
            papers = [p for p in papers if p.get("year") and year_range[0] <= p["year"] <= year_range[1]]
        if min_cited_by > 0:
            papers = [p for p in papers if (p.get("citation_count") or p.get("cited_by_count") or 0) >= min_cited_by]
        return papers


def _s2_to_oa(s2_paper: Any) -> Dict:
    """Convert a S2 Paper object to an OpenAlex-compatible dict."""
    ei = s2_paper.external_info if hasattr(s2_paper, "external_info") and s2_paper.external_info else {}
    corpus_id = ei.get("corpusId", "")
    return {
        "id": corpus_id or getattr(s2_paper, "paper_id", ""),
        "openalex_id": None,
        "corpus_id": corpus_id,
        "title": getattr(s2_paper, "title", ""),
        "abstract": getattr(s2_paper, "abstract", ""),
        "year": getattr(s2_paper, "year", None),
        "publication_year": getattr(s2_paper, "year", None),
        "doi": getattr(s2_paper, "doi", None),
        "venue": getattr(s2_paper, "venue", ""),
        "citation_count": getattr(s2_paper, "citation_count", 0),
        "cited_by_count": getattr(s2_paper, "citation_count", 0),
        "url": getattr(s2_paper, "url", ""),
        "authors": [{"display_name": a} for a in (getattr(s2_paper, "authors", []) or [])],
        "referenced_works": ei.get("references", []),
        "_source": "semantic_scholar",
    }
