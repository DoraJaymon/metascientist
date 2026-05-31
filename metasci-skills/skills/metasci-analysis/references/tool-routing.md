# Tool Routing

## Fast defaults

Use `ms.analysis.preflight(dataset, intent=...)` first. It returns:

- `recommended_tools`: tools that can run
- `blocked_tools`: tools missing required fields
- `safe_defaults`: dependency-light parameters
- `suggested_fetch_args`: retrieval options for re-fetching

## Intent map

| Intent | Use |
| --- | --- |
| `bibliometrics` | production by year, citation summary, top papers, authors, sources, OpenAlex topic frequencies |
| `macro` | countries, institutions, productivity, citation impact, collaboration share, country/institution collaboration networks, maps, temporal collaboration |
| `author_landscape` | corpus author productivity, first/last/corresponding roles, coauthor networks, author affiliations, author-topic footprint |
| `coword` | extracted terms, term co-occurrence edges, term network, term evolution |
| `topic_modeling` | modeled topic clusters from title/abstract text |
| `topic_landscape` | combined OpenAlex topics + co-word + topic modeling |
| `citation_overview` | top cited papers, citation by year, referenced-work frequencies |
| `science_landscape` | composed broad scenario; use when the user asks for an overall analysis/report |

## Parameter choices

- Small exploratory dataset: `min_count=1`, `nr_topics=2` if fewer than 20 records.
- Larger dataset: use preflight defaults.
- Corpus author analysis: prefer `author_landscape` over manually combining top-author tables and author lookup calls.
- Dependency-light topic modeling: `modeling_backend="sklearn_lda"`.
- Semantic clustering only when requested or environment is prepared: `embedding_kmeans`, `embedding_hdbscan`, `bertopic`.
- Text processing: `text_backend="sklearn"` for stable runs; spaCy may work but can require installed language models.

## Fetch advice

- Bibliometrics author metrics, macro analysis, and author landscape need `include=["authors"]`.
- Citation reference frequency, intellectual-base claims, and citation-network
  analysis need `include=["references"]`.
- A full landscape should fetch `authors` by default; add `references` when the
  user's question depends on reference evidence or when the user asks for a
  citation/reference foundation.

## Unified Entry Points

Keep user-facing execution coarse-grained:

- Use `macro` for country/institution questions rather than separate map,
  timeline, and network tools.
- Use `author_landscape` for corpus-level author questions rather than many
  individual `authors.profile` calls.
- Use `topic_landscape` for broad thematic maps rather than separate OpenAlex
  topic, co-word, and topic-model calls unless the user asks for one method.
- When a model has produced topic-paper assignments, use them only as needed
  for the user's question. Do not run a fixed post-analysis checklist.
- Use targeted `authors.profile` enrichment only after `author_landscape`
  identifies authors worth inspecting.
