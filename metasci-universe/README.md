# MetaSci Universe

Phase 1 package skeleton for agent-native meta-science data acquisition.

## Installation

MetaSci Universe keeps the default install focused on data retrieval. Install
only the capability tier you need:

```bash
pip install metasci-universe
pip install "metasci-universe[analysis]"
pip install "metasci-universe[embeddings]"
pip install "metasci-universe[all]"
```

The tiers are:

- `metasci-universe`: data acquisition, author/work/conference/citation lookup,
  saved dataset I/O, CLI, and agent tool discovery.
- `metasci-universe[analysis]`: normal bibliometric, macro, co-word, citation,
  topic landscape, and sklearn LDA analysis.
- `metasci-universe[embeddings]`: analysis plus local sentence-transformers
  embedding workflows and embedding-based clustering.
- `metasci-universe[all]`: every optional backend, including BERTopic, HDBSCAN,
  and spaCy.

Default analysis settings are dependency-light: sklearn tokenization and LDA are
used unless a caller explicitly selects embedding or BERTopic backends.

Current scope:

- OpenAlex API provider
- DOI/URL-level Springer article metadata and Markdown full-text retrieval
- conference-paper retrieval from high-value CS venue sources:
  OpenReview and DBLP
- works search and single-work lookup
- author search, profile lookup, and DOI/work authorship lookup
- dataset artifact writing/loading
- CLI and agent tool discovery

The base package intentionally avoids database, service, LLM, and agent runtime
dependencies.
