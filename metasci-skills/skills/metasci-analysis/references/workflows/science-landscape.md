# Science Landscape Workflow

Use this reference when the user asks for a broad research landscape, topic map,
scientometric overview, science mapping report, or fetch-and-analyze workflow.

This is a composed workflow, not a separate top-level skill. It should be
invoked through `metasci-analysis`, with `metasci-data-fetch` used when the
dataset is missing or preflight says required fields are absent.

## Scenario

Saved works dataset -> preflight -> optional re-fetch -> bibliometrics + macro
+ author landscape + topic landscape + citation overview -> artifact-backed summary -> optional
handoff to `metasci-report-writer`.

## Workflow

1. Identify or create the dataset.
   - If the user provides `papers.json` or a `metasci_outputs/...` directory,
     reuse it.
   - If the user asks to fetch papers, use `metasci-data-fetch`. For a full
     landscape, prefer authors and references when feasible.
2. Run preflight before analysis:

```python
import asyncio
import metasci_universe as ms

async def main():
    pre = await ms.analysis.preflight(
        "metasci_outputs/.../papers.json",
        intent="science_landscape",
    )
    print(pre.summary())
    print(pre.data["suggested_fetch_args"])

asyncio.run(main())
```

3. If preflight reports missing fields that materially affect the user's goal,
   go back to data fetching.
   - Missing macro/institution analysis: re-fetch with `--include authors`.
   - Missing author landscape: re-fetch with `--include authors`.
   - Missing reference-frequency analysis: re-fetch with `--include references`
     only when the user's question needs reference evidence.
   - For a full science landscape, prefer `--include authors`; add
     `--include references` when the report needs a citation/reference
     foundation.
   - If re-fetching is not possible, continue with `skip_unready=True` and
     report skipped components.
4. Run the composed Python workflow:

```python
import asyncio
import metasci_universe as ms

async def main():
    result = await ms.workflows.science_landscape(
        "metasci_outputs/.../papers.json",
        output_dir="metasci_outputs/analysis/science_landscape",
        top_n=30,
    )
    print(result.summary())
    print(result.artifacts)

asyncio.run(main())
```

5. Read `result.data["components"]` and the generated `summary_md`.
6. For a user-facing report, invoke `metasci-report-writer` on the workflow
   artifacts.
7. Report the dataset path, components run/skipped, diagnostics, summary path,
   and report path when produced.

## Fetch Defaults

For new datasets that need author and reference evidence:

```bash
metasci works search "science of science" \
  --from-year 2020 \
  --to-year 2026 \
  --include authors \
  --include references \
  --limit 500 \
  --json
```

Use smaller limits for smoke tests. Use explicit IDs after author/source
disambiguation.

## Output Contract

Return:

- exact fetch command if data was fetched
- exact re-fetch command if preflight required better data
- dataset artifact path
- preflight result summary
- Python analysis call
- components run and skipped
- summary markdown path
- report path when `metasci-report-writer` was used
- key analysis artifact directories
- diagnostics and re-fetch suggestions

Do not present the broad landscape as a literature review. It is a
scientometric/data analysis over the retrieved works.

## Report Boundary

The built-in workflow summary is compact. A good default user-facing report
should be sectioned, not a full paper:

- Dataset and coverage
- Output and citation profile
- Topic structure
- Country, institution, and collaboration structure
- Author roles, repeated contributors, and coauthor structure
- Citation/reference signals
- Interpretation
- Limitations
- Artifacts

Use `metasci-report-writer` to produce and improve that report.
