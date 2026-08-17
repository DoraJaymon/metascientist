# Phase 3: Forward Expansion (Experimental)

Forward expansion finds later papers that cite selected papers already in the
session. It is useful when the question requires recent follow-on work or when
Phase 2 found foundational papers but few modern applications.

This is an experimental recipe, not a default pipeline stage. A larger store
does not by itself improve top-K retrieval: on early CiteFlow cases, forward
expansion sometimes pushed an already-found relevant paper below rank 100.

## Preconditions

- Complete Phase 1 and Phase 2 first.
- Inspect the current store and direction diagnosis.
- Use only papers that have not already been used as forward-expansion seeds.
- Record the chosen seeds and parameters in the session ledger.

## One Expansion Round

1. Select candidate papers from the previous expansion round:

   ```text
   cf.seeds.select_citations { session_id, round }
   ```

   This calls autoscore, filters candidates, ranks them, asks the relevance
   selector to judge the leading candidates, and chooses citation seeds. The
   result includes `seed_ids` and `total_seed_citations`.

2. Inspect the seed set before fetching. Prefer seeds that cover a direction
   still missing from Phase 2. Do not select generic classics solely because
   they have high global citation counts.

3. Inspect the seed citation and year distributions:

   ```text
   cf.store.distributions { session_id, paper_ids: [...] }
   cf.citations.decide_params {
     session_id,
     total_seed_citations,
     citation_distribution,
     year_distribution
   }
   ```

   `cf.citations.decide_params` uses the CiteFlow parameter-decider prompt and
   clamps its output to safe ranges. Keep the returned `year_start` and
   `min_citations` with the experiment record.

4. Fetch citing papers:

   ```text
   cf.citations.fetch_forward {
     session_id,
     round,
     seed_ids: [...],
     year_start,
     min_citations
   }
   ```

   The OpenAlex graph provider paginates the citing-work results, normalizes
   them into CuraLib records, deduplicates them, and appends a `citations` row
   to the session ledger.

5. Re-score and inspect ranking impact:

   ```text
   cf.store.autoscore { session_id }
   cf.papers.filter { session_id }
   cf.store.rank { session_id, top_k: 100 }
   ```

## Repeat Or Stop

Run at most three forward rounds while this remains experimental. Stop when
one of these is true:

- the previous round added little new material;
- new results mostly repeat directions that are already strong;
- the seed selector cannot find fresh, relevant seeds;
- a held-out case shows lower recall@K after ranking.

Use another round only for a distinct unresolved direction. Do not treat store
growth as success; compare the ranked output or `cf.eval.score` before and
after expansion.

## Reference Implementation

`dev_scripts/run_forward_expand_9.py` is an experimental, direction-aware
batch implementation. It selects one or two seeds per search-query direction,
fetches their OpenAlex citations, persists sessions, and reports exact/fuzzy
gold-title coverage. It is useful for understanding the intended policy, but
it contains benchmark-specific paths and is not a portable CLI.
