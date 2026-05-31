# Report Types

## science-landscape-brief

Use for broad MetaSci analyses over a works dataset. This is the default report type. It should read like a short analytical essay grounded in artifacts, not like a concatenation of component summaries.

Use the minimal report spine, then choose modules that fit the user's emphasis. The final section order is flexible.

Useful modules:

- scope and evidence base;
- temporal evolution;
- output and influence structure;
- topic and intellectual structure;
- collaboration geography;
- citation/reference foundation;
- comparative venue/source structure, when the corpus includes meaningful groups;
- synthesis and evidence notes.

Avoid section titles that simply repeat component names unless the report is purely technical. Prefer titles that describe the analytical point each section makes.

## topic-trend-report

Use when topic evolution, co-word terms, or modeled topics are central. The report should compare the topic signals instead of treating one method as the truth.

Useful modules:

- topic thesis or central movement;
- evidence base: topic methods, text fields, and coverage;
- stable themes;
- emerging or declining themes;
- method comparison across OpenAlex topics, co-word analysis, and topic modeling;
- figure-led discussion of time series or topic composition;
- synthesis and caveats.

Final sections may be chronological, thematic, method-comparison-oriented, or organized around turning points.

## author-impact-brief

Use for author-centered datasets.

Useful modules:

- Author identity and corpus boundary.
- Career/output arc, using time-series evidence where available.
- Influence structure: citation profile, top works, sources, and concentration.
- Intellectual footprint: topics, terms, methods, or problem areas.
- Collaboration/institutional pattern when available.
- Synthesis: how the author's contribution is positioned within the retrieved corpus.
- Evidence notes and artifacts.

## conference-landscape-brief

Use for venue/year slices. Keep the venue/year constraint visible throughout; do not generalize beyond the slice.

Useful modules:

- Venue/year scope and corpus boundary.
- Main thematic pattern in the accepted/proceedings papers.
- Concentrations or absences: topics, methods, institutions, countries, or sources that dominate or are missing.
- Early citation or reference signals if available.
- Synthesis: what this slice says about the venue at that moment.
- Evidence notes and artifacts.

If comparing multiple venues or years, organize the report around contrasts and changes rather than writing one mini-report per venue unless the user explicitly asks for that.

## executive-brief

Use when the user wants a short decision-facing summary. Keep it under 1-2 pages, but preserve a narrative lead rather than only bullets.

Useful modules:

- One-paragraph bottom line.
- 3-5 key findings with evidence references.
- Implications for the user's decision, research direction, or next analysis.
- Caveats and artifact links.

## technical-appendix

Use when the user needs reproducibility details:

- Dataset Path and Inputs
- Analysis Calls
- Parameters and Backends
- Diagnostics
- Artifact Inventory
- Known Limitations

This is the only report type where a component-by-component structure is usually appropriate.

## quality-review-and-revision

Use when improving an existing report. Do not merely polish prose. Diagnose why the report is weak, then revise the structure and evidence use.

Revision steps:

- Identify whether the current report is component-driven, under-interpreted, missing figures, over-claiming, or hiding caveats.
- Infer the user's likely main question and build a new narrative outline before rewriting.
- Move dataset/method details into a concise evidence-base section.
- Integrate available visualizations into the body.
- Replace generic `Interpretation` and `Limitations` sections with targeted synthesis and evidence notes unless the user requests otherwise.
- Preserve traceability to artifact paths.
