# L2 Strategy: CiteFlow

Full CiteFlow algorithm — iterative keyword search followed by citation network
expansion. Best for: comprehensive literature reviews, topics where important
papers may not be surfaced by keyword search alone, finding foundational works.

**Expected output size:** 100–400 papers before ranking, top 100 returned.
**Expected time:** 3–8 minutes depending on topic size.

---

## Execution

Read and follow each L1 reference in order:

### Phase 1 — Iterative Search
→ `references/l1/iterative-search.md`

Parameters:
- max_rounds: 3 (increase to 5 for broad or ambiguous topics)
- search_limit: 50 per round
- Stop condition: successful_rounds >= 2 OR total_rounds >= max_rounds

### Phase 2 — Citation Expansion
→ `references/l1/citation-expand.md`

Parameters:
- Seed selection: use Option A (score-based) by default
  Use Option B (LLM judge on candidates) only if Phase 1 found fewer than
  20 relevant papers — it means keyword search underperformed and seed
  quality matters more.
- Run both fetch_refs AND fetch_forward
- Run co_cite with min_count=2

### Phase 3 — Rank and Filter
→ `references/l1/rank-and-filter.md`

Parameters:
- Use the "in-domain citation expansion" weight profile since Phase 2 ran
- top_k: 100 (default)

---

## Checkpoints

After Phase 1:
- Store should have 50–150 papers.
- If < 30: keyword search struggled — tell the user and consider clarifying
  the query before continuing to Phase 2.
- If 0 evaluated (papers.judge wasn't called or all failed): warn, but
  proceed — Phase 2 can still work from importance-ranked seeds.

After Phase 2:
- Store should have grown by at least 50 papers.
- If growth < 20: seeds had few citations (niche topic). This is fine —
  just note it in the output summary.

---

## Output summary template

```
DeepSearch complete (CiteFlow strategy)
  Query: <query>
  Search: <N> papers across <R> rounds
  Expansion: <N> refs + <N> co-cited + <N> forward citations
  Total collected: <N> | Returned: <top_k>

Top papers:
  1. <title> (<year>, <citations> citations)
  2. ...
```
