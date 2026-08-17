"""Agent-style forward expansion: per-direction seed selection.

For each session:
1. Use search_queries as direction proxies (each query = one research angle)
2. For each direction, find store papers matching that direction with highest idc
3. Select 1-2 seeds per direction → multi-direction coverage
4. Run forward expansion
"""

import asyncio
import json
import re
import sys
from pathlib import Path
from difflib import SequenceMatcher

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "metasci-universe" / "src"))
sys.path.insert(0, str(ROOT / "metasci-citeflow" / "src"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from metasci_citeflow.session import Session
from metasci_citeflow.providers.openalex_graph import OpenAlexGraph

SESSION_ROOT = ROOT / "metasci_outputs" / "citeflow" / "merged_roleprio10_v2"
GOLD_FILE = Path("/home/dell/Desktop/hypothesisGen/evaluation/eval50/sci-reasoning/scireasoning_filtered38.jsonl")

ALREADY_DONE = {"51WraMid8K"}


def load_gold():
    gold = {}
    with open(GOLD_FILE) as f:
        for line in f:
            entry = json.loads(line)
            titles = [pw["title"].strip().lower() for pw in entry.get("prior_works", [])]
            gold[entry["openreview_id"]] = titles
    return gold


def normalize(t):
    return " ".join(t.lower().split())


def count_gold_hits(papers, gold_titles):
    store_titles = {normalize(p.title or ""): p for p in papers}
    exact = 0
    fuzzy = 0
    for gt in gold_titles:
        gt_norm = normalize(gt)
        if gt_norm in store_titles:
            exact += 1
        else:
            best = max(
                (SequenceMatcher(None, gt_norm, st).ratio() for st in store_titles),
                default=0,
            )
            if best >= 0.8:
                fuzzy += 1
    return exact, fuzzy


def direction_keywords(query):
    """Extract keywords from a search query for matching."""
    words = re.findall(r'[a-zA-Z\-]+', query.lower())
    stopwords = {'a', 'an', 'the', 'of', 'in', 'for', 'and', 'or', 'with', 'on', 'to', 'by'}
    return [w for w in words if w not in stopwords and len(w) > 2]


def paper_matches_direction(paper, dir_keywords):
    """Check if paper title/abstract matches a research direction."""
    title = (paper.title or "").lower()
    abstract = (paper.abstract or "").lower()[:300]
    text = title + " " + abstract
    matches = sum(1 for kw in dir_keywords if kw in text)
    return matches


def select_seeds_by_direction(session, max_per_direction=2, min_idc=3):
    """Select seeds by finding top hubs per research direction."""
    analysis = session.analysis or {}
    search_queries = analysis.get("search_queries", [])
    disc_terms = list((analysis.get("discriminative_terms") or {}).keys())

    papers = session.store.get_all_papers()
    candidates = [p for p in papers if (p.in_domain_citation_count or 0) >= min_idc and p.openalex_id]

    selected = {}  # oa_id → info
    direction_report = []

    for qi, query in enumerate(search_queries):
        dir_kws = direction_keywords(query)

        # Score each candidate for this direction
        scored = []
        for p in candidates:
            match_count = paper_matches_direction(p, dir_kws)
            if match_count == 0:
                continue
            cc = p.citation_count or 0
            # Skip super-generic classics for forward expansion
            if cc > 20000:
                continue
            scored.append((p, match_count, p.in_domain_citation_count or 0))

        # Sort by match_count desc, then idc desc
        scored.sort(key=lambda x: (x[1], x[2]), reverse=True)

        picks = []
        for p, mc, idc in scored[:max_per_direction * 3]:
            oa = p.openalex_id
            if oa in selected:
                continue
            info = {
                "id": oa,
                "title": (p.title or "")[:70],
                "idc": idc,
                "cc": p.citation_count or 0,
                "direction": query,
                "match_count": mc,
            }
            selected[oa] = info
            picks.append(info)
            if len(picks) >= max_per_direction:
                break

        direction_report.append({
            "query": query,
            "keywords": dir_kws,
            "candidates_matched": len(scored),
            "picked": len(picks),
            "picks": [f"idc={s['idc']} cc={s['cc']} {s['title'][:50]}" for s in picks],
        })

    # If some directions had no picks, try to fill from overall top idc with disc_term relevance
    if len(selected) < 3:
        candidates.sort(key=lambda p: p.in_domain_citation_count or 0, reverse=True)
        for p in candidates[:30]:
            if p.openalex_id in selected:
                continue
            title = (p.title or "").lower()
            if any(t.lower() in title for t in disc_terms):
                cc = p.citation_count or 0
                if cc > 20000:
                    continue
                selected[p.openalex_id] = {
                    "id": p.openalex_id,
                    "title": (p.title or "")[:70],
                    "idc": p.in_domain_citation_count or 0,
                    "cc": cc,
                    "direction": "fallback (disc_terms)",
                    "match_count": 0,
                }
                if len(selected) >= 5:
                    break

    return list(selected.values()), direction_report


async def run_one(session_id, openreview_id, gold_titles, graph):
    session = Session.load(session_id, root=SESSION_ROOT)
    papers_before = session.store.get_all_papers()
    store_before = len(papers_before)
    exact_before, fuzzy_before = count_gold_hits(papers_before, gold_titles)

    seeds, dir_report = select_seeds_by_direction(session)
    seed_ids = [s["id"] for s in seeds]

    print(f"\n{'='*70}")
    print(f"  {openreview_id} (session: {session_id})")
    print(f"  Store: {store_before}, Gold before: {exact_before}e+{fuzzy_before}f / {len(gold_titles)}")
    print(f"  Direction analysis:")
    for dr in dir_report:
        picks_str = "; ".join(dr["picks"]) if dr["picks"] else "(no match)"
        print(f"    [{dr['query']}] {dr['candidates_matched']} candidates → {picks_str}")
    print(f"  Total seeds: {len(seeds)}")

    if not seed_ids:
        print(f"  No valid seeds!")
        return {"openreview_id": openreview_id, "store_before": store_before,
                "exact_before": exact_before, "fuzzy_before": fuzzy_before,
                "exact_after": exact_before, "fuzzy_after": fuzzy_before,
                "gold": len(gold_titles), "seeds": 0, "added": 0}

    try:
        citations = await graph.get_citations(
            seed_ids, year_range=(2013, 2025), max_per_work=200,
        )
        all_papers = [p for papers in citations.values() for p in papers]
        unique = {}
        for p in all_papers:
            oa = p.get("openalex_id", "")
            if oa and oa not in unique:
                unique[oa] = p

        new_records = session.store.add_papers(
            list(unique.values()), source="citation", parent_ids=seed_ids, api_name="openalex"
        )
        session.save()

        papers_after = session.store.get_all_papers()
        store_after = len(papers_after)
        exact_after, fuzzy_after = count_gold_hits(papers_after, gold_titles)

        print(f"  Fetched: {len(all_papers)} → {len(unique)} unique → {len(new_records)} new")
        print(f"  Store after: {store_after}")
        print(f"  Gold: {exact_before}e+{fuzzy_before}f → {exact_after}e+{fuzzy_after}f")
        if exact_after > exact_before or fuzzy_after > fuzzy_before:
            print(f"  >>> NEW GOLD HITS! <<<")

        return {
            "openreview_id": openreview_id,
            "store_before": store_before, "store_after": store_after,
            "seeds": len(seed_ids), "added": len(new_records),
            "exact_before": exact_before, "fuzzy_before": fuzzy_before,
            "exact_after": exact_after, "fuzzy_after": fuzzy_after,
            "gold": len(gold_titles),
            "seed_details": seeds, "direction_report": dir_report,
        }
    except Exception as e:
        print(f"  ERROR: {e}")
        return {"openreview_id": openreview_id, "error": str(e),
                "store_before": store_before, "seeds": len(seed_ids),
                "exact_before": exact_before, "fuzzy_before": fuzzy_before,
                "gold": len(gold_titles)}


async def main():
    summary_data = json.load(open(SESSION_ROOT / "expansion_summary.json"))
    gold = load_gold()
    graph = OpenAlexGraph()
    results = []

    for entry in summary_data:
        oid = entry["openreview_id"]
        if oid in ALREADY_DONE:
            continue
        sid = entry["session_id"]
        gold_titles = gold.get(oid, [])
        result = await run_one(sid, oid, gold_titles, graph)
        results.append(result)

    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    total_eb = sum(r.get("exact_before", 0) for r in results)
    total_fb = sum(r.get("fuzzy_before", 0) for r in results)
    total_ea = sum(r.get("exact_after", r.get("exact_before", 0)) for r in results)
    total_fa = sum(r.get("fuzzy_after", r.get("fuzzy_before", 0)) for r in results)
    total_gold = sum(r.get("gold", 0) for r in results)

    print(f"9 sessions (excl. 51WraMid8K):")
    print(f"  Before: {total_eb}e + {total_fb}f / {total_gold}")
    print(f"  After:  {total_ea}e + {total_fa}f / {total_gold}")
    print()
    for r in results:
        oid = r["openreview_id"]
        eb, fb = r.get("exact_before", 0), r.get("fuzzy_before", 0)
        ea = r.get("exact_after", eb)
        fa = r.get("fuzzy_after", fb)
        g = r.get("gold", 0)
        added = r.get("added", 0)
        delta = (ea + fa) - (eb + fb)
        marker = f" +{delta}" if delta > 0 else ""
        print(f"  {oid}: {eb}e+{fb}f → {ea}e+{fa}f / {g}  (+{added} papers){marker}")

    out = SESSION_ROOT / "forward_expansion_summary.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    asyncio.run(main())
