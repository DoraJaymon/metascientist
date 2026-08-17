#!/usr/bin/env python3
"""Run CiteFlow Phase 1 over Sci-Reasoning eval-50 problem seeds.

Different task from ``citeflow_batch.py``.  There the query *asks for* papers; here the
query is a **hypothesis-generation problem seed** ("I want a novel ML research idea
about ...") and the ground truth is the set of prior works the target paper actually
built on.  So this asks: starting from only a problem statement, does the citation-graph
search surface the literature the real paper stood on?

Two things force a separate script rather than a flag on ``citeflow_batch.py``:

* **Matching is by title.** Sci-Reasoning ``prior_works`` carry no OpenAlex/S2 id and
  only 44/344 have an arXiv id, so ``cf.eval.score`` (id-based) cannot be used.  We
  reuse the eval's own ``paper_matching.normalize_title`` + Jaccard so the numbers here
  are comparable with the rest of that benchmark.
* **Exact and fuzzy hits are reported separately**, never summed silently: fuzzy is a
  0.6 Jaccard threshold nobody has audited on this output yet.

Usage::

    python dev_scripts/citeflow_scireasoning.py --limit 3
    python dev_scripts/citeflow_scireasoning.py --queries 51WraMid8K,kRoWeLTpL4
    python dev_scripts/citeflow_scireasoning.py --limit 3 --year 2010-2025
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
for src in (REPO / "metasci-universe" / "src", REPO / "metasci-citeflow" / "src"):
    if src.exists():
        sys.path.insert(0, str(src))

HYPGEN = Path("/home/dell/Desktop/hypothesisGen/evaluation")
sys.path.insert(0, str(HYPGEN / "Sci-Reasoning" / "utils"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / ".env")

from paper_matching import (  # noqa: E402
    FUZZY_FLAG_THRESHOLD,
    jaccard_word_overlap,
    normalize_title,
)

from metasci_citeflow import registry  # noqa: E402

DATA = HYPGEN / "Sci-Reasoning" / "data"
SEEDS = DATA / "scireasoning_search_to_idea_problem_seeds_eval50.jsonl"
MANIFEST = DATA / "scireasoning_search_to_idea_eval50_manifest.jsonl"


def load_cases(seeds_path: Path = SEEDS) -> List[Dict[str, Any]]:
    """Join problem seeds to their paper's prior_works on openreview_id.

    ``seeds_path`` is a parameter so alternative seed wordings can be run against the
    same gold: comparing a rewrite to the archived numbers of an earlier run would
    conflate the rewrite with the pipeline's own variance (``cf.query.analyze`` is an
    LLM call at temperature 0.5), so both arms have to be run together.
    """
    manifest = {
        json.loads(line)["openreview_id"]: json.loads(line)
        for line in MANIFEST.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    cases = []
    for line in seeds_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        seed = json.loads(line)
        entry = manifest.get(seed["openreview_id"])
        if entry is None:
            continue
        cases.append({**seed, "prior_works": entry.get("prior_works") or [],
                      "target_title": entry.get("title")})
    return cases


def match_ground_truth(store_papers, prior_works) -> Dict[str, Any]:
    """Title-match each gold prior work against the store.

    Exact (normalised-equal) and fuzzy (Jaccard >= threshold) are kept apart: only the
    exact tier is a hit we would defend without a human looking at it.
    """
    indexed = []
    for paper in store_papers:
        title = getattr(paper, "title", None) or ""
        norm = normalize_title(title)
        if norm:
            indexed.append((norm, title, getattr(paper, "year", None)))

    exact_titles = {norm for norm, _, _ in indexed}
    rows = []
    for work in prior_works:
        gold = normalize_title(work.get("title"))
        if gold and gold in exact_titles:
            rows.append({"title": work.get("title"), "year": work.get("year"),
                         "role": work.get("role"), "tier": "exact", "score": 1.0,
                         "matched_title": work.get("title")})
            continue
        best_score, best_title = 0.0, None
        for norm, raw, _ in indexed:
            score = jaccard_word_overlap(gold, norm)
            if score > best_score:
                best_score, best_title = score, raw
        tier = "fuzzy" if best_score >= FUZZY_FLAG_THRESHOLD else "none"
        rows.append({"title": work.get("title"), "year": work.get("year"),
                     "role": work.get("role"), "tier": tier,
                     "score": round(best_score, 3),
                     "matched_title": best_title if tier == "fuzzy" else None})

    exact = sum(1 for r in rows if r["tier"] == "exact")
    fuzzy = sum(1 for r in rows if r["tier"] == "fuzzy")
    return {"n_gold": len(rows), "exact": exact, "fuzzy": fuzzy, "rows": rows}


async def run_case(case: Dict[str, Any], args) -> Dict[str, Any]:
    from metasci_citeflow.session import Session

    query_id = case["openreview_id"]
    started = time.monotonic()
    log = lambda msg: print(f"    {msg}", flush=True)  # noqa: E731

    print(f"\n=== {query_id}  {case['original_title'][:70]}", flush=True)
    print(f"    seed : {case['problem_seed'][:160]}", flush=True)
    print(f"    gold : {len(case['prior_works'])} prior works", flush=True)

    overrides: Dict[str, Any] = {}
    if args.year:
        low, high = (int(v) for v in args.year.split("-"))
        overrides["init_search.year"] = (low, high)

    opened = await registry.run_tool(
        "cf.session.open",
        {"profile": args.profile, "overrides": overrides, "session_dir": args.session_dir},
    )
    sid = opened.data["session_id"]
    tool_args = {"session_id": sid, "session_dir": args.session_dir}

    analysis = await registry.run_tool(
        "cf.query.analyze", {**tool_args, "query": case["problem_seed"]}
    )
    log(f"queries : {analysis.data['search_queries'][:2]}")
    log(f"terms   : {list((analysis.data.get('discriminative_terms') or {}).items())[:6]}")

    search = await registry.run_tool("cf.papers.search", tool_args)
    log(f"search  : merged={search.data['merged']} resolved={search.data['resolved']} "
        f"({search.data['openalex_coverage']:.0%} OA)")

    cocite = await registry.run_tool("cf.citations.co_cite", tool_args)
    log(f"co-cite : total={cocite.data['co_cited_total']} strong={cocite.data['strong_bucket']} "
        f"weak={cocite.data['weak_bucket']} hydrated={cocite.data['added']}")

    refs = await registry.run_tool("cf.citations.expand_refs_guided", tool_args)
    log(f"refs    : sources={len(refs.data['source_ids'])} fetched={refs.data['refs_fetched']} "
        f"added={refs.data['added']}")

    seeds = await registry.run_tool("cf.seeds.select_refs", tool_args)
    log(f"seeds   : {len(seeds.data['seed_ids'])} selected "
        f"(strategies={seeds.data['strategies_used']})")

    stats = await registry.run_tool("cf.store.stats", tool_args)

    session = Session.open(sid, root=REPO / args.session_dir)
    found = match_ground_truth(session.store.get_all_papers(), case["prior_works"])

    row = {
        "openreview_id": query_id,
        "session_id": sid,
        "stratum": case.get("stratum"),
        "n_gold": found["n_gold"],
        "exact": found["exact"],
        "fuzzy": found["fuzzy"],
        "coverage_exact": round(found["exact"] / found["n_gold"], 4) if found["n_gold"] else 0.0,
        "store": stats.data["total_papers"],
        "oa_cov": stats.data["openalex_coverage"],
        "strong": cocite.data["strong_bucket"],
        "seeds": len(seeds.data["seed_ids"]),
        "gold_rows": found["rows"],
        "seconds": round(time.monotonic() - started, 1),
    }
    log(f"EVAL    : exact {found['exact']}/{found['n_gold']}  (+{found['fuzzy']} fuzzy)  "
        f"store={row['store']}  [{row['seconds']}s]")
    for r in found["rows"]:
        mark = {"exact": "HIT  ", "fuzzy": "FUZZY", "none": "MISS "}[r["tier"]]
        log(f"          {mark} [{r['year']}|{r['role'][:12]:<12}] {r['title'][:64]}")
    return row


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", default=None, help="comma-separated openreview_ids")
    parser.add_argument("--limit", type=int, default=3, help="first N cases if --queries unset")
    parser.add_argument("--seeds", default=str(SEEDS), help="problem-seed jsonl to run")
    parser.add_argument("--profile", default="acadeepr-run1")
    parser.add_argument("--session-dir", default="metasci_outputs/citeflow/scireasoning")
    parser.add_argument("--year", default=None, help="override init_search year, e.g. 2010-2025")
    parser.add_argument("--out", default="metasci_outputs/citeflow/scireasoning_report.json")
    args = parser.parse_args()

    cases = load_cases(Path(args.seeds))
    if args.queries:
        wanted = [q.strip() for q in args.queries.split(",") if q.strip()]
        cases = [c for c in cases if c["openreview_id"] in wanted]
    else:
        cases = cases[: args.limit]

    rows = []
    for case in cases:
        try:
            rows.append(await run_case(case, args))
        except Exception as exc:  # one bad case should not kill the batch
            print(f"    FAILED: {type(exc).__name__}: {exc}", flush=True)
            rows.append({"openreview_id": case["openreview_id"],
                         "error": f"{type(exc).__name__}: {exc}"})

    ok = [r for r in rows if "error" not in r]
    print("\n" + "=" * 92)
    print("SCI-REASONING eval-50 — PHASE 1 GROUND-TRUTH STORE COVERAGE (title match)")
    print("=" * 92)
    print(f"{'openreview_id':<16}{'gold':>6}{'exact':>7}{'fuzzy':>7}{'cov':>7}"
          f"{'store':>8}{'strong':>8}{'seeds':>7}{'sec':>7}")
    print("-" * 92)
    for r in ok:
        print(f"{r['openreview_id']:<16}{r['n_gold']:>6}{r['exact']:>7}{r['fuzzy']:>7}"
              f"{r['coverage_exact']:>7.0%}{r['store']:>8}{r['strong']:>8}"
              f"{r['seeds']:>7}{r['seconds']:>7.0f}")
    for r in rows:
        if "error" in r:
            print(f"{r['openreview_id']:<16}  ERROR: {r['error'][:60]}")
    if ok:
        gold = sum(r["n_gold"] for r in ok)
        exact = sum(r["exact"] for r in ok)
        fuzzy = sum(r["fuzzy"] for r in ok)
        print("-" * 92)
        print(f"{'POOLED':<16}{gold:>6}{exact:>7}{fuzzy:>7}{exact / gold:>7.0%}")
        print("\nCoverage is the ceiling on recall: it only asks whether the paper entered\n"
              "the store at all, before any ranking or filtering.")

    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nreport -> {out}")


if __name__ == "__main__":
    asyncio.run(main())
