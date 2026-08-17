# Phase 2: Co-citation Diagnosis + Backward Expansion

Use co-citation analysis to find foundational works that many search results
cite but keyword search never surfaces. Then expand references from selected
store papers to pull in these backbone works and their neighborhoods.

**The agent's role**: diagnose hubs, select expansion sources, supplement
search for missing directions, decide whether a second round is needed.

---

## Step 1: Run Co-citation + Diagnose Hubs

Call `cf.citations.co_cite`. Returns:
- `co_cited` (top 50): works cited by multiple store papers, with title/count/year/cc
- `expansion_candidates` (top 25): store papers ranked by how many hubs
  (count >= 3) they cite

### 1a. Hub Health Check

Count co-cited works with count >= 3:

| Count | Action |
|---|---|
| >= 20 | Healthy, proceed |
| 5-20 | Weak signal, proceed but expect modest expansion |
| < 5 | Very weak — consider going back to Phase 1 with different keywords |

### 1b. Hub Classification

Read the `co_cited` titles. Classify each into:

**A. Direction Core** — title directly relates to a direction the hypothesis needs,
or is a recognized foundational work for that direction.

**B. Related but Broad** — right general field but not specific to the hypothesis.
Still useful structurally.

**C. Noise** — exclude. Satisfies ANY of:
- Generic ML/DL tool with cc > 5000 ("Adam", "ResNet", "Attention Is All You Need")
- No semantic connection to the hypothesis
- Broad survey
- **Adjacent-community overload**: title/keywords genuinely overlap with the
  hypothesis's vocabulary, but the paper belongs to a *different research
  community that happens to reuse the same terms*. This is not caught by the
  "no semantic connection" test — the connection reads as real until you check
  which community actually cites the paper. Example: a hypothesis about
  LoRA-optimizer invariance used the query "Riemannian optimization low-rank
  matrix" to reach K-FAC/manifold-optimization work, but that phrase is more
  strongly claimed by the *matrix-completion / compressed-sensing* community
  (SVT, nuclear-norm minimization, cc 3000-5900) — a real field, on-topic
  words, wrong direction. If a keyword group's search results skew toward one
  unexpected application domain, treat that domain's classics as C even
  though they pass a naive title check.

If a title is ambiguous, look up its abstract from the session store:
```python
session = Session.open(session_id)
record = session.store.get_record(paper_id)
print(record.title, record.abstract)
```

### 1c. Direction Coverage

Group A-rated hubs by direction. Note which directions are strong, weak,
or missing — missing directions may need supplementary search (Step 3b).

---

## Step 2: Select Expansion Sources

Expansion sources are **store papers** whose full reference lists we fetch.
If a paper cites multiple direction-core hubs, its other references are
likely also relevant to the hypothesis.

### From `expansion_candidates`, keep papers that satisfy ALL of:

1. `co_cited_works_cited` >= 2 (genuine junction, not one-off)
2. Title is relevant to the hypothesis direction
3. Not a survey or general classic (cc > 5000 + generic title → skip)
4. Focused on this round's target direction

### Source count: 7-18

Select all passing candidates, clamped to this range. If < 7 pass, relax
threshold to >= 1. If > 18, keep top 18 by `co_cited_works_cited`.

### When `expansion_candidates` itself is compromised

`co_cited_works_cited` ranks candidates by how many hub papers they cite —
if an adjacent-community cluster (see Step 1b) dominates the hubs, it will
also dominate this ranking, and every top candidate will cite mostly *other*
noise hubs. Filtering within `expansion_candidates` cannot fix this; the
list itself is the wrong pool.

When you see this (most of the top-25 candidates classify as C, or as A/B
for the wrong direction), **don't force a selection out of
`expansion_candidates`**. Instead pick `source_ids` directly from store
papers with a good `search_rank` in the direction you actually need —
i.e., go back to the papers your Phase 1 search surfaced for that keyword
group, not the co-citation-derived candidate list. This is what
`source_ids` on `cf.citations.expand_refs_guided` is for: it bypasses
`expansion_candidates` entirely.

### Execute

Call `cf.citations.expand_refs_guided` with `source_ids=[...]`.

---

## Step 3: Diagnose Round 1 → Decide Next Action

Three options (can combine): **A) supplementary search**, **B) Round 2
expansion**, **C) move on to Phase 3**.

### 3a. Growth Check

| Growth | Meaning |
|---|---|
| 3x+ (190→700) | Healthy |
| 2-3x (190→450) | Moderate |
| < 2x (190→300) | Weak — sources may have been poorly chosen |

### 3b. Supplementary Search (max 3 search calls)

**When:** direction diagnosis flagged missing directions that Round 1 didn't
fill. The agent now understands the hypothesis better than in Phase 1, so
supplementary keywords will be more targeted.

**How:** Generate 1-2 keyword groups for the missing direction, call
`cf.papers.search`. These 3 calls are separate from Phase 1's 6-call budget.

After supplementary search: new papers are in the store. If doing Round 2,
re-running co_cite will incorporate them and may reveal new hubs.

### 3c. Round 2?

**Skip if:** single-direction hypothesis well-covered, or hub count was
small (<10), or supplementary search already addressed gaps.

**Run if:** multi-direction hypothesis with Round 1 only deepening one
direction, or supplementary search brought in new papers that may create
new co-citation hubs.

### 3d. Round 2 Procedure

1. Re-run `cf.citations.co_cite` on expanded store
2. New hubs appeared? → Select sources citing them, expand.
   Same hubs with higher counts? → Skip, not much new.
3. Focus on a DIFFERENT direction than Round 1

**Expected store at end of Phase 2: ~600-1200 papers.**

---

## Persisting Diagnosis

After direction diagnosis (Step 1c) and after each round, persist the result
to the session so Phase 3 can read it:

```python
session = Session.open(session_id)
session.set_direction_diagnosis({
    "directions": {
        "unlearning": {"strength": "strong", "hub_count": 6,
                       "key_hubs": ["Machine Unlearning", "Certified Data Removal"]},
        "calibration": {"strength": "missing", "hub_count": 0,
                        "supplementary_searched": True},
    },
    "noise_hubs_excluded": ["Adam", "BERT"],
    "gaps_addressed": ["calibration"],
    "gaps_remaining": ["model editing"],
    "phase": "post_round1"  # update to "post_round2" after Round 2
})
```

Update the `phase` field and gap status after each action (expansion,
supplementary search, Round 2).

---

## Key Rules

- Don't run expansion without reading co_cited first — catch weak signals early
- Each round should focus on one direction; use Round 2 for another direction
- Don't expand from noise hubs' citing papers — scattered references
- Source count follows candidate quality (7-18), not a fixed number
- If a direction is missing, supplement search NOW rather than hoping later
  phases will find it
