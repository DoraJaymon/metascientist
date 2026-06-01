# L1: Iterative Search

Find relevant papers through multi-round keyword search with LLM evaluation.
This is the first phase of any deep search strategy.

**Input:**  research `query`, optional `max_rounds` (default 3), `search_limit` per round (default 50)
**Output:** `session_id` with a populated store, `search_report`

---

## Algorithm

```
1. ds.session.new()                     → session_id
2. ds.query.analyze(query)              → keywords, criteria
3. tried_keywords = [keywords]
   successful_rounds = 0

4. LOOP (up to max_rounds):
   a. ds.papers.search(session_id, keywords, limit=search_limit)
      → added, total, paper_ids

   b. ds.papers.judge(session_id, query, criteria, top_k=15)
      → scores, successful_count

   c. READ the scores. Decide:
      - If successful_count >= 3:  successful_rounds += 1
      - If successful_rounds >= 2: BREAK  (enough relevant papers found)
      - If total_rounds >= max_rounds: BREAK

   d. ds.store.stats(session_id)        → check total, evaluated

   e. Decide rewrite mode:
      - successful_count >= 1 → mode = "expand"   (found something, broaden)
      - successful_count == 0 → mode = "regenerate" (missed, try new angle)

   f. ds.query.rewrite(query, tried_keywords, mode)
      → new_keywords
      tried_keywords.append(new_keywords)
      keywords = new_keywords

5. Return session_id, search_report
```

## search_report format

```python
{
    "session_id": "...",
    "rounds": [
        {"keywords": "...", "added": 40, "successful_count": 5},
        ...
    ],
    "total_papers": 120,
    "successful_rounds": 2,
}
```

## Decision notes

**When to stop early:**
- `successful_rounds >= 2` is the primary stop condition — don't mechanically
  exhaust all rounds if good papers are already found.
- If round 1 finds 0 papers at all (S2 returned nothing), check whether the
  keywords are too specific; try `mode="regenerate"` immediately.

**Choosing top_k for judge:**
- Default 15 is appropriate for limit=50 searches.
- If search returns < 20 papers total, judge all of them (set top_k to total).
- Don't judge more than 20 papers per round — cost control.

**Keyword rewrite hints:**
- If the query involves a specific method + application domain, expand by
  alternating: one round focused on method, next on application.
- If two regenerate rounds both fail, tell the user and ask for clarification
  rather than continuing to burn rounds.
