# Quality Rubric

Use this checklist before finalizing a MetaSci report.

## Outline Review

Run this before writing the full draft.

- The outline states the user's main question and the report's central answer.
- The selected analytical modules match the user request and available artifacts.
- Reader-facing section titles express analytical claims or useful questions, not just component names.
- Each planned section lists the artifact, figure, table, or diagnostic evidence it will use.
- Visual evidence is planned inside the body, not only in the appendix.
- The outline includes a synthesis step that connects evidence streams.
- Missing or weak evidence is assigned to evidence notes rather than stretched into unsupported sections.
- The outline would still make sense if module names were hidden.

## Grounding

- Every quantitative claim is traceable to a component `summary.md`, `analysis.json`, or CSV.
- Artifact paths are listed.
- Dataset path and record count are included.
- Diagnostics are not hidden.
- Figures and tables used in the report are traceable to local artifact paths.
- If the report includes HTML output, all embedded or linked local assets resolve relative to the HTML file or are clearly linked.

## Interpretation

- Observed patterns are separated from interpretations.
- Topic-model/co-word findings are framed as exploratory when appropriate.
- Missing abstracts, authors, institutions, or references are explicitly noted.
- Claims do not exceed the retrieved dataset scope.
- The synthesis connects multiple evidence streams instead of summarizing each analysis component in isolation.
- The report explains disagreements between OpenAlex topics, co-word terms, and modeled topics when those methods differ.

## Structure

- The report uses sections that match the available artifacts.
- Skipped sections are either omitted or explicitly marked unavailable.
- The opening gives a central claim or narrative frame, not only a list of facts.
- Section titles communicate analytical points rather than raw component names whenever possible.
- Analytical modules were used as a planning checklist, not copied mechanically as the final table of contents.
- Dataset and method details are concise and placed where they support interpretation.
- Caveats are integrated into `Scope and Evidence Base` and `Evidence Notes and Reproducibility`, unless a standalone limitations section is clearly warranted.
- The conclusion or synthesis gives useful next analysis steps if gaps remain.

## Visual Evidence

- A visualization inventory was performed before drafting.
- Important available figures/tables are used in the body, not only listed in an appendix.
- Each major figure or table has an interpretive caption.
- Captions state what the visual shows and avoid claiming more than the data supports.
- If no visualizations are available, the report explains whether this is because analysis did not generate them or because only raw tables exist.

## HTML Presentation

Use this checklist when producing HTML:

- The HTML is a static, local file with no required build step.
- The page has a readable title block, narrative lead, analytical sections, figure blocks, and evidence/provenance section.
- Styling is restrained and report-like; it improves scanning without turning the report into a marketing page.
- Tables, metrics, and figure captions are legible on typical desktop and mobile widths.
- Links to artifacts are visible and useful.

## Draft Review

Run this after drafting and before finalizing.

- The opening answers the user's question directly.
- Every section advances the argument; no section exists only because a component exists.
- Claims that began as interpretations are clearly framed as interpretations.
- Figures and tables are explained in prose and captioned with their evidentiary limits.
- The synthesis adds a higher-level reading of the corpus instead of repeating earlier summaries.
- Caveats are visible but do not overwhelm the main narrative.
- The report has been revised after review, not merely checked.
- Markdown, HTML if present, and provenance outputs agree on artifact paths and claims.

## Feedback Loop

If the report quality is limited by missing fields, recommend a concrete re-fetch command shape:

```bash
metasci works search "<query>" --include authors --include references ...
```

Do not invent missing analysis results. Re-run the analysis after re-fetching data.
