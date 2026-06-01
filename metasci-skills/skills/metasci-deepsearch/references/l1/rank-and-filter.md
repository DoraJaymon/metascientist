# L1: Rank and Filter

Produce the final ranked paper list from the session store.
This is always the last phase of any deep search strategy.

**Input:**  `session_id` (populated store), optional `weights`, `top_k`
**Output:** ranked paper list, `final_report`

---

## Algorithm

```
1. READ store state
   ds.store.stats(session_id)
   → evaluated, total, seeds

2. DECIDE ranking weights
   Choose based on what data is available and what the user needs:

   Standard (default):
     weights = {relevance: 0.5, centrality: 0.25, recency: 0.25}

   If LLM scores are available (papers.judge was called):
     weights = {llm_score: 0.4, relevance: 0.3, centrality: 0.2, recency: 0.1}

   If in-domain citation expansion was done (citation-expand ran):
     weights = {relevance: 0.4, in_domain_citation_score: 0.2,
                centrality: 0.2, recency: 0.2}

   If user wants recent/cutting-edge papers:
     weights = {relevance: 0.5, recency: 0.4, centrality: 0.1}

   If user wants foundational/influential papers:
     weights = {relevance: 0.3, centrality: 0.5, recency: 0.1,
                in_domain_citation_score: 0.1}

3. RANK
   ds.store.rank(session_id, weights=<decided>, top_k=<top_k>)
   → papers list

4. PRESENT results
   Return the ranked papers with a summary.
```

## final_report format

```python
{
    "session_id": "...",
    "total_in_store": 360,
    "returned": 100,
    "weights_used": {...},
    "top_papers": [
        {"title": "...", "year": 2022, "citation_count": 450,
         "importance_score": 0.87, "source": "citation"},
        ...
    ],
    "breakdown": {
        "search_papers": 120,
        "citation_papers": 240,
    }
}
```

## Decision notes

**On weights:**
Don't overthink this. The default is good for most cases. Only deviate when
the user gives a clear signal ("I want recent papers", "show me the most
cited ones").

**On top_k:**
- Default 100 is appropriate for a full literature review.
- 30–50 for a focused reading list.
- Ask the user if unclear.

**Optional: LLM re-ranking of top results**
If top_k ≤ 30 and high precision matters, run one more judge pass on the
top results before returning:
  ds.papers.judge(session_id, query, criteria, paper_ids=[top 30 ids], top_k=30)
Then re-rank with llm_score weighted higher.
This is expensive — only do it if the user needs a curated, high-precision list.
