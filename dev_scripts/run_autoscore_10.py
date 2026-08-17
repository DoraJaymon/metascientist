"""Run autoscore on all 10 merged sessions, then dump in-domain + score summary."""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "metasci-universe" / "src"))
sys.path.insert(0, str(ROOT / "metasci-citeflow" / "src"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from metasci_citeflow.session import Session
from metasci_citeflow.scoring.autoscore import autoscore
from metasci_citeflow.scoring.reranker import BGEReranker
from metasci_citeflow.graph.cocitation import score_store_in_domain, network_stats

SESSION_ROOT = ROOT / "metasci_outputs" / "citeflow" / "merged_roleprio10_v2"
SUMMARY_PATH = ROOT / "metasci_outputs" / "query_analysis" / "claude_opus_10_roleprio_v2.json"

GOLD_FILE = Path("/home/dell/Desktop/hypothesisGen/evaluation/eval50/sci-reasoning/scireasoning_filtered38.jsonl")


def load_gold():
    gold = {}
    with open(GOLD_FILE) as f:
        for line in f:
            entry = json.loads(line)
            titles = [pw["title"].strip().lower() for pw in entry.get("prior_works", [])]
            gold[entry["openreview_id"]] = titles
    return gold


def load_summary():
    with open(SESSION_ROOT / "expansion_summary.json") as f:
        return json.load(f)


async def run_one(session_id, openreview_id, gold_titles):
    session = Session.load(session_id, root=SESSION_ROOT)
    analysis = session.analysis or {}

    try:
        reranker = BGEReranker()
    except Exception:
        reranker = None

    report = await autoscore(
        session.store,
        rerank_query=analysis.get("rerank_query", ""),
        terms=analysis.get("discriminative_terms") or {},
        reranker=reranker,
        max_papers=3000,
    )
    session.save()

    papers = session.store.get_all_papers()
    stats = network_stats(papers)

    # check gold coverage with scores
    gold_hits = []
    for p in papers:
        title = (p.title or "").strip().lower()
        if title in gold_titles:
            gold_hits.append({
                "title": title[:80],
                "in_domain_count": p.in_domain_citation_count,
                "in_domain_score": round(p.in_domain_citation_score, 4) if p.in_domain_citation_score else None,
                "embedding_sim": round(p.embedding_sim, 4) if p.embedding_sim is not None else None,
                "keyword_score": round(p.keyword_match_score, 4) if p.keyword_match_score is not None else None,
                "citation_count": p.citation_count,
            })

    return {
        "openreview_id": openreview_id,
        "session_id": session_id,
        "store_size": len(papers),
        "network": stats,
        "autoscore_coverage": report.get("coverage", {}),
        "gold_total": len(gold_titles),
        "gold_in_store": len(gold_hits),
        "gold_details": gold_hits,
    }


async def main():
    summary = load_summary()
    gold = load_gold()
    results = []

    for entry in summary:
        oid = entry["openreview_id"]
        sid = entry["session_id"]
        gold_titles = gold.get(oid, [])
        print(f"Scoring {oid} ({sid})... ", end="", flush=True)
        try:
            result = await run_one(sid, oid, gold_titles)
            results.append(result)
            print(f"done - {result['gold_in_store']}/{result['gold_total']} gold, "
                  f"in_domain_ratio={result['network']['in_domain_ratio']}")
        except Exception as e:
            print(f"ERROR: {e}")
            results.append({"openreview_id": oid, "session_id": sid, "error": str(e)})

    out = SESSION_ROOT / "autoscore_summary.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    asyncio.run(main())
