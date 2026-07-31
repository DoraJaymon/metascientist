"""OpenAlex citation-graph access for CiteFlow.

Built on ``metasci_universe.providers.openalex_api.OpenAlexAPIProvider`` rather than a
standalone client, so it inherits that provider's async httpx transport, polite-pool
auth and cursor pagination.

Two things the previous port got wrong are fixed here:

* **Abstracts.** OpenAlex ships abstracts as an inverted index; the previous port
  hardcoded ``abstract == ""``.  Since the reranker scores ``f"{title}. {abstract}"``
  and the seed-selection prompt shows abstracts, dropping them degraded exactly the
  papers that arrive via citation expansion — the bulk of the store.
* **Forward-citation breadth.** The previous port issued a single request capped at
  ``per_page<=200`` and never paginated, so a seed with thousands of citing papers
  contributed at most 200.  Here forward citations are batched, filtered server-side and
  paginated through the cursor API.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

WORK_SELECT = ",".join(
    [
        "id",
        "ids",
        "doi",
        "title",
        "display_name",
        "publication_year",
        "cited_by_count",
        "referenced_works",
        "primary_location",
        "authorships",
        "abstract_inverted_index",
    ]
)

# OpenAlex accepts up to 50 OR-ed values in a single filter clause.
BATCH = 50

FIELD_IDS = {
    "computer science": "fields/17",
    "medicine": "fields/27",
    "biology": "fields/13",
    "physics": "fields/31",
    "mathematics": "fields/26",
    "engineering": "fields/22",
    "psychology": "fields/32",
    "social sciences": "fields/33",
}


def compact_id(value: Any) -> str:
    """``https://openalex.org/W123`` -> ``W123``."""
    if value is None:
        return ""
    text = str(value).strip()
    if text.startswith("https://openalex.org/"):
        return text.rsplit("/", 1)[-1]
    return text


def is_work_id(value: str) -> bool:
    return bool(value) and value.startswith("W")


def reconstruct_abstract(inverted_index: Optional[Dict[str, List[int]]]) -> str:
    """Rebuild abstract text from OpenAlex's ``abstract_inverted_index``."""
    if not inverted_index:
        return ""
    positions: List[Tuple[int, str]] = []
    for word, slots in inverted_index.items():
        for slot in slots or []:
            positions.append((slot, word))
    if not positions:
        return ""
    positions.sort(key=lambda pair: pair[0])
    return " ".join(word for _, word in positions)


def normalise_doi(doi: Optional[str]) -> str:
    if not doi:
        return ""
    text = str(doi).strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text


def parse_work(work: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Normalise a raw OpenAlex work into a CuraLib-compatible paper dict."""
    if not work:
        return None
    oa_id = compact_id(work.get("id"))
    if not oa_id:
        return None

    ids = work.get("ids") or {}
    referenced = [compact_id(ref) for ref in (work.get("referenced_works") or [])]
    referenced = [ref for ref in referenced if is_work_id(ref)]
    cited_by = work.get("cited_by_count") or 0
    venue = ((work.get("primary_location") or {}).get("source") or {}).get("display_name", "") or ""
    authors = [
        (authorship.get("author") or {}).get("display_name", "")
        for authorship in (work.get("authorships") or [])
    ]

    return {
        "id": oa_id,
        "openalex_id": oa_id,
        "corpus_id": "",  # filled by the caller when an S2 identity is known
        "mag_id": str(ids.get("mag") or "") or None,
        "doi": normalise_doi(work.get("doi") or ids.get("doi")),
        "title": work.get("title") or work.get("display_name") or "",
        "abstract": reconstruct_abstract(work.get("abstract_inverted_index")),
        "year": work.get("publication_year"),
        "publication_year": work.get("publication_year"),
        "authors": [name for name in authors if name],
        "venue": venue,
        "citation_count": cited_by,
        "cited_by_count": cited_by,
        "reference_count": len(referenced),
        "referenced_works": referenced,
        "reference_ids": referenced,
        "url": f"https://openalex.org/{oa_id}",
        "_source": "openalex",
    }


def _chunks(items: Sequence[str], size: int = BATCH) -> Iterable[List[str]]:
    for start in range(0, len(items), size):
        chunk = [item for item in items[start : start + size] if item]
        if chunk:
            yield chunk


class OpenAlexGraph:
    """Citation-graph operations over OpenAlex."""

    def __init__(self, provider: Any = None) -> None:
        if provider is None:
            from metasci_universe.providers.openalex_api import OpenAlexAPIProvider

            provider = OpenAlexAPIProvider()
        self._provider = provider

    # -- low level ---------------------------------------------------------

    async def _filtered(
        self, filter_str: str, *, limit: int, extra_params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "filter": filter_str,
            "select": WORK_SELECT,
            "cursor": "*",
        }
        if extra_params:
            params.update(extra_params)
        records, _meta = await self._provider._fetch_cursor("/works", params=params, limit=limit)
        return records

    # -- keyword search (fallback for Semantic Scholar) ---------------------

    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
        year: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Keyword search over titles and abstracts.

        Used when Semantic Scholar is unavailable.  Results are already OpenAlex works,
        so they need no resolution step — but recall on natural-language research
        questions is weaker than S2's, so this is a fallback rather than the default.
        """
        clauses = []
        if year:
            text = str(year).strip()
            if "-" in text:
                start, _, end = text.partition("-")
                if start and end:
                    clauses.append(f"publication_year:{start}-{end}")
                elif start:
                    clauses.append(f"publication_year:>{int(start) - 1}")
                elif end:
                    clauses.append(f"publication_year:<{int(end) + 1}")
            elif text:
                clauses.append(f"publication_year:{text}")

        params: Dict[str, Any] = {"search": query}
        filter_str = ",".join(clauses) if clauses else "type:article"
        records = await self._filtered(filter_str, limit=limit, extra_params=params)
        return [paper for paper in (parse_work(raw) for raw in records) if paper]

    # -- hydration ---------------------------------------------------------

    async def get_by_ids(self, openalex_ids: Sequence[str]) -> List[Optional[Dict[str, Any]]]:
        """Fetch full metadata for OpenAlex ids, preserving input order."""
        wanted = [compact_id(value) for value in openalex_ids]
        valid = [value for value in wanted if is_work_id(value)]
        found: Dict[str, Dict[str, Any]] = {}

        for chunk in _chunks(valid):
            filter_str = "openalex:" + "|".join(chunk)
            for raw in await self._filtered(filter_str, limit=len(chunk)):
                parsed = parse_work(raw)
                if parsed:
                    found[parsed["openalex_id"]] = parsed

        return [found.get(value) for value in wanted]

    # -- resolution (Semantic Scholar -> OpenAlex) --------------------------

    async def resolve_many(
        self, queries: Sequence[Dict[str, str]]
    ) -> List[Optional[Dict[str, Any]]]:
        """Resolve papers to OpenAlex works.

        Each query is ``{"doi": ...}``, ``{"mag": ...}`` and/or ``{"title": ...}``.
        DOI is tried first (exact, batched 50 per request), then MAG id — Semantic
        Scholar returns MAG ids and OpenAlex indexes them, which is far more reliable
        than title matching — then a per-paper title search as last resort.
        """
        results: List[Optional[Dict[str, Any]]] = [None] * len(queries)

        # Pass 1: DOI
        by_doi: Dict[str, List[int]] = {}
        for index, query in enumerate(queries):
            doi = normalise_doi(query.get("doi"))
            if doi:
                by_doi.setdefault(doi, []).append(index)
        if by_doi:
            dois = list(by_doi)
            for chunk in _chunks(dois):
                filter_str = "doi:" + "|".join(chunk)
                for raw in await self._filtered(filter_str, limit=len(chunk)):
                    parsed = parse_work(raw)
                    if not parsed:
                        continue
                    for index in by_doi.get(parsed["doi"], []):
                        results[index] = parsed

        # Pass 2: MAG
        by_mag: Dict[str, List[int]] = {}
        for index, query in enumerate(queries):
            if results[index] is not None:
                continue
            mag = str(query.get("mag") or "").strip()
            if mag:
                by_mag.setdefault(mag, []).append(index)
        if by_mag:
            for chunk in _chunks(list(by_mag)):
                filter_str = "mag:" + "|".join(chunk)
                for raw in await self._filtered(filter_str, limit=len(chunk)):
                    parsed = parse_work(raw)
                    if not parsed or not parsed.get("mag_id"):
                        continue
                    for index in by_mag.get(parsed["mag_id"], []):
                        results[index] = parsed

        # Pass 3: title search, one request each
        for index, query in enumerate(queries):
            if results[index] is not None:
                continue
            title = (query.get("title") or "").strip()
            if not title:
                continue
            try:
                raw_records = await self._filtered(
                    "type:article", limit=1, extra_params={"search": title}
                )
            except Exception as exc:  # network/API hiccup should not abort the batch
                logger.warning("OpenAlex title lookup failed for %r: %s", title[:60], exc)
                continue
            parsed = parse_work(raw_records[0]) if raw_records else None
            if parsed and _titles_match(title, parsed.get("title", "")):
                results[index] = parsed

        return results

    # -- backward expansion ------------------------------------------------

    async def get_references(self, openalex_id: str, *, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch the works a paper cites (hydrated)."""
        oa_id = compact_id(openalex_id)
        if not is_work_id(oa_id):
            return []
        works = await self.get_by_ids([oa_id])
        work = works[0] if works else None
        if not work:
            return []
        ref_ids = work.get("reference_ids", [])[:limit]
        return [paper for paper in await self.get_by_ids(ref_ids) if paper]

    async def batch_get_references(
        self, openalex_ids: Sequence[str], *, limit_per_work: int = 100
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch references for several papers, hydrating each unique work only once."""
        seeds = [compact_id(value) for value in openalex_ids]
        seeds = [value for value in seeds if is_work_id(value)]
        if not seeds:
            return {}

        seed_works = await self.get_by_ids(seeds)
        wanted: Dict[str, List[str]] = {}
        all_ref_ids: List[str] = []
        for seed_id, work in zip(seeds, seed_works):
            ref_ids = (work or {}).get("reference_ids", [])[:limit_per_work]
            wanted[seed_id] = ref_ids
            all_ref_ids.extend(ref_ids)

        unique_refs = list(dict.fromkeys(all_ref_ids))
        hydrated = await self.get_by_ids(unique_refs)
        lookup = {paper["openalex_id"]: paper for paper in hydrated if paper}

        return {
            seed_id: [lookup[ref] for ref in ref_ids if ref in lookup]
            for seed_id, ref_ids in wanted.items()
        }

    # -- forward expansion -------------------------------------------------

    async def get_citations(
        self,
        openalex_ids: Sequence[str],
        *,
        year_range: Optional[Tuple[Optional[int], Optional[int]]] = None,
        min_cited_by: int = 0,
        field_id: Optional[str] = None,
        max_per_work: Optional[int] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch citing works for each seed, filtered server-side and fully paginated.

        Seeds are queried one at a time so each citing paper can be attributed to the
        seed it cites.  Filters are pushed into the OpenAlex query rather than applied
        after truncation, which is what makes the ``min_citations`` / ``year_start``
        decisions meaningful.
        """
        seeds = [compact_id(value) for value in openalex_ids]
        seeds = [value for value in seeds if is_work_id(value)]
        results: Dict[str, List[Dict[str, Any]]] = {}

        for seed_id in seeds:
            clauses = [f"cites:{seed_id}"]
            if year_range:
                start, end = year_range
                if start is not None and end is not None:
                    clauses.append(f"publication_year:{start}-{end}")
                elif start is not None:
                    clauses.append(f"publication_year:>{start - 1}")
                elif end is not None:
                    clauses.append(f"publication_year:<{end + 1}")
            if min_cited_by > 0:
                # OpenAlex range filters are strict, so ">= n" is expressed as "> n-1".
                clauses.append(f"cited_by_count:>{min_cited_by - 1}")
            if field_id:
                clauses.append(f"primary_topic.field.id:{field_id}")

            limit = max_per_work if max_per_work is not None else 10_000
            try:
                raw_records = await self._filtered(",".join(clauses), limit=limit)
            except Exception as exc:
                logger.warning("OpenAlex forward citations failed for %s: %s", seed_id, exc)
                results[seed_id] = []
                continue

            papers = [parse_work(raw) for raw in raw_records]
            results[seed_id] = [paper for paper in papers if paper]

        return results


def _titles_match(query: str, candidate: str, threshold: float = 0.94) -> bool:
    from difflib import SequenceMatcher

    left = " ".join(query.lower().split())
    right = " ".join((candidate or "").lower().split())
    if not left or not right:
        return False
    if left == right:
        return True
    return SequenceMatcher(None, left, right).ratio() >= threshold
