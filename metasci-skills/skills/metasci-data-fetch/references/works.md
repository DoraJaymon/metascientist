# General Works Retrieval

Use this reference for OpenAlex-backed paper/work retrieval by query, topic,
source, institution, author ID, and year.

Read `query-selection.md` first when the request mixes keywords, broad topics,
sources, venues, institutions, or authors.

## Keyword / Year

Direct tool:

```json
{
  "tool": "metasci_search_works",
  "arguments": {
    "query": "peer review",
    "from_year": 2020,
    "to_year": 2025,
    "limit": 500
  }
}
```

CLI:

```bash
metasci works search "peer review" \
  --from-year 2020 \
  --to-year 2025 \
  --limit 500 \
  --json
```

## Topic + Keyword

Use this when the user asks for a broad field plus a literal concept.

```bash
metasci works search "peer review" \
  --topic-name "Artificial Intelligence" \
  --from-year 2021 \
  --limit 500 \
  --json
```

## Source / Year

Use this for a journal, proceedings, repository, or venue constrained mainly by
source and year range.

```bash
metasci works search \
  --source-name "Journal of Informetrics" \
  --from-year 2022 \
  --to-year 2023 \
  --json
```

For supported CS conference accepted/proceedings lists, prefer
`references/conferences.md` instead of general source search.

## Institution-Constrained Retrieval

```bash
metasci works search "quantum computing" \
  --institution-name "University of Science and Technology of China" \
  --from-year 2020 \
  --to-year 2025 \
  --limit 500 \
  --json
```

## Author ID Retrieval

Use this after author disambiguation or when the user provides an OpenAlex
Author ID:

```bash
metasci works search \
  --author-id A5069892096 \
  --from-year 2020 \
  --to-year 2025 \
  --json
```

Do not guess between same-name authors. Read `authors.md` first if the user
only provides a name.

## Include Non-Core Fields

Default saved work records include core metadata, source, topics, and abstract
inverted index when available. Add optional fields only when needed:

```bash
metasci works search "bibliometrix" \
  --from-year 2023 \
  --include authors \
  --include references \
  --json
```

## Output

Report the exact command or direct tool call, saved `papers.json` path, returned
count, filtered total when present, provider, and diagnostics.
