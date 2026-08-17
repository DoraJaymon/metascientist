# CuraLib in CiteFlow

`metasci_universe.memory.curalib.PaperStore` is CiteFlow's persistent paper
memory. Agent tools decide which searches and graph operations to run; CuraLib
maintains the evidence those decisions operate on.

## Responsibilities

1. **Identity and deduplication.** Papers are keyed by Semantic Scholar corpus
   ID when available, with OpenAlex ID as a secondary identity. An OpenAlex-only
   citation record uses its OpenAlex ID as its primary key. This prevents the
   same paper found by search and graph traversal from entering the store twice.

2. **Discovery provenance.** Each record keeps `discovery_history`: the round,
   source (`search`, `citation`, or `manual`), query keywords, parent papers,
   and source search rank. A paper may be rediscovered many times while still
   retaining its first-discovery source.

3. **Graph signals.** CiteFlow writes in-domain citation counts and scores to
   records after co-citation analysis. These distinguish papers repeatedly
   connected within the retrieved subgraph from globally famous but diffuse
   papers.

4. **Textual signals.** Autoscore writes keyword-match and embedding-relevance
   scores. The final ranker can use a search-rank fallback when a paper has not
   been reranked yet.

5. **Persistence.** `save_to_json` writes papers, indexes, and the current
   round. `load_from_json` reconstructs the keyword, provider, and OpenAlex
   indexes, so a file-backed CiteFlow session can resume in a different process.

## CiteFlow Data Flow

```text
S2/OpenAlex search or citation graph
  -> PaperStore.add_papers
  -> identity resolution + provenance append
  -> co-citation / autoscore update record signals
  -> filters
  -> PaperStore.rank_by_importance
  -> cf.store.rank result
```

The implementation is in `src/metasci_universe/memory/curalib.py`. Regression
coverage is in `tests/test_curalib.py`, including provider-index persistence,
OpenAlex-only records, cross-provider deduplication, discovery history, and
ranking-signal behavior.
