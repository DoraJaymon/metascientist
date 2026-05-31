---
name: metasci-report-writer
description: Write and improve reports from MetaSci analysis artifacts. Use when the user asks to turn MetaSci outputs, science-landscape artifacts, bibliometric summaries, topic-landscape results, citation overviews, or macro collaboration analyses into a structured report, brief, appendix, executive summary, or revised higher-quality report. Also use when reviewing report quality, improving structure, checking diagnostics/provenance, or applying report templates.
allowed-tools:
  - Bash(find *)
  - Bash(sed *)
  - Bash(rg *)
  - Bash(python *)
---

# MetaSci Report Writer

Write artifact-grounded analytical reports from MetaSci analysis results. The goal is not to restate every component output mechanically, but to turn the evidence into a coherent science-landscape narrative with clear sections, visual interpretation, and reproducible artifact links. This skill does not fetch data and does not run heavy analysis unless the user explicitly asks; it reads existing analysis outputs and turns them into a structured report.

## Inputs

Accept any of:

- `science_landscape_summary.md`
- component `summary.md` files
- component `analysis.json` files
- CSV tables and HTML figure paths
- PNG/SVG/HTML visualization artifacts
- a `MetaSciResult` JSON envelope
- a saved dataset path plus analysis artifact directory

If artifacts are missing, ask `metasci-analysis` to run the appropriate analysis
or the `science_landscape` workflow first.

## Report Types

Choose the smallest report type that answers the user:

| User asks for | Report type |
| --- | --- |
| "summarize the landscape" | `science-landscape-brief` |
| "topic trend report" | `topic-trend-report` |
| "author impact report" | `author-impact-brief` |
| "conference/year analysis" | `conference-landscape-brief` |
| "executive summary" | `executive-brief` |
| "appendix / reproducibility details" | `technical-appendix` |
| "improve this report" | `quality-review-and-revision` |

## Science Landscape Report Design

Do not write a full paper unless requested. The default should be a compact but narrative analytical report: start from the user's main question, select the relevant analytical modules, then organize the evidence into report sections that fit the case. Do not mirror the raw analysis component list (`Dataset`, `Citation Profile`, `Topic`, `Interpretation`, `Limitations`) unless that is genuinely the clearest structure.

Modules are the behind-the-scenes checklist; sections are the reader-facing story. Modules can be relatively stable, but final section titles and ordering must remain flexible.

Common analytical modules:

- Scope and evidence base: corpus, filters, record count, years, available fields, missing fields, and analysis components used.
- Temporal evolution: growth phases, inflection points, rising or declining topics, and period contrasts.
- Comparative venue/source structure: differences between journals, conferences, sources, publishers, or user-defined groups.
- Output and influence structure: publication volume, citation skew, top papers, sources, authors, and open-access share when available.
- Topic and intellectual structure: OpenAlex topics, co-word terms, modeled topics, and where methods agree or disagree.
- Collaboration geography: countries, institutions, collaboration networks, and concentration patterns.
- Citation/reference foundation: top cited papers, reference frequency, knowledge base, and influence concentration.
- Evidence notes and reproducibility: diagnostics, missing fields, skipped components, artifact paths, and concrete next steps.
- Synthesis: what the combined evidence suggests about trajectory, maturity, fragmentation, gaps, or opportunities.

Choose only the modules that serve the user's request and available artifacts. Omit irrelevant modules. If a module is important but unsupported by data, mention the gap briefly in evidence notes rather than forcing a thin section.

Evidence selection should be question-driven. Do not treat the artifact list as
the report outline. Foreground the few artifacts that materially change the
answer to the user's question; demote routine, redundant, or low-relevance
outputs to the evidence notes or artifact index. For fixed-scope corpora, such
as one source, one venue, or one narrow year range, skip metrics that merely
restate the sampling design unless they explain a caveat.

## Choosing the Narrative

First infer the report's dominant question:

- General landscape: What is this corpus made of, where is it concentrated, and what is changing?
- Time-focused landscape: What phases or turning points appear over time?
- Multi-venue or multi-source comparison: How do venues/sources differ in role, topic mix, influence, and evidence base?
- Topic-focused landscape: What themes organize the field, and how stable are they across methods?
- Institution/country landscape: Who produces the work, where are collaboration clusters, and how concentrated is the field?
- Citation/reference landscape: Which works form the knowledge base, and how concentrated is influence?
- Author/group landscape: What output arc, topic footprint, collaboration pattern, and influence structure define the entity?

Then create reader-facing sections that express analytical claims. Prefer section titles like:

- `A fast-growing corpus with influence concentrated in a few papers`
- `The journals share a problem space but split by methodological role`
- `The topic map is stable at the top and fragmented at the frontier`
- `Collaboration is broad geographically but narrow institutionally`
- `Reference patterns point to a methods-heavy knowledge base`

Do not use these examples unless they match the evidence. They illustrate style: titles should communicate the point, not the data type.

## Minimal Report Spine

Most reports still need a small spine:

- Opening: central answer to the user's question and the strongest caveat.
- Evidence base: concise data boundary and artifact inventory.
- Flexible analytical sections: selected modules reorganized into a coherent story.
- Synthesis: what the evidence means when read together.
- Evidence notes and reproducibility: diagnostics, missing evidence, artifact paths, and next steps.

This spine is not a fixed table of contents. Rename, merge, reorder, or shorten sections to fit the user request.

## Visualization Rules

Before drafting, build a visualization inventory:

- Search the artifact directory for `.html`, `.png`, `.svg`, `.jpg`, `.jpeg`, and `.csv` files.
- Inspect component `analysis.json` files for `figures`, `tables`, or exported visualization references.
- Identify the figures or tables that best support the report's argument. A short brief may need only one or two strong visuals; a broader landscape may need several. Prefer charts that show time trends, concentration, topic structure, collaboration geography, citation skew, or reference foundations.
- If no visual artifacts exist, say whether the analysis stage did not generate them or whether only raw tables are available. Recommend the relevant `metasci-analysis` workflow when useful.

Use visualizations in the body of the report:

- Do not leave figures only in the artifact appendix.
- Every major visual should appear near the analysis it supports.
- Add a short interpretive caption for each visual: what pattern the reader should notice, what the evidence does not prove, and any data caveat.
- In Markdown, embed image files when available and link HTML figures or CSV tables. If only an HTML figure exists, link it prominently and summarize its visual pattern in the text.
- In HTML output, embed or iframe local HTML figures when practical; otherwise provide a styled figure link with the same caption.

## HTML Output

When the user asks for a polished report, a shareable report, visual presentation, or explicitly asks for HTML, produce both Markdown and static HTML:

```text
outputs/<slug>-science-landscape.md
outputs/<slug>-science-landscape.html
outputs/<slug>.provenance.md
```

The HTML report is not a raw Markdown conversion. It should be a readable static analysis page with:

- a title block and short narrative lead;
- a compact metrics strip when metrics are available;
- sectioned analytical story blocks;
- embedded or linked figures with captions;
- a concise evidence/reproducibility section;
- restrained academic/report styling that works locally without a build step.

Use `references/templates/science-landscape-html.md` when creating the HTML version.

## Workflow

Use a writing loop rather than drafting directly from artifacts:

1. Plan.
   - Clarify the user's main question, intended reader, report type, desired format, and whether HTML is needed.
   - Identify the likely narrative mode: general landscape, time-focused, multi-venue/source comparison, topic-focused, institution/country, citation/reference, author/group, or other.
2. Evidence inventory.
   - Locate artifacts. Prefer `science_landscape_summary.md` as the starting point.
   - Read component summaries first. Read `analysis.json` only for exact values needed in the report.
   - Build a visualization inventory and decide which figures/tables should drive the analysis.
   - Note missing fields, skipped components, weak diagnostics, and unsupported but important questions.
3. Narrative outline.
   - Select relevant analytical modules.
   - Build a reader-facing outline with one central claim, flexible section titles, and the artifact/figure evidence each section uses.
   - Do not draft prose yet.
4. Outline review.
   - Check whether the outline answers the user's question, avoids component-list structure, uses visual evidence in the body, and includes synthesis.
   - Revise the outline before drafting if sections are generic, unsupported, repetitive, or too thin.
5. Draft.
   - Write the report from the reviewed outline.
   - Integrate figure/table links or embeds near the relevant discussion.
   - Add interpretive captions and keep caveats close to the claims they qualify.
6. Draft review.
   - Run a quality pass using `references/quality-rubric.md`.
   - Check grounding, interpretation, structure, visual evidence, HTML presentation if applicable, and reproducibility.
7. Revise.
   - Fix the report based on the draft review. This may require reordering sections, deleting weak sections, strengthening captions, softening claims, or moving caveats.
   - If evidence is insufficient, state the gap and recommend a concrete re-fetch or re-analysis path rather than inventing results.
8. Finalize.
   - Write:

```text
outputs/<slug>-science-landscape.md
outputs/<slug>.provenance.md
```

   - If HTML is requested or beneficial for visual reading, also write:

```text
outputs/<slug>-science-landscape.html
```

   - Use a short slug derived from the topic or dataset directory.

## Quality Rules

- Do not overstate topic-model or co-word outputs as definitive intellectual structure.
- Always report diagnostics and missing-field caveats.
- Separate observed data patterns from interpretation.
- Cite artifact paths, not invented sources.
- If macro/citation/reference artifacts were skipped, say why and how to re-fetch.
- Keep the report useful and sectioned, but do not force either an academic-paper structure or a raw component-by-component structure.
- Prefer caveats integrated into `Scope and Evidence Base` and `Evidence Notes and Reproducibility`; use a standalone `Limitations` section only when it improves clarity.
- Use available visual artifacts as evidence in the body of the report.
- The synthesis should add value beyond summaries: connect output, influence, themes, collaboration, and citation evidence into a defensible interpretation.

## References

Read as needed:

- `references/report-types.md`
- `references/quality-rubric.md`
- `references/templates/science-landscape.md`
- `references/templates/science-landscape-html.md`
