---
name: metasci-citation-lookup
description: Resolve a scholarly paper and find its references and/or citing papers through MetaSci Universe. Use when the user asks for citation lookup, references, citing papers, forward/backward citations, 被引论文, 参考文献, 引用关系, or asks to test citation lookup for a specific paper. Uses OpenAlex first and Semantic Scholar only as fallback/supplement.
allowed-tools:
  - Bash(metasci citations *)
  - Bash(python -m metasci_universe.cli citations *)
  - Bash(PYTHONPATH=metasci-universe/src python -m metasci_universe.cli citations *)
---

# MetaSci Citation Lookup

Use this skill to resolve one scholarly paper and fetch citation graph edges:

- `references`: papers this work cites
- `citations`: papers that cite this work

Do not use this skill for corpus-level citation summaries over a saved dataset;
use `metasci-analysis` and `analysis.citation_overview` for that.

## Route by user intent

Use the narrow command when the user asks for only one side.

### References only

For "references", "参考文献", "这篇论文引用了谁", or "backward citations":

```bash
PYTHONPATH=metasci-universe/src python -m metasci_universe.cli citations refs \
  --title "PAPER TITLE" \
  --provider auto \
  --limit 1000 \
  --json
```

### Citing papers only

For "citing papers", "被引论文", "谁引用了它", or "forward citations":

```bash
PYTHONPATH=metasci-universe/src python -m metasci_universe.cli citations citing \
  --title "PAPER TITLE" \
  --provider auto \
  --limit 1000 \
  --json
```

### Both sides

For general "citation lookup", "引用关系", "test this paper", or when the user
does not specify one side:

```bash
PYTHONPATH=metasci-universe/src python -m metasci_universe.cli citations lookup \
  --title "PAPER TITLE" \
  --provider auto \
  --limit 1000 \
  --json
```

`lookup` always returns both references and citing papers. Do not pass
`--direction`; it is not a public parameter.

## Inputs

Prefer stable identifiers over title search:

1. `--openalex-id W...`
2. `--doi 10...`
3. `--arxiv-id 2411.00816`
4. `--s2-id ...`
5. `--s2-corpus-id ...`
6. `--title "..."`

If title lookup returns multiple candidates, report the ambiguity and ask for a
DOI, arXiv ID, OpenAlex ID, or S2 ID if precision matters.

## Provider policy

Use `--provider auto` by default.

`auto` means:

- resolve through OpenAlex first
- fetch requested refs/citing through OpenAlex first
- if a requested side is missing or clearly incomplete and a DOI is available,
  query OpenCitations before S2 and enrich its DOI/OpenAlex identifiers through
  OpenAlex metadata
- if OpenAlex + OpenCitations are still missing or clearly incomplete, resolve
  S2 once and use Semantic Scholar as the final supplement
- for `lookup`, if either side triggers supplement, supplement both requested
  sides
- preserve partial S2 results when pagination hits rate limits

When an S2 API key is available, pass it through the environment as
`S2_API_KEY` or `SEMANTIC_SCHOLAR_API_KEY`. Never hard-code a real key in the
skill, command examples, repository files, or committed docs.

Use `--provider openalex` only when the user explicitly asks not to call
Semantic Scholar or wants OpenAlex-only results.

## Output

Do not paste full JSON unless the user asks. Summarize:

- command used
- resolved OpenAlex ID, DOI, arXiv ID, S2 ID / Corpus ID when present
- whether resolve used only OpenAlex or needed S2 fallback
- `provider_counts.references` and/or `provider_counts.citations`
- whether S2 supplement was triggered
- diagnostics, especially title ambiguity, rate limits, or partial S2 results

If the command fails with `All connection attempts failed`, retry with network
permission if available.
