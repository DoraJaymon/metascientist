# L1: Citation Expansion

Expand paper coverage using the citation network, starting from seed papers.
This phase typically follows iterative-search and adds papers that keyword
search cannot reach — foundational works, recent citing papers, knowledge hubs.

**Input:**  `session_id` (populated store), `query`, `criteria`
**Output:** `session_id` with expanded store, `expansion_report`

---

## Algorithm

```
1. READ the store first
   ds.store.stats(session_id)
   → understand current state (total, evaluated, existing seeds)

2. SELECT seeds

   Option A — score-based (default):
     ds.store.seeds.candidates(session_id, n=10)
     → candidates list with in_domain_citations, score, year

     LOOK at the candidates. Choose seeds by:
     - Prefer papers with both high LLM score (if available) AND high in_domain_citations
     - Avoid papers with citation_count > 5000 (too general, will explode)
     - Pick 3–7 seeds. More seeds = more papers but slower.

     ds.store.seeds.mark(session_id, paper_ids=[chosen ids], tag="seed_r1")

   Option B — LLM judge (higher quality, slower):
     ds.store.seeds.candidates(session_id, n=20)   → get wider candidate pool
     ds.papers.judge(session_id, query, criteria, paper_ids=[candidate ids])
     → pick ids where score >= 0.6
     ds.store.seeds.mark(session_id, paper_ids=[high-score ids], tag="seed_r1")

3. FETCH REFERENCES (backward expansion)
   seed_ids = [openalex_id of each seed]

   ds.citations.fetch_refs(session_id, paper_ids=seed_ids, limit_per_paper=60)
   → adds referenced works to store

4. CO-CITATION ANALYSIS
   ds.citations.co_cite(session_id, min_count=2)
   → finds papers cited by multiple store papers (knowledge hubs)
   → adds them to store

5. DECIDE forward citation parameters
   READ the expansion so far:
   ds.store.stats(session_id)

   Look at the candidate papers' year distribution and citation counts.
   Decide:
   - year_start: typically (earliest_seed_year - 1), floor at 2015 for recent topics
   - min_citations: 0 for niche topics; 5–10 for popular topics to avoid noise
   - If the topic is fast-moving (LLMs, diffusion models), use recent year_start

6. FETCH FORWARD CITATIONS
   ds.citations.fetch_forward(
       session_id,
       paper_ids=seed_ids,
       year_start=<decided>,
       min_citations=<decided>,
       max_per_paper=100,
   )

7. Return session_id, expansion_report
```

## expansion_report format

```python
{
    "session_id": "...",
    "seeds_used": ["W123", "W456", ...],
    "refs_added": 85,
    "co_cited_added": 12,
    "forward_added": 143,
    "total_after": 360,
    "params_used": {"year_start": 2018, "min_citations": 5},
}
```

## Decision notes

**Seed selection is the most important decision here.**
A good seed is highly cited within the domain, not too broad, and directly
relevant to the query. A bad seed (e.g. a survey paper with 10k citations)
will flood the store with tangentially related papers.

**On forward citation parameters:**
Don't use a fixed formula. Look at the data:
- If seeds are all from 2017–2020, year_start=2016 is reasonable.
- If the topic is very niche (few papers), set min_citations=0.
- If store already has 300+ papers, raise min_citations to 10 to stay focused.

**When to skip forward citations:**
- If the topic is purely historical (no interest in recent citing papers)
- If seeds have very few citations (< 20 each) — forward expansion won't add much

**When to run a second expansion round:**
After fetching, run `ds.store.stats` again. If citation_papers < 50 and the
topic warrants broad coverage, consider selecting new seeds from the freshly
added papers and running a second expansion.
