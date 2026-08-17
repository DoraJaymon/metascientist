#!/usr/bin/env python3
"""recall@K per case, per signal — no bucketing, no union, just: sort the whole store by
one signal at a time, see how many gold papers land in the top 50/100/200.

Each case's store is ranked independently. Signals tested individually (not combined) so we
can see which ones are actually predictive before designing any bucket/composite scheme.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for src in (REPO / "metasci-citeflow" / "src", REPO / "metasci-universe" / "src"):
    sys.path.insert(0, str(src))
sys.path.insert(0, str(Path("/home/dell/Desktop/hypothesisGen/evaluation/Sci-Reasoning/utils")))

from metasci_citeflow.session import Session  # noqa: E402
from metasci_citeflow.graph import cocitation as cc  # noqa: E402
from paper_matching import normalize_title, jaccard_word_overlap, FUZZY_FLAG_THRESHOLD  # noqa: E402

SUMMARY = REPO / "metasci_outputs/citeflow/merged_roleprio10_v2/expansion_summary.json"
SESSION_ROOT = REPO / "metasci_outputs/citeflow/merged_roleprio10_v2"

# VpWki1v2P8 and 7BLXhmWvwF have been rerun blind under the new skill (Phase1+Phase2) with
# much better recall; swap those two in so the ranking test reflects the improved store
# instead of the old-pipeline store that never found the gold papers in the first place.
BLIND_ROOT = REPO / "metasci_outputs/citeflow/skill_test_v1_blind"
SESSION_OVERRIDES = {
    "VpWki1v2P8": ("cf_2107d4484c", BLIND_ROOT),
    "7BLXhmWvwF": ("cf_1d6c7a001c", BLIND_ROOT),
}
MANIFEST = Path(
    "/home/dell/Desktop/hypothesisGen/evaluation/Sci-Reasoning/data/"
    "scireasoning_search_to_idea_eval50_manifest.jsonl"
)
KS = (50, 100, 200)

SIGNALS = {
    "in_domain_score": lambda p: p.in_domain_citation_score or 0.0,
    "citation_count":  lambda p: p.citation_count or 0,
    "embedding_sim":   lambda p: p.embedding_sim or 0.0,
    "keyword_match":   lambda p: p.keyword_match_score or 0.0,
}


def load_gold():
    gold = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        gold[row["openreview_id"]] = row.get("prior_works") or []
    return gold


def gold_hits_at_k(ranked_papers, gold_works, k):
    top = ranked_papers[:k]
    norm_titles = {normalize_title(p.title or "") for p in top if p.title}
    exact = 0
    for w in gold_works:
        gn = normalize_title(w.get("title") or "")
        if gn and gn in norm_titles:
            exact += 1
    return exact


def main():
    gold_by_case = load_gold()
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))

    per_signal_totals = {name: {k: 0 for k in KS} for name in SIGNALS}
    total_gold = 0

    header = f"{'case':<14}{'gold':>5}" + "".join(f"{name+'@'+str(k):>18}" for name in SIGNALS for k in KS)
    print(header)
    print("-" * len(header))

    for row in summary:
        oid = row["openreview_id"]
        if oid in SESSION_OVERRIDES:
            sid, root = SESSION_OVERRIDES[oid]
            session = Session.open(sid, root=root)
        else:
            session = Session.open(row["session_id"], root=SESSION_ROOT)
        papers = session.store.get_all_papers()
        cc.score_store_in_domain(papers)
        gold_works = gold_by_case.get(oid, [])
        n_gold = len(gold_works)
        total_gold += n_gold

        line = f"{oid:<14}{n_gold:>5}"
        for name, keyfn in SIGNALS.items():
            ranked = sorted(papers, key=keyfn, reverse=True)
            for k in KS:
                hits = gold_hits_at_k(ranked, gold_works, k)
                per_signal_totals[name][k] += hits
                line += f"{f'{hits}/{n_gold}':>18}"
        print(line)

    print("-" * len(header))
    line = f"{'POOLED':<14}{total_gold:>5}"
    for name in SIGNALS:
        for k in KS:
            hits = per_signal_totals[name][k]
            line += f"{f'{hits}/{total_gold}={hits/total_gold:.0%}':>18}"
    print(line)


if __name__ == "__main__":
    main()
