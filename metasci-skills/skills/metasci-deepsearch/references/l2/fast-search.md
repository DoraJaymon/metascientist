# L2 Strategy: Fast Search

Keyword search only — no citation expansion. Best for: quick paper surveys,
well-defined topics where S2 coverage is good, time-sensitive requests,
or when the user just wants a starting point.

**Expected output size:** 50–150 papers.
**Expected time:** 1–2 minutes.

---

## Execution

### Phase 1 — Iterative Search
→ `references/l1/iterative-search.md`

Parameters:
- max_rounds: 2 (one focused round + one expand round is usually enough)
- search_limit: 80 (higher than citeflow since there's no citation phase)
- Stop condition: successful_rounds >= 1 OR total_rounds >= 2

### Phase 2 — Rank and Filter
→ `references/l1/rank-and-filter.md`

Parameters:
- Use the "standard" weight profile (no in-domain scores available)
- If papers.judge ran: use the "LLM scores available" profile
- top_k: 50 (fast-search is for focused results)

---

## When to upgrade to citeflow

Suggest upgrading to the full citeflow strategy if:
- The user mentions "comprehensive", "all relevant papers", or "literature review"
- Phase 1 returns many relevant papers (successful_count >= 5 in round 1) —
  there's likely a rich citation network worth exploring
- The topic is foundational (pre-2020) where citation graphs are dense
