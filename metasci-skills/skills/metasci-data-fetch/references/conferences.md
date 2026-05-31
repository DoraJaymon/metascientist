# Conference Paper Retrieval

Use this reference when the user asks for accepted papers, proceedings papers,
or conference/year datasets for supported CS venues.

Prefer conference connectors over general OpenAlex source search because
conference metadata can be fragmented across proceedings, tracks, workshops,
preprints, and publisher pages.

This connector retrieves conference/year paper lists. It is not the first
choice for open-ended keyword or topic search. For keyword/topic search across
venues, use `works.md`. For keyword/topic search within a conference/year, fetch
the conference list first when coverage matters, then filter or analyze locally.

## Supported Connector Choices

- `openreview`: ICLR / NeurIPS / ICML when OpenReview is the desired source.
- `acl`: ACL / EMNLP / NAACL / COLING / EACL.
- `cvf`: CVPR / ICCV / WACV.
- `pmlr`: AISTATS / COLT / UAI / CoRL, or ICML with explicit PMLR volume.
- `dblp`: fallback for broader CS venue bibliographic lists.
- `auto`: let MetaSci choose when the user does not specify a source.

## Direct Tool

```json
{
  "tool": "metasci_fetch_conference_papers",
  "arguments": {
    "venue": "acl",
    "year": 2024,
    "source": "auto",
    "limit": 100
  }
}
```

## CLI

```bash
metasci conferences papers acl --year 2024 --source auto --limit 100 --json
```

For source-specific proceedings identifiers:

```bash
metasci conferences papers aistats \
  --year 2024 \
  --source pmlr \
  --source-collection-id v235 \
  --json
```

Use `source_collection_id` for PMLR volume IDs such as `v235`, ACL Anthology
proceedings slugs such as `2024.acl-long`, or explicit CVF listing URLs.

## When Not To Use This

- If the user asks for all works from a journal or non-CS venue, use `works.md`.
- If the user asks for a topical corpus across many venues, use `works.md` and
  `query-selection.md`.
- If the user asks for conference papers plus downstream analysis, fetch the
  conference dataset first, then hand the saved `papers.json` to
  `metasci-analysis`.

## Output

Report connector/source, exact command or direct tool call, saved data path,
returned count, and coverage caveats.
