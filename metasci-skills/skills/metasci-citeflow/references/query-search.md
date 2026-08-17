# Phase 1: Query Analysis + Adaptive Search

Read a problem seed (research hypothesis), extract structured keyword groups,
then adaptively search using S2 and/or OpenAlex. Diagnose search quality after
each call and decide whether to continue, switch engines, or rewrite keywords.

**Search tool budget: 6 calls maximum.**

---

## Step 1: Keyword Group Generation

Read the problem_seed. Extract 3–5 keyword groups:

### Rules

1. **Identify research elements** via loose syntactic parsing:
   - research_task (always present), contribution, methodology
   - Other: time period, data source, domain/setting

2. **Modifiers vs independent elements:**
   - Adjective modifying a head noun → modifier, stays in that group
   - Independent noun phrase → separate group

3. **Each group = 2–4 words** (max 5 rare cases). Use lemmatized forms.
   Preserve compound terms: "hate speech", "named entity recognition".

4. **Priority:** research_task first, then by retrieval importance.

5. **Infer implicit directions:** if the hypothesis implies a related research
   community not mentioned in the text, add a keyword group for it. This is
   where agent intelligence adds value over syntactic parsing.

### Example

"Can we improve machine unlearning evaluation by borrowing calibration
metrics from conformal prediction?"

```
1. ("machine unlearning", "evaluation")
2. ("conformal prediction", "calibration")
3. ("unlearning", "benchmark")
4. ("model editing", "knowledge")  ← inferred related direction
```

### Byproduct: Discriminative Terms

Produce discriminative_terms for later keyword-match scoring. Score 1–10:
how well this term distinguishes target papers from random papers in the
same broad field. Language names, proper nouns, rare methodology score high;
"model", "learning", "network" score low.

---

## Step 2: Adaptive Search

### Flow

1. Pick first 2 keyword groups, start with S2 (better semantic recall)
2. Diagnose `top_papers` from the response
3. Decide next action based on diagnosis

### Diagnosis Criteria

| Signal | Good | Needs Attention |
|---|---|---|
| Title relevance | ≥6/10 related | <4/10 related |
| Year distribution | Mix of recent + foundational | All pre-2015 or all 2024+ |
| Citation count | Mix of >100 and 10-100 | All <10 or all >5000 |
| Result count | merged ≥ 30 | <15 (too narrow) or = limit (too broad) |

### Engine Strategy

- **S2 first**: better semantic matching
- **Switch to OA when**: S2 fails (status="failed"), or S2 misses a direction
- **OA strengths**: broader keyword coverage, no rate-limits

### When to Rewrite

- **Off-topic**: keywords are ambiguous (e.g., "LoRA" → LoRa wireless)
- **Too narrow**: merged < 15 → remove the most restrictive term
- **Too broad**: all generic ML papers → add a more specific term
- **Missing direction**: generate a new group for it

### Budget Allocation (6 calls)

- Call 1–2: First 2 groups on S2
- Call 3: OA for coverage, or next group if S2 results were partial
- Call 4–6: Reserved for diagnosis-driven adjustments

Don't exhaust all 6 blindly — if call 1-2 returned good results, save budget.

---

## Step 3: Persist to Session

Store analysis on the session for later phases:

```python
{
    "query": "<problem_seed>",
    "structured_keywords": [["machine unlearning", "evaluation"], ...],
    "search_queries": ["machine unlearning evaluation", ...],
    "discriminative_terms": {"conformal": 8, "calibration": 6, ...},
    "rerank_query": "evaluation machine unlearning calibration conformal prediction"
}
```
