# MetaSci Universe

Phase 1 package skeleton for agent-native meta-science data acquisition.

Current scope:

- OpenAlex API provider
- conference-paper retrieval from high-value CS venue sources:
  OpenReview and DBLP
- works search and single-work lookup
- author search, profile lookup, and DOI/work authorship lookup
- dataset artifact writing/loading
- CLI and agent tool discovery

The base package intentionally avoids database, service, LLM, and agent runtime
dependencies.
