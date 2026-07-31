#!/usr/bin/env python3
"""Run the CiteFlow Phase 1 pipeline over benchmark queries and report coverage.

Phase 1 is search -> co-citation -> guided references expansion -> seed selection.
There is no final ranking yet, so the metric reported is **ground-truth store coverage**:
did the pipeline find the papers at all?  That is the ceiling on recall, and it is
ranking-independent, which makes it the right thing to track while the forward-expansion
loop is still being built.

Usage::

    python dev_scripts/citeflow_batch.py --queries semantic_144,semantic_187,semantic_5,semantic_12
    python dev_scripts/citeflow_batch.py --queries semantic_5 --live-analysis

By default the query analysis is pinned from the original AcaDeepR config so runs are
comparable; ``--live-analysis`` exercises cf.query.analyze instead.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for src in (REPO / "metasci-universe" / "src", REPO / "metasci-citeflow" / "src"):
    if src.exists():
        sys.path.insert(0, str(src))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / ".env")

from metasci_citeflow import registry  # noqa: E402
from metasci_citeflow.eval import Benchmark  # noqa: E402

ACADEEPR = Path("/home/dell/Desktop/AcaDeepR")
CONFIG_DIR = ACADEEPR / "inputConfig" / "run_my_1"
DEFAULT_QUERIES = "semantic_144,semantic_187,semantic_5,semantic_12"


async def run_query(query_id: str, args, benchmark) -> dict:
    bench_query = benchmark.get(query_id)
    config = CONFIG_DIR / f"{query_id}.yaml"
    started = time.monotonic()
    log = lambda msg: print(f"    {msg}", flush=True)  # noqa: E731

    print(f"\n=== {query_id}  (GT={bench_query.size})", flush=True)
    print(f"    {bench_query.query[:100]}", flush=True)

    opened = await registry.run_tool(
        "cf.session.open",
        {"profile": args.profile, "session_dir": args.session_dir},
    )
    sid = opened.data["session_id"]
    tool_args = {"session_id": sid, "session_dir": args.session_dir}

    analyze_payload = dict(tool_args)
    if not args.live_analysis:
        if not config.exists():
            return {"query_id": query_id, "error": f"no config at {config}"}
        analyze_payload["from_yaml"] = str(config)
    else:
        analyze_payload["query"] = bench_query.query

    analysis = await registry.run_tool("cf.query.analyze", analyze_payload)
    log(f"queries : {analysis.data['search_queries'][:2]}")

    search = await registry.run_tool("cf.papers.search", tool_args)
    log(
        f"search  : merged={search.data['merged']} "
        f"resolved={search.data['resolved']} "
        f"({search.data['openalex_coverage']:.0%} OA) via {search.data['provider']}"
    )

    cocite = await registry.run_tool("cf.citations.co_cite", tool_args)
    log(
        f"co-cite : total={cocite.data['co_cited_total']} "
        f"strong={cocite.data['strong_bucket']} weak={cocite.data['weak_bucket']} "
        f"hydrated={cocite.data['added']}"
    )

    refs = await registry.run_tool("cf.citations.expand_refs_guided", tool_args)
    log(
        f"refs    : sources={len(refs.data['source_ids'])} "
        f"fetched={refs.data['refs_fetched']} added={refs.data['added']}"
    )

    seeds = await registry.run_tool("cf.seeds.select_refs", tool_args)
    log(
        f"seeds   : {len(seeds.data['seed_ids'])} selected "
        f"({seeds.data['total_seed_citations']} citations, "
        f"strategies={seeds.data['strategies_used']}, "
        f"budget_met={seeds.data['budget']['met']})"
    )

    stats = await registry.run_tool("cf.store.stats", tool_args)
    score = await registry.run_tool(
        "cf.eval.score",
        {**tool_args, "query_id": query_id, "benchmark_path": args.benchmark},
    )

    row = {
        "query_id": query_id,
        "session_id": sid,
        "gt": bench_query.size,
        "found": score.data["num_ground_truth_in_store"],
        "coverage": score.data["ground_truth_store_coverage"],
        "store": stats.data["total_papers"],
        "oa_cov": stats.data["openalex_coverage"],
        "abs_cov": stats.data["abstract_coverage"],
        "strong": cocite.data["strong_bucket"],
        "seeds": len(seeds.data["seed_ids"]),
        "missing": score.data["missing_titles"],
        "seconds": round(time.monotonic() - started, 1),
    }
    log(
        f"EVAL    : GT in store {row['found']}/{row['gt']} "
        f"({row['coverage']:.0%})  store={row['store']} papers  [{row['seconds']}s]"
    )
    for title in row["missing"]:
        log(f"          MISSING: {title[:76]}")
    return row


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", default=DEFAULT_QUERIES)
    parser.add_argument("--profile", default="acadeepr-run1")
    parser.add_argument("--session-dir", default="metasci_outputs/citeflow/sessions")
    parser.add_argument("--benchmark", default=None)
    parser.add_argument("--live-analysis", action="store_true")
    parser.add_argument("--out", default="metasci_outputs/citeflow/batch_report.json")
    args = parser.parse_args()

    benchmark = Benchmark.load(args.benchmark)
    query_ids = [q.strip() for q in args.queries.split(",") if q.strip()]

    rows = []
    for query_id in query_ids:
        try:
            rows.append(await run_query(query_id, args, benchmark))
        except Exception as exc:  # keep going; one bad query should not kill the batch
            print(f"    FAILED: {type(exc).__name__}: {exc}", flush=True)
            rows.append({"query_id": query_id, "error": f"{type(exc).__name__}: {exc}"})

    print("\n" + "=" * 96)
    print("PHASE 1 GROUND-TRUTH STORE COVERAGE")
    print("=" * 96)
    header = f"{'query':<16}{'GT':>4}{'found':>7}{'cov':>7}{'store':>8}{'OA':>6}{'abs':>6}{'strong':>8}{'seeds':>7}{'sec':>7}"
    print(header)
    print("-" * 96)
    ok = [r for r in rows if "error" not in r]
    for r in ok:
        print(
            f"{r['query_id']:<16}{r['gt']:>4}{r['found']:>7}{r['coverage']:>7.0%}"
            f"{r['store']:>8}{r['oa_cov']:>6.0%}{r['abs_cov']:>6.0%}"
            f"{r['strong']:>8}{r['seeds']:>7}{r['seconds']:>7.0f}"
        )
    for r in rows:
        if "error" in r:
            print(f"{r['query_id']:<16}  ERROR: {r['error'][:60]}")
    if ok:
        total_gt = sum(r["gt"] for r in ok)
        total_found = sum(r["found"] for r in ok)
        print("-" * 96)
        print(f"{'POOLED':<16}{total_gt:>4}{total_found:>7}{total_found / total_gt:>7.0%}")
        print(
            "\nNote: ground-truth sets are tiny (median 1), so per-query rows matter more\n"
            "than the pooled figure. Coverage is the ceiling on recall - the forward\n"
            "expansion loop is not built yet, so this is a Phase 1 baseline only."
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nreport -> {out}")


if __name__ == "__main__":
    asyncio.run(main())
