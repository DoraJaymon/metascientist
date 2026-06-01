# L2 Strategy: Citation-First

Start from user-provided seed papers and expand through the citation network.
Skip keyword search entirely. Best for: "I already know these 3 papers, find
related work", finding papers that cite a specific influential work, or
exploring a paper's intellectual neighbourhood.

**Expected output size:** 100–300 papers.
**Expected time:** 2–5 minutes.

---

## Execution

### Phase 0 — Load seeds

```python
import asyncio
import metasci_universe as ms

async def main():
    r = await ms.run_tool("ds.session.new", {})
    session_id = r.data["session_id"]

    # Add user-provided seed papers to the store
    # Seeds can be provided as OpenAlex IDs, DOIs, or title strings.
    # If only titles are known, search for them first:
    for seed_query in seed_titles:
        await ms.run_tool("ds.papers.search", {
            "session_id": session_id,
            "keywords": seed_query,
            "limit": 5,
        })
    # Then mark the matched papers as seeds
    candidates = await ms.run_tool("ds.store.seeds.candidates", {
        "session_id": session_id, "n": len(seed_titles)
    })
    seed_ids = [c["openalex_id"] for c in candidates.data["candidates"]]
    await ms.run_tool("ds.store.seeds.mark", {
        "session_id": session_id,
        "paper_ids": seed_ids,
        "tag": "user_seed",
    })
```

If the user provides OpenAlex IDs directly, skip the search step and call
`ds.store.seeds.mark` with those IDs immediately after `ds.session.new`.

### Phase 1 — Citation Expansion
→ `references/l1/citation-expand.md`

Note: seeds are already marked (Phase 0). In citation-expand, skip the
seed selection step (steps 2a and 2b) and go directly to step 3 (fetch_refs).

Parameters:
- Use seed_ids from Phase 0 as `paper_ids` for fetch_refs and fetch_forward
- Run co_cite with min_count=2
- Be generous with year range — user-provided seeds may span many years

### Phase 2 — Optional: Keyword Enrichment

After citation expansion, the store may be missing recent papers not yet
well-cited. Optionally run 1–2 keyword search rounds:

  ds.query.analyze(query)   → keywords, criteria
  ds.papers.search(...)     → adds keyword results
  ds.papers.judge(...)      → scores for ranking

Skip this phase if the user explicitly said "only papers related to these seeds".

### Phase 3 — Rank and Filter
→ `references/l1/rank-and-filter.md`

Parameters:
- Use "foundational/influential" weight profile if user wants seminal papers
- Use "standard" profile otherwise
- top_k: 80

---

## Output summary template

```
DeepSearch complete (Citation-First strategy)
  Seeds: <N> user-provided papers
  Expansion: <N> refs + <N> co-cited + <N> forward citations
  Keyword enrichment: <N> papers (if ran)
  Total collected: <N> | Returned: <top_k>
```
