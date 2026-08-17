---
name: metasci-deepsearch
description: >
  [ARCHIVED] Replaced by metasci-citeflow skill system.
  Legacy recipe-based deep search with fixed pipeline. Kept for reference only.
allowed-tools:
  - Bash(python *)
  - Bash(metasci tools *)
---

# MetaSci DeepSearch

Use this skill to find papers for a research question using the CiteFlow algorithm.
The skill is **layer-driven**: choose the right strategy first, then follow the
corresponding reference document.

## Choosing a strategy

| User intent | Strategy | Reference |
|---|---|---|
| Standard deep search — broad coverage, citation-aware | `citeflow` | `references/l2/citeflow.md` |
| Quick search, no citation expansion needed | `fast-search` | `references/l2/fast-search.md` |
| User already has seed papers, wants related literature | `citation-first` | `references/l2/citation-first.md` |

When in doubt, use `citeflow`.

## Runtime

```python
import asyncio
import metasci_universe as ms

async def main():
    # Check available tools
    print([t for t in ms.list_tools() if t.startswith("ds.")])

asyncio.run(main())
```

All `ds.*` tools share a **session_id** that keeps the paper store alive across
calls.  Always start with `ds.session.new` and pass the returned `session_id`
to every subsequent call.

## Tool quick-reference

```
ds.session.new()                               → session_id
ds.query.analyze(query, mode?)                 → keywords, criteria
ds.query.rewrite(query, tried, mode, hint?)    → keywords
ds.papers.search(session_id, keywords, limit?) → added, total, paper_ids
ds.papers.judge(session_id, query, criteria, paper_ids?, top_k?) → scores, successful_count
ds.citations.fetch_refs(session_id, paper_ids, limit_per_paper?) → added, total
ds.citations.fetch_forward(session_id, paper_ids, year_start?, year_end?, min_citations?) → added, total
ds.citations.co_cite(session_id, min_count?)   → co_cited_count, added
ds.store.stats(session_id)                     → total, evaluated, seeds, ...
ds.store.seeds.candidates(session_id, n?)      → candidates list
ds.store.seeds.mark(session_id, paper_ids)     → marked
ds.store.rank(session_id, weights?, top_k?)    → papers
```

## Output

After completing a strategy, the final result comes from `ds.store.rank`.
Return the top papers with title, year, citation_count, and relevance scores.
Summarise: how many papers found, how many via search vs citation expansion,
top 5 titles.
