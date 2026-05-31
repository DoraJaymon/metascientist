---
name: metasci-analysis
description: Analyze saved MetaSci works datasets with the MetaSci Python package. Use when the user asks for bibliometrics, science mapping, science-landscape workflows, topic landscapes, co-word networks, country/institution collaboration, author landscape/roles/collaboration, citation overviews, analysis preflight, readiness, or analysis of an existing metasci_outputs papers.json dataset. Prefer Python package calls (`import metasci_universe as ms`) over CLI for analysis composition; keep CLI as fallback only.
allowed-tools:
  - Bash(python *)
  - Bash(metasci dataset info *)
  - Bash(metasci tools *)
---

# MetaSci Analysis

Use the installed MetaSci Python package for analysis workflows. The CLI remains useful for data retrieval and quick inspection, but analysis composition should be Python-first.

## Runtime

In an installed environment:

```bash
python analysis_script.py
```

In a local source checkout where `metasci_universe` is not installed into the active Python environment, run Python with:

```bash
PYTHONPATH=metasci-universe/src python analysis_script.py
```

## Core Pattern

```python
import asyncio
import metasci_universe as ms

async def main():
    dataset = "metasci_outputs/.../papers.json"
    rec = await ms.analysis.preflight(dataset, intent="science_landscape")
    print(rec.summary())
    print(rec.data["safe_defaults"])

    result = await ms.analysis.topic_landscape(
        dataset,
        text_backend="sklearn",
        modeling_backend="sklearn_lda",
        min_count=rec.data["safe_defaults"]["min_count"],
    )
    print(result.summary())
    print(result.artifacts)

asyncio.run(main())
```

Before choosing an analysis, run:

```python
rec = await ms.analysis.preflight(dataset_path, intent="auto")
```

Use `rec.data["safe_defaults"]` instead of inventing defaults. For lightweight, reproducible agent runs, prefer:

- `text_backend="sklearn"`
- `modeling_backend="sklearn_lda"`
- `min_count=1` for small datasets, otherwise the preflight default

## Design Principle

Prefer a few unified analysis entrypoints over many tiny tool calls. Each
entrypoint should generate a coherent artifact bundle: `analysis.json`,
`summary.md`, CSV tables, and HTML figures when visualization dependencies are
available. Do not split country maps, author roles, coauthor networks, topic
tables, and timelines into separate user-facing tools unless the user asks for
one narrow artifact.

Default analysis families:

- `preflight`: decide readiness, safe defaults, and whether to re-fetch.
- `bibliometrics`: output, citation, source, topic, and basic corpus-author overview.
- `macro`: country/institution productivity, impact, temporal patterns, collaboration networks, country chord diagrams, and corresponding-author country SCP/MCP distributions.
- `author_landscape`: corpus-level author productivity, first/last/corresponding roles, affiliations, topics, and coauthor networks.
- `topic_landscape`: OpenAlex topics, co-word signals, topic modeling, and topic evolution.
- `citation_overview`: citation distribution and referenced-work frequency.
- `science_landscape`: one composed workflow over the major families.

## Routing

| User intent | Python API |
| --- | --- |
| "Can this dataset support analysis?" | `await ms.analysis.preflight(path, intent="auto")` or `inspect_readiness` |
| Overall publication/citation/source/author overview | `await ms.analysis.bibliometrics(path, ...)` |
| Countries, institutions, international collaboration, country chord diagrams, corresponding-author country SCP/MCP plots | `await ms.analysis.macro(path, ...)` |
| Corpus author roles, coauthor networks, repeated contributors, affiliations | `await ms.analysis.author_landscape(path, ...)` |
| Keywords, terms, co-word network, term evolution | `await ms.analysis.coword(path, ...)` |
| Topic model only | `await ms.analysis.topic_modeling(path, backend="sklearn_lda", ...)` |
| Broad topic map / science-map / thematic landscape | `await ms.analysis.topic_landscape(path, ...)` |
| Citation distribution, top cited papers, reference frequency | `await ms.analysis.citation_overview(path, ...)` |
| Broad saved-dataset analysis with multiple components | `await ms.workflows.science_landscape(path, output_dir=...)` |

If the user asks to fetch data first, use `metasci-data-fetch` before this skill.
For the full broad workflow, read `references/workflows/science-landscape.md`.

## Discovery

When unsure about parameters:

```python
import metasci_universe as ms

print(ms.list_tools())
print(ms.describe_tool("analysis.topic_landscape"))
print(ms.tool_schema("analysis.topic_landscape"))
```

The same schemas power the CLI fallback:

```bash
metasci tools describe analysis.topic_landscape --json
metasci tools run analysis.topic_landscape '{"dataset_path": "..."}' --json
```

## Readiness Rules

- If `analysis.macro` is missing, tell the user to re-fetch with `--include authors`.
- If `analysis.author_landscape` is missing, tell the user to re-fetch with `--include authors`.
- If the user's question needs reference-frequency, intellectual-base, or citation-network evidence and references are missing, re-fetch with `--include references`; otherwise continue and report the limitation.
- If title/abstract coverage is low, avoid strong claims from co-word or topic modeling.
- If OpenAlex topics are missing but text exists, topic landscape can still run with co-word and topic modeling.

## Depth Rules

- For a general landscape, use `science_landscape` or run `bibliometrics + macro + author_landscape + topic_landscape + citation_overview`.
- For country/institution questions, use `macro` as the single entrypoint and read productivity, citation impact, international collaboration share, temporal tables, maps, collaboration networks, country chord diagrams, and corresponding-author country SCP/MCP outputs.
- For author questions, use `author_landscape` as the single corpus-level entrypoint. Use `authors.profile` only for targeted enrichment of selected authors, not as the default corpus analysis.
- For topic modeling, remember that the current tool mainly produces topic
  assignments and standard topic artifacts; it does not automatically answer
  every "topic analysis" question. If the user asks for interpretation, choose
  a small, question-relevant follow-up analysis from the available artifacts and
  source metadata. State clearly when a desired derived table is not yet
  materialized by the package.
- For report preparation, do not stop at top-N tables. Read the richer CSV/JSON fields: role counts, collaborator counts, timelines, network edges, affiliation/topic tables, skipped components, and diagnostics.
- If references are missing and the user asks about intellectual foundations, re-fetch before writing strong knowledge-base claims. For questions that do not depend on references, do not make re-fetch mandatory.

## Reference Files

Read only the relevant reference when needed:

- `references/python-patterns.md` for common Python snippets.
- `references/tool-routing.md` for analysis intent and parameter choices.
- `references/common-mistakes.md` for failure modes.
- `references/workflows/science-landscape.md` for the composed broad landscape scenario.

## Output

Report:

1. Python API call used
2. dataset path
3. readiness or preflight summary
4. analysis artifact paths, especially `summary_md`, `analysis_json`, CSV tables, and HTML figures
5. diagnostics and missing-field advice

Do not paste large JSON payloads unless the user asks.
