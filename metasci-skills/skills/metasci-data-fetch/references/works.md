# General Works Retrieval

Use this reference for paper/work retrieval by query, topic, source,
institution, author ID, year, explicit ScienceDirect/Elsevier routing, and
Springer DOI/URL-level retrieval.
OpenAlex remains the default broad discovery provider.

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

## ScienceDirect / Elsevier Retrieval

Use ScienceDirect only when the user explicitly requests ScienceDirect,
Elsevier, or ScienceDirect article metadata. The runtime must have
`ELSEVIER_API_KEY` or `SCIENCEDIRECT_API_KEY`; an institutional token may be
required for entitlement-sensitive fields.

```bash
metasci works search "deep learning AND drug discovery" \
  --provider sciencedirect \
  --from-year 2024 \
  --to-year 2025 \
  --limit 50 \
  --json
```

For a known DOI, prefer single-work retrieval:

```bash
metasci works get 10.1016/j.example.2025.01.001 \
  --provider sciencedirect \
  --json
```

For full-text XML, use the dedicated command so the XML is saved as a separate
artifact rather than mixed into `papers.json`:

```bash
metasci works fulltext 10.1016/j.example.2025.01.001 \
  --provider sciencedirect \
  --json
```

ScienceDirect search currently applies query, year range, and limit. It returns
normalized work records with DOI, PII, title, publication date, source title,
and open-access status when available. DOI-level retrieval may add abstract,
authors, references, ISSN, and raw Elsevier JSON depending on API response and
subscription entitlements. Full-text retrieval writes `fulltext.xml` plus
`metadata.json`; access may fail for non-open or non-entitled articles.

## Springer DOI / URL Retrieval

Use Springer only for known DOI, DOI URL, or Springer article URL retrieval.
The first version does not support `works.search --provider springer`.

For metadata:

```bash
metasci works get 10.1007/s10796-025-10632-z \
  --provider springer \
  --json
```

For full-text Markdown:

```bash
metasci works fulltext 10.1007/s10796-025-10632-z \
  --provider springer \
  --json
```

To save the PDF when Springer exposes one:

```bash
metasci works fulltext 10.1007/s10796-025-10632-z \
  --provider springer \
  --download-pdf \
  --json
```

Springer full-text retrieval writes `fulltext.md`, `work.json`, and
`metadata.json`; with `--download-pdf` it also writes `article.pdf`. Metadata is
normalized into the same work shape used by other providers. `referenced_works`
contains DOI URLs only when a DOI can be extracted; full reference strings are
kept under `_raw.references` in `work.json`.

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
