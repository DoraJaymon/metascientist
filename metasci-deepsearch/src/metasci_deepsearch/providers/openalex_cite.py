"""OpenAlex citation graph client for metasci-deepsearch.

Wraps pyalex to fetch referenced works (refs) and citing works (citations)
using the same email-polite approach as AcaDeepR's OpenAlexClient.

Only the methods needed by CitationFetcher are implemented here.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_EMAIL = os.getenv("OPENALEX_EMAIL", os.getenv("PYALEX_EMAIL", "research@example.com"))


def _clean_oa_id(oa_id: str) -> str:
    s = str(oa_id).strip()
    if s.startswith("https://openalex.org/"):
        s = s.replace("https://openalex.org/", "")
    return s


def _is_valid_oa_id(oa_id: str) -> bool:
    return bool(oa_id) and oa_id.startswith("W")


def _parse_work(w: Dict) -> Dict:
    """Convert a raw pyalex Work dict to a normalised paper dict."""
    oa_id = _clean_oa_id(w.get("id", ""))
    authors = [
        a.get("author", {}).get("display_name", "")
        for a in (w.get("authorships") or [])
    ]
    cited_by = w.get("cited_by_count", 0) or 0
    ref_works = [_clean_oa_id(r) for r in (w.get("referenced_works") or [])]
    return {
        "id": oa_id,
        "openalex_id": oa_id,
        "title": w.get("title", "") or "",
        "abstract": "",
        "year": w.get("publication_year"),
        "authors": authors,
        "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
        "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
        "citation_count": cited_by,
        "cited_by_count": cited_by,
        "reference_count": len(ref_works),
        "referenced_works": ref_works,
        "reference_ids": ref_works,
        "url": w.get("doi", "") or f"https://openalex.org/{oa_id}",
        "_source": "openalex",
    }


class OpenAlexCiteClient:
    """Thin pyalex wrapper for citation-graph operations.

    Provides batch_get_refs() and batch_get_citations() as expected by
    CitationFetcher.
    """

    def __init__(self, email: Optional[str] = None) -> None:
        self.email = email or _EMAIL
        self._configured = False

    def _ensure_pyalex(self) -> None:
        if self._configured:
            return
        try:
            import pyalex
            pyalex.config.email = self.email
            self._configured = True
        except ImportError as exc:
            raise ImportError("pyalex is required: pip install pyalex") from exc

    # -------------------------------------------------------------------------
    # References (backward citations)
    # -------------------------------------------------------------------------

    async def batch_get_refs(
        self,
        work_ids: List[str],
        limit_per_work: int = 100,
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, List[Dict]]:
        """Fetch referenced_works for each work_id via OpenAlex."""
        def _fetch() -> Dict[str, List[Dict]]:
            self._ensure_pyalex()
            from pyalex import Works

            results: Dict[str, List[Dict]] = {}
            for i, work_id in enumerate(work_ids, 1):
                clean = _clean_oa_id(work_id)
                if not _is_valid_oa_id(clean):
                    results[work_id] = []
                    continue
                try:
                    w_list = Works()[f"https://openalex.org/{clean}"]
                    if not w_list:
                        results[work_id] = []
                        continue
                    w = w_list if isinstance(w_list, dict) else w_list[0]
                    ref_ids = [_clean_oa_id(r) for r in (w.get("referenced_works") or [])]
                    ref_ids = ref_ids[:limit_per_work]
                    # Batch-fetch full metadata for ref IDs
                    refs = []
                    for j in range(0, len(ref_ids), 50):
                        batch = [rid for rid in ref_ids[j: j + 50] if _is_valid_oa_id(rid)]
                        if not batch:
                            continue
                        filter_str = "|".join(f"https://openalex.org/{rid}" for rid in batch)
                        batch_works = Works().filter(openalex=filter_str).get(per_page=50)
                        refs.extend(_parse_work(bw) for bw in batch_works)
                        time.sleep(0.3)
                    results[work_id] = refs
                    count = len(refs)
                except Exception as exc:
                    logger.warning("OA refs failed for %s: %s", work_id, exc)
                    results[work_id] = []
                    count = 0
                if progress_callback:
                    progress_callback(i, len(work_ids), work_id, count)
                time.sleep(0.3)
            return results

        return await asyncio.to_thread(_fetch)

    async def get_by_ids(self, ids: List[str], batch_size: int = 25) -> List[Optional[Dict]]:
        """Fetch full metadata for a list of OpenAlex IDs."""
        def _fetch() -> List[Optional[Dict]]:
            self._ensure_pyalex()
            from pyalex import Works

            clean_ids = [_clean_oa_id(i) for i in ids]
            id_map: Dict[str, Dict] = {}

            for i in range(0, len(clean_ids), batch_size):
                batch = [c for c in clean_ids[i: i + batch_size] if _is_valid_oa_id(c)]
                if not batch:
                    continue
                filter_str = "|".join(f"https://openalex.org/{c}" for c in batch)
                try:
                    works = Works().filter(openalex=filter_str).get(per_page=batch_size)
                    for w in works:
                        wid = _clean_oa_id(w.get("id", ""))
                        if wid:
                            id_map[wid] = _parse_work(w)
                except Exception as exc:
                    logger.warning("OA get_by_ids batch failed: %s", exc)
                time.sleep(0.5)

            return [id_map.get(c) for c in clean_ids]

        return await asyncio.to_thread(_fetch)

    # -------------------------------------------------------------------------
    # Citations (forward)
    # -------------------------------------------------------------------------

    async def batch_get_citations(
        self,
        work_ids: List[str],
        year_range: Optional[Tuple[int, int]] = None,
        min_cited_by: int = 0,
        max_per_work: Optional[int] = None,
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, List[Dict]]:
        """Fetch citing works for each work_id via OpenAlex."""
        def _fetch() -> Dict[str, List[Dict]]:
            self._ensure_pyalex()
            from pyalex import Works

            results: Dict[str, List[Dict]] = {}
            for i, work_id in enumerate(work_ids, 1):
                clean = _clean_oa_id(work_id)
                if not _is_valid_oa_id(clean):
                    results[work_id] = []
                    continue
                try:
                    q = Works().filter(cites=f"https://openalex.org/{clean}")
                    if year_range:
                        q = q.filter(publication_year=f"{year_range[0]}-{year_range[1]}")
                    if min_cited_by > 0:
                        q = q.filter(cited_by_count=f">{min_cited_by - 1}")

                    per_page = min(max_per_work or 200, 200)
                    cits_raw = q.get(per_page=per_page)
                    cits = [_parse_work(w) for w in cits_raw]
                    if max_per_work:
                        cits = cits[:max_per_work]
                    results[work_id] = cits
                    count = len(cits)
                except Exception as exc:
                    logger.warning("OA citations failed for %s: %s", work_id, exc)
                    results[work_id] = []
                    count = 0
                if progress_callback:
                    progress_callback(i, len(work_ids), work_id, count)
                time.sleep(0.3)
            return results

        return await asyncio.to_thread(_fetch)
