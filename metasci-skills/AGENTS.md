# MetaSci Skills

Bundle-level routing guide for MetaSci skills. Use the installed MetaSci runtime.
For retrieval, the `metasci` CLI is often the fastest path. For analysis
composition, prefer the Python package:

```python
import metasci_universe as ms
```

Do not use `deepalex`, `openalex_agent`, local `.venv` paths, or private DB
credentials.

## Routing

Use `metasci-data-fetch` for:

- paper / work retrieval
- OpenAlex-backed dataset creation
- keyword, topic, source, author, institution, or year-constrained work search
- saved works dataset inspection
- author candidate search, disambiguation, profiles, and DOI/work authorships

Use `metasci-analysis` for:

- analysis of an existing saved works dataset
- readiness checks and tool recommendations
- bibliometrics, macro country/institution analysis, author landscape analysis,
  co-word analysis, topic modeling, topic landscapes, and citation overviews
- broad science-landscape workflows over saved datasets
- analysis workflows that may need to go back to data fetching after preflight
- Python-first composition with `ms.analysis.*`

Use `metasci-report-writer` for:

- turning MetaSci analysis artifacts into a sectioned report
- improving or reviewing an existing MetaSci report
- applying report templates, quality rubrics, and provenance checks
- writing executive briefs, science-landscape reports, topic-trend reports,
  author-impact briefs, conference-landscape briefs, or technical appendices

If a task needs both author disambiguation and work retrieval, resolve the
author first with `metasci-data-fetch`, then retrieve works with the selected
`--author-id`.

If a task needs data retrieval and analysis, retrieve first with
`metasci-data-fetch`, then analyze the saved dataset with `metasci-analysis`.

If analysis preflight reports missing fields, go back to `metasci-data-fetch`
with the suggested `--include` options, then rerun the analysis. Do not silently
drop missing macro or citation-reference sections when the user asked for a full
landscape.

## Output

For successful retrievals, report:

- exact `metasci` command used
- returned count / filtered total when available
- saved data path
- diagnostics
- resolved entities when name-based resolution was used

Do not paste large JSON payloads. Point to the saved data file instead.

For successful analyses, report:

- Python API call used
- saved dataset path
- readiness/recommendation summary
- analysis artifact paths
- diagnostics and suggested re-fetch args when fields were missing
