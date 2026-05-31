"""Citation network analysis — co-citation, in-domain scoring, seed discovery.

Ported from AcaDeepR/src/tools/paper_bigbang/citation_network.py.
Removed: src.* imports.  Accepts a PaperStore (CuraLib) instance.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple


class CitationNetwork:
    """Citation network analyser backed by a PaperStore.

    Responsibilities:
    1. Co-citation analysis — find papers commonly cited together.
    2. In-domain citation scoring — measure field relevance of each paper.
    3. Seed candidate discovery — rank papers by combined domain impact.
    """

    def __init__(self, store: Any) -> None:
        self.store = store
        self._in_domain_citation_counts: Optional[Counter] = None

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _get_paper_ids(self) -> Set[str]:
        return {str(p.openalex_id) for p in self.store.get_all_papers() if p.openalex_id}

    def _compute_in_domain_citations(self, force_refresh: bool = False) -> Counter:
        """Count how many papers in the store cite each paper (in-domain citations)."""
        if self._in_domain_citation_counts is not None and not force_refresh:
            return self._in_domain_citation_counts
        paper_ids = self._get_paper_ids()
        counts: Counter = Counter()
        for paper in self.store.get_all_papers():
            for ref_id in paper.reference_ids:
                if str(ref_id) in paper_ids:
                    counts[str(ref_id)] += 1
        self._in_domain_citation_counts = counts
        return counts

    def refresh(self) -> "CitationNetwork":
        self._in_domain_citation_counts = None
        return self

    @staticmethod
    def _normalize_ref_id(ref_id: str) -> str:
        ref_id_str = str(ref_id)
        if ref_id_str.startswith("https://openalex.org/"):
            return ref_id_str.replace("https://openalex.org/", "")
        return ref_id_str

    @staticmethod
    def _paper_to_dict(record: Any) -> Dict:
        if hasattr(record, "to_dict"):
            return record.to_dict()
        return dict(record) if not isinstance(record, dict) else record

    # -------------------------------------------------------------------------
    # Co-citation analysis
    # -------------------------------------------------------------------------

    def find_co_citations(
        self,
        refs_data: Dict[str, List[Dict]],
        min_count: int = 2,
        return_papers_only: bool = True,
    ) -> List[Dict]:
        """Find papers commonly co-cited by the source papers.

        Args:
            refs_data: {work_id: [ref_paper_dict, ...]}.
            min_count: Minimum number of citing papers to qualify.
            return_papers_only: If True return a flat list of paper dicts,
                                 else return dicts with co_citation_count.
        """
        ref_count: Dict[str, Dict] = {}
        for work_id, refs in refs_data.items():
            seen: Set[str] = set()
            for ref in refs:
                ref_id = ref.get("corpus_id") or ref.get("id") or ref.get("openalex_id")
                if not ref_id:
                    continue
                ref_id_str = str(ref_id)
                if ref_id_str in seen:
                    continue
                seen.add(ref_id_str)
                if ref_id_str not in ref_count:
                    ref_count[ref_id_str] = {"cited_by": [], "paper": ref}
                ref_count[ref_id_str]["cited_by"].append(work_id)

        co_citations = sorted(
            [
                {"paper": d["paper"], "co_citation_count": len(d["cited_by"]), "cited_by_works": d["cited_by"]}
                for d in ref_count.values()
                if len(d["cited_by"]) >= min_count
            ],
            key=lambda x: x["co_citation_count"],
            reverse=True,
        )
        return [item["paper"] for item in co_citations] if return_papers_only else co_citations

    def _collect_citation_stats(self, papers: List[Dict]) -> Tuple[Counter, Dict[str, List[str]]]:
        ref_counter: Counter = Counter()
        citing_map: Dict[str, List[str]] = defaultdict(list)
        for paper in papers:
            pid = paper.get("openalex_id") or paper.get("corpus_id") or paper.get("id")
            if not pid:
                continue
            ref_ids = paper.get("referenced_works") or paper.get("reference_ids", [])
            seen: Set[str] = set()
            for ref_id in ref_ids:
                if not ref_id:
                    continue
                r = self._normalize_ref_id(str(ref_id))
                if r in seen:
                    continue
                seen.add(r)
                ref_counter[r] += 1
                citing_map[r].append(str(pid))
        return ref_counter, dict(citing_map)

    async def compute_co_citations_from_papers(
        self,
        papers: List[Dict],
        min_count: int = 2,
        fetcher: Any = None,
        auto_fetch: bool = True,
        round_num: int = 0,
    ) -> Tuple[List[Dict], Dict[str, List[str]]]:
        """Compute co-citations directly from paper referenced_works / reference_ids.

        Returns (co_cited_papers, citing_map).
        """
        ref_counter, citing_map = self._collect_citation_stats(papers)
        co_cited_ids = sorted(
            [(rid, cnt) for rid, cnt in ref_counter.items() if cnt >= min_count],
            key=lambda x: x[1],
            reverse=True,
        )

        co_cited_papers: List[Dict] = []
        missing_papers: List[Tuple[str, int, int]] = []

        for ref_id, count in co_cited_ids:
            rec = self.store.get_paper(ref_id)
            if rec:
                d = self._paper_to_dict(rec)
                d["_co_citation_count"] = count
                co_cited_papers.append(d)
            else:
                co_cited_papers.append({"openalex_id": ref_id, "id": ref_id,
                                        "_co_citation_count": count, "_not_in_store": True})
                missing_papers.append((ref_id, count, len(co_cited_papers) - 1))

        if missing_papers and auto_fetch and fetcher:
            await self._fetch_and_save_missing(missing_papers, co_cited_papers, fetcher, round_num)

        return co_cited_papers, citing_map

    async def _fetch_and_save_missing(
        self,
        missing_papers: List[Tuple[str, int, int]],
        co_cited_papers: List[Dict],
        fetcher: Any,
        round_num: int,
    ) -> int:
        n = len(missing_papers)
        if n < 680:
            threshold = 3
        elif n < 2500:
            threshold = 4
        elif n < 6800:
            threshold = 5
        elif n < 14000:
            threshold = 7
        else:
            threshold = 10

        to_fetch = [(rid, cnt, idx) for rid, cnt, idx in missing_papers
                    if threshold <= cnt <= min(threshold + 6, 16)]
        if not to_fetch:
            return 0

        missing_ids = [rid for rid, _, _ in to_fetch]
        fetched = await fetcher.openalex.get_by_ids(missing_ids)
        id_map = {(p.get("openalex_id") or p.get("id")): p for p in fetched if p}

        updated = 0
        papers_to_save = []
        for rid, cnt, idx in to_fetch:
            if rid in id_map:
                p = id_map[rid]
                p["_co_citation_count"] = cnt
                co_cited_papers[idx] = p
                papers_to_save.append(p)
                updated += 1

        if papers_to_save:
            self.store.add_papers(papers_to_save, source="citation")
        return updated

    # -------------------------------------------------------------------------
    # In-domain citation scoring
    # -------------------------------------------------------------------------

    def calculate_paper_scores(self) -> int:
        """Compute in-domain citation scores and write them back to PaperStore.

        Score formula: ``s_dom = n_dom × (n_dom / |C(p)|)²``
        where n_dom is in-domain citation count and |C(p)| total citations.
        """
        for rec in self.store.get_all_papers():
            if rec.openalex_id:
                rec.in_domain_citation_count = 0
                rec.in_domain_citation_score = 0.0 if (rec.citation_count or 0) > 0 else None

        counts = self._compute_in_domain_citations(force_refresh=True)
        updated = 0
        for paper_id, n_dom in counts.items():
            if paper_id in self.store._openalex_index:
                corpus_id = self.store._openalex_index[paper_id]
                rec = self.store._papers.get(corpus_id)
            else:
                rec = self.store._papers.get(paper_id)
            if not rec:
                continue
            rec.in_domain_citation_count = n_dom
            total = rec.citation_count or 0
            if total > 0:
                ratio = n_dom / total
                rec.in_domain_citation_score = n_dom * (ratio ** 2)
            else:
                rec.in_domain_citation_score = None
            updated += 1
        return updated

    def find_seed_candidates(
        self,
        top_k: int = 10,
        min_in_domain: int = 2,
        min_total: int = 10,
        exclude_seeds: bool = True,
        year_range: Optional[Tuple[Optional[int], Optional[int]]] = None,
    ) -> List[Dict]:
        """Return top candidate seed papers sorted by in-domain citation score."""
        candidates = []
        for rec in self.store.get_all_papers():
            if not rec.openalex_id or rec.in_domain_citation_count is None:
                continue
            n_dom = rec.in_domain_citation_count
            if n_dom < min_in_domain:
                continue
            total = rec.citation_count or 0
            if total < min_total:
                continue
            if exclude_seeds and rec.is_seed:
                continue
            if year_range is not None:
                lo, hi = year_range
                y = rec.year
                if y is None:
                    continue
                if lo is not None and y < lo:
                    continue
                if hi is not None and y > hi:
                    continue
            ratio = n_dom / total if total > 0 else 0
            candidates.append({
                "title": rec.title,
                "openalex_id": rec.openalex_id,
                "corpus_id": rec.corpus_id,
                "in_domain_citations": n_dom,
                "total_citations": total,
                "ratio": ratio,
                "score": rec.in_domain_citation_score or 0,
                "year": rec.year,
                "is_seed": rec.is_seed,
                "tags": rec.tags,
                "abstract": rec.abstract or "",
                "cited_by_count": total,
                "citation_count": total,
                "paper_record": rec,
            })
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:top_k]

    # -------------------------------------------------------------------------
    # Stats
    # -------------------------------------------------------------------------

    def get_network_stats(self) -> Dict:
        paper_ids = self._get_paper_ids()
        counts = self._compute_in_domain_citations()
        total_refs = in_domain = 0
        for p in self.store.get_all_papers():
            for rid in p.reference_ids:
                total_refs += 1
                if str(rid) in paper_ids:
                    in_domain += 1
        return {
            "total_papers": len(paper_ids),
            "papers_with_in_domain_citations": len(counts),
            "total_in_domain_citations": sum(counts.values()),
            "total_references": total_refs,
            "in_domain_references": in_domain,
            "in_domain_ratio": in_domain / total_refs if total_refs else 0,
        }
