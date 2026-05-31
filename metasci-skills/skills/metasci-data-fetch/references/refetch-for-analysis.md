# Fetching For Analysis Readiness

Use this reference when retrieval is meant to feed `metasci-analysis`,
especially science landscape, macro collaboration, citation/reference analysis,
or report writing.

## Include Fields

- Bibliometrics can run on core metadata, but author metrics improve with
  `--include authors`.
- Macro country/institution and collaboration analysis needs author
  affiliations, so fetch with `--include authors`.
- Citation overview can run on cited-by counts, but reference-frequency
  analysis needs `--include references`.
- Full science landscape should usually fetch with both:

```bash
--include authors --include references
```

## Fetch Then Preflight

After retrieval, the analysis skill should run:

```python
pre = await ms.analysis.preflight(path, intent="science_landscape")
print(pre.summary())
print(pre.data["suggested_fetch_args"])
```

If preflight reports important missing fields, re-fetch or enrich the dataset
before presenting a complete landscape.

## Re-Fetch Guidance

- Missing macro/institution/collaboration sections: re-fetch with
  `--include authors`.
- Missing reference-frequency sections: re-fetch with `--include references`.
- Sparse title/abstract text: keep topic or co-word conclusions modest; consider
  changing the retrieval query instead of forcing analysis.
- If re-fetching is not possible, continue only with a partial analysis and
  report skipped components.

## Example

```bash
metasci works search "science mapping" \
  --from-year 2024 \
  --to-year 2026 \
  --include authors \
  --include references \
  --limit 50 \
  --json
```
