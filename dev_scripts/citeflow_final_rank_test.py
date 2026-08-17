#!/usr/bin/env python3
"""Test the terminal-ranking bucket design against the 10-case old-pipeline stores.

v2: no value-threshold pre-filters (count-based top-K only, per user feedback — a fixed
citation_count/relevance cutoff silently excludes good candidates before ranking ever sees
them). Two buckets, not three: "structural" (background + hub papers collapse into one
ranking once the citation_count>=500 gate is gone, since in_domain_citation_score already
penalizes globally-famous-but-topically-diffuse papers) and "recent" (textual/semantic
relevance, for papers too new to have accumulated citations yet). embedding_sim is computed
fresh for whatever's missing it *within the recent-bucket candidate pool only* — not the
whole store — since v1 silently treated "never scored" as "scored 0" (a real bug: only
30-45% of these old stores had embedding_sim/keyword_match_score at all).

Still no LLM step — this only tests the candidate-generation stage.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for src in (REPO / "metasci-citeflow" / "src", REPO / "metasci-universe" / "src"):
    sys.path.insert(0, str(src))

sys.path.insert(0, str(Path("/home/dell/Desktop/hypothesisGen/evaluation/Sci-Reasoning/utils")))

from metasci_citeflow.session import Session  # noqa: E402
from metasci_citeflow.graph import cocitation as cc  # noqa: E402
from metasci_citeflow.deps import CiteFlowDeps  # noqa: E402
from metasci_citeflow.scoring.reranker import score_relevance  # noqa: E402
from paper_matching import normalize_title, jaccard_word_overlap, FUZZY_FLAG_THRESHOLD  # noqa: E402

SUMMARY = REPO / "metasci_outputs/citeflow/merged_roleprio10_v2/expansion_summary.json"
SESSION_ROOT = REPO / "metasci_outputs/citeflow/merged_roleprio10_v2"
MANIFEST = Path(
    "/home/dell/Desktop/hypothesisGen/evaluation/Sci-Reasoning/data/"
    "scireasoning_search_to_idea_eval50_manifest.jsonl"
)

TOP_K = 25
RECENT_WINDOW = 5


def load_gold():
    gold = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        gold[row["openreview_id"]] = row.get("prior_works") or []
    return gold


def rel(p):
    return max(p.embedding_sim or 0.0, p.keyword_match_score or 0.0)


CLASSICS_PERCENTILE = 0.20  # top 20% by citation_count, relative to this store — not a fixed count


async def build_buckets(session, papers, deps):
    cc.score_store_in_domain(papers)  # free, local — fills in_domain_citation_score

    # in_domain_citation_score's squared-share formula structurally buries huge-citation
    # classics (Adam: n_domain=50 but total_citations=84805 -> score ~0) behind small-total-
    # citation niche papers with an inflated in-domain share. Split by citation_count rank
    # (relative to this store, not a fixed magic number) so classics only compete against
    # other classics for their top-K, instead of losing to niche papers on a shared axis.
    scored = [p for p in papers if p.in_domain_citation_score is not None]
    by_cc = sorted(scored, key=lambda p: p.citation_count or 0, reverse=True)
    split = max(1, int(len(by_cc) * CLASSICS_PERCENTILE))
    classics_pool, niche_pool = by_cc[:split], by_cc[split:]

    classics_pool.sort(key=lambda p: p.in_domain_citation_score or 0.0, reverse=True)
    niche_pool.sort(key=lambda p: p.in_domain_citation_score or 0.0, reverse=True)
    classics = classics_pool[:TOP_K]
    niche = niche_pool[:TOP_K]

    # Bucket 2: recent — year window, no relevance pre-filter. Score whatever's missing
    # embedding_sim within this window only (bounded cost), then rank by rel().
    years = [p.year for p in papers if p.year]
    recent = []
    if years:
        max_year = max(years)
        recent = [p for p in papers if p.year and p.year >= max_year - RECENT_WINDOW]
        query_text = (session.analysis or {}).get("rerank_query") or session.query or ""
        if query_text and deps is not None:
            try:
                reranker = deps.require_reranker()
                scores, _report = await score_relevance(recent, query_text, reranker)
                for pid, score in scores.items():
                    for p in recent:
                        if (p.openalex_id or p.corpus_id) == pid:
                            p.embedding_sim = score
                            break
            except Exception as exc:  # reranker down — fall back to whatever's already scored
                print(f"    [reranker unavailable: {exc}]")
        recent.sort(key=rel, reverse=True)
        recent = recent[:TOP_K]

    return {"classics": classics, "niche": niche, "recent": recent}


def match_gold(union_papers, gold_works):
    indexed = [(normalize_title(p.title or ""), p.title, i) for i, p in enumerate(union_papers)]
    exact_map = {n: (t, i) for n, t, i in indexed if n}
    rows = []
    for work in gold_works:
        gold_title = work.get("title") or ""
        gn = normalize_title(gold_title)
        if gn in exact_map:
            matched_title, rank = exact_map[gn]
            rows.append({"title": gold_title, "tier": "exact", "rank_in_union": rank})
            continue
        best_score, best_title, best_rank = 0.0, None, None
        for n, t, i in indexed:
            s = jaccard_word_overlap(gn, n)
            if s > best_score:
                best_score, best_title, best_rank = s, t, i
        tier = "fuzzy" if best_score >= FUZZY_FLAG_THRESHOLD else "miss"
        rows.append({"title": gold_title, "tier": tier, "rank_in_union": best_rank if tier == "fuzzy" else None})
    return rows


async def main():
    gold_by_case = load_gold()
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    deps = CiteFlowDeps.from_env()

    all_rows = []
    for row in summary:
        oid = row["openreview_id"]
        session = Session.open(row["session_id"], root=SESSION_ROOT)
        papers = session.store.get_all_papers()
        gold_works = gold_by_case.get(oid, [])

        buckets = await build_buckets(session, papers, deps)
        seen = {}
        for name, plist in buckets.items():
            for p in plist:
                key = p.openalex_id or p.corpus_id
                if key not in seen:
                    seen[key] = p
        union = list(seen.values())

        matches = match_gold(union, gold_works)
        exact = sum(1 for m in matches if m["tier"] == "exact")
        fuzzy = sum(1 for m in matches if m["tier"] == "fuzzy")
        miss = sum(1 for m in matches if m["tier"] == "miss")

        print(f"\n=== {oid} ===")
        print(f"  store={len(papers)}  classics={len(buckets['classics'])} "
              f"niche={len(buckets['niche'])} recent={len(buckets['recent'])} union={len(union)} "
              f"(reduction {len(papers)/max(len(union),1):.1f}x)")
        print(f"  gold captured: {exact} exact + {fuzzy} fuzzy / {len(gold_works)}  ({miss} missed)")
        for m in matches:
            tag = {"exact": "HIT ", "fuzzy": "FUZZ", "miss": "MISS"}[m["tier"]]
            rk = f"rank {m['rank_in_union']}" if m["rank_in_union"] is not None else "-"
            print(f"    {tag} [{rk:<8}] {m['title'][:70]}")

        all_rows.append({
            "openreview_id": oid, "store": len(papers), "union": len(union),
            "gold": len(gold_works), "exact": exact, "fuzzy": fuzzy, "miss": miss,
        })

    print("\n" + "=" * 80)
    tot_gold = sum(r["gold"] for r in all_rows)
    tot_exact = sum(r["exact"] for r in all_rows)
    tot_fuzzy = sum(r["fuzzy"] for r in all_rows)
    tot_store = sum(r["store"] for r in all_rows)
    tot_union = sum(r["union"] for r in all_rows)
    print(f"POOLED: gold captured in union = {tot_exact} exact + {tot_fuzzy} fuzzy / {tot_gold} "
          f"({(tot_exact+tot_fuzzy)/tot_gold:.0%})")
    print(f"POOLED: store->union reduction = {tot_store} -> {tot_union} ({tot_store/tot_union:.1f}x)")

    out = REPO / "metasci_outputs/citeflow/final_rank_test_report_v2.json"
    out.write_text(json.dumps(all_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nreport -> {out}")


if __name__ == "__main__":
    asyncio.run(main())
