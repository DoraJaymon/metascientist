---
name: metasci-data-fetch
description: Retrieve scholarly datasets and resolve scholarly entities through MetaSci Universe. Use for paper/work retrieval, author lookup and disambiguation, DOI/work authorships, CS conference accepted/proceedings papers, source/topic/institution filters, keyword-vs-topic query planning, and re-fetching data with fields needed by downstream analysis workflows.
allowed-tools:
  - Bash(metasci works *)
  - Bash(metasci conferences *)
  - Bash(metasci authors *)
  - Bash(metasci dataset info *)
  - Bash(metasci tools *)
---

# MetaSci Data Fetch

Use this skill for data retrieval and entity resolution. Keep the top-level
decision small: plan the query representation, load the relevant execution
reference, then produce one or more executable retrieval actions with saved
artifact paths.

Do not depend on `deepalex`, `openalex_agent`, private DB credentials, or local
legacy repository paths.

## Runtime

Inside `metasci-agent`, prefer direct light-agent tools:

- `metasci_search_works`
- `metasci_fetch_conference_papers`
- `metasci_search_authors`
- `metasci_get_author_profile`
- `metasci_get_work_authors`
- `metasci_dataset_info`

In Codex, Claude Code, or a terminal-only environment, prefer the installed
`metasci` CLI and include `--json` unless the user explicitly wants
human-readable stdout only.

If the CLI is unavailable but the package is importable, inspect and call the
Python API:

```python
import metasci_universe as ms

print(ms.list_tools())
print(ms.describe_tool("works.search"))
result = await ms.run_tool("works.search", {
    "query": "science of science",
    "from_year": 2020,
    "limit": 100,
})
```

## Planning Step

For non-trivial paper retrieval, first apply
`references/query-selection.md` to decide whether the request should be
represented as `query`, `topic_name`, `source_name`, `venue` / `year`,
`author_id`, `institution_name`, or a combination. This is a pre-routing guide,
not an execution destination.

Then load the execution reference:

| User intent | Read |
| --- | --- |
| General paper/work retrieval by query, topic, source, institution, year, or author ID | `references/works.md` |
| Author candidate search, disambiguation, profiles, DOI/work authorships, or works by selected author | `references/authors.md` |
| Accepted/proceedings papers from CS conferences such as ACL, CVPR, ICLR, ICML, NeurIPS, AISTATS, COLT, UAI, CoRL | `references/conferences.md` |
| Fetching or re-fetching data for analysis readiness, especially authors/references for science landscape | `references/refetch-for-analysis.md` |

If a request contains multiple independent datasets, sources, venues, authors,
or entities, write a short retrieval plan first and run one retrieval action per
dataset/entity. Do not collapse independent retrievals into one over-constrained
query.

## Core Extraction

Identify only the elements needed for the classified task:

- `query`: literal title/abstract/full-text keywords, method names, or phrases.
- `topic_name`: conceptual field, discipline, or OpenAlex topic-like phrase.
- `source_name`: journal, proceedings, repository, or venue name for general works search.
- `venue` / `year`: named CS conference and year for conference connectors.
- `author_name` / `author_id`: person name or resolved OpenAlex Author ID.
- `institution_name`: university, company, lab, hospital, or research institute.
- `from_year` / `to_year`: year range. "since 2020" means `--from-year 2020`.
- `include`: optional fields such as `authors` or `references`.
- `limit`: only for sample, preview, top N, or bounded datasets.
- `sort_by`: only when the user explicitly wants newest/recent or another non-default sort.

Prefer explicit OpenAlex IDs (`--author-id`, `--source-id`, etc.) when the user
provides them. If names are ambiguous, surface diagnostics and disambiguate
before fetching dependent datasets.

## Default Rules

- Include `--json` for CLI retrievals so artifact paths can be read from the JSON envelope.
- Do not write empty fields or unchanged defaults.
- Use smaller limits for smoke tests; use larger limits only when the user asks
  for a real dataset.
- For downstream science-landscape analysis, fetch or re-fetch with authors and
  references when feasible. See `references/refetch-for-analysis.md`.
- For conference accepted/proceedings lists, prefer source-specific conference
  connectors over general OpenAlex source search. See `references/conferences.md`.

## Output

Return:

1. the exact direct tool call or CLI command used
2. saved artifact path, especially `data_file` / `papers.json`
3. returned count and filtered total when present
4. provider and diagnostics, especially entity ambiguity or coverage caveats

Do not paste large JSON payloads. Parse JSON envelopes for artifact paths and
summarize the relevant fields.
