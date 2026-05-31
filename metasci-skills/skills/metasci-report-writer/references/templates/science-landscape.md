# Flexible Science Landscape Markdown Template

Use this as a planning scaffold, not a fixed table of contents. Delete the planning notes and unused modules in the final report. The final report should have section titles that fit the user's question and the evidence.

## Plan

Do this before drafting:

- User's main question: {{user_question}}
- Intended reader and use: {{reader_and_use}}
- Required outputs: {{markdown | markdown_and_html | appendix | other}}
- Dominant narrative mode: {{general_landscape | time_focused | multi_venue_comparison | topic_focused | institution_country | citation_reference | author_group | other}}
- Central answer: {{central_answer}}
- Main caveat: {{main_caveat}}

## Evidence Inventory

- Dataset path: `{{dataset_path}}`
- Artifact directory: `{{artifact_directory}}`
- Component summaries: {{component_summaries}}
- Analysis JSON files: {{analysis_json_files}}
- Core visual evidence: {{core_visuals}}
- Core tables: {{core_tables}}
- Diagnostics: {{diagnostics}}
- Missing or weak evidence: {{missing_or_weak_evidence}}

## Narrative Outline

- Selected analytical modules: {{selected_modules}}
- Omitted modules and why: {{omitted_modules}}
- Planned sections:
  - {{section_title}}: claim={{section_claim}}; evidence={{section_evidence}}; visual={{section_visual}}
  - {{section_title}}: claim={{section_claim}}; evidence={{section_evidence}}; visual={{section_visual}}
  - {{section_title}}: claim={{section_claim}}; evidence={{section_evidence}}; visual={{section_visual}}

## Outline Review

Before drafting, check:

- Does the outline answer the user's main question?
- Are section titles reader-facing rather than component names?
- Does each section have evidence?
- Are visuals used inside the body?
- Is there a synthesis step?
- Are unsupported questions moved to evidence notes?

## Final Report Skeleton

```markdown
# {{title}}

{{opening_narrative}}

## {{evidence_base_section_title}}

This report is based on `{{dataset_path}}` ({{record_count}} records, {{year_range}}). The analysis uses {{analysis_components_used}}. Available fields include {{field_coverage_summary}}. Missing or weak fields include {{missing_fields}}.

The figures and tables used below come from `{{artifact_directory}}`. Topic-model and co-word outputs should be read as exploratory signals unless stronger validation is available.

## {{reader_facing_section_title}}

{{section_analysis}}

{{figure_or_table_link_or_embed}}

Caption: {{interpretive_caption}}

## {{reader_facing_section_title}}

{{section_analysis}}

{{figure_or_table_link_or_embed}}

Caption: {{interpretive_caption}}

## {{reader_facing_section_title}}

{{section_analysis}}

{{figure_or_table_link_or_embed}}

Caption: {{interpretive_caption}}

## {{synthesis_section_title}}

{{synthesis}}

## {{evidence_notes_section_title}}

{{evidence_notes}}

Diagnostics and caveats:

- {{diagnostic_or_caveat}}
- {{diagnostic_or_caveat}}
- {{diagnostic_or_caveat}}

Artifacts:

- Landscape summary: `{{science_landscape_summary}}`
- Bibliometrics: `{{bibliometrics_artifacts}}`
- Macro/collaboration: `{{macro_artifacts}}`
- Topic landscape: `{{topic_landscape_artifacts}}`
- Citation/reference overview: `{{citation_artifacts}}`
- Visualizations: `{{visualization_artifacts}}`
- Tables: `{{table_artifacts}}`
```

## Module Prompts

Use these prompts to compose the final sections. Do not copy the module names as section titles unless they are the best titles for the report.

Scope and evidence base:

- What corpus is being analyzed, how was it filtered, and what fields are reliable?
- Which analysis components are present?
- Which missing fields limit interpretation?

Temporal evolution:

- Are there phases, accelerations, slowdowns, or turning points?
- Do topic or citation patterns change across periods?
- Which visual best shows the time pattern?

Comparative venue/source structure:

- Are sources or venues playing different roles?
- Do they differ by topic mix, citation profile, openness, geography, or reference base?
- Is the comparison fair given record counts and coverage?

Output and influence structure:

- Is influence broad or concentrated?
- Which papers, authors, sources, or topics dominate?
- Does citation skew change the interpretation of volume?

Topic and intellectual structure:

- What themes recur across OpenAlex topics, co-word terms, and modeled topics?
- Where do methods disagree, and what might that disagreement mean?
- Are there stable cores and fragmented frontiers?

Collaboration geography:

- Which countries or institutions organize the corpus?
- Is the network broad, clustered, or concentrated?
- Does collaboration structure align with topic or citation patterns?

Citation/reference foundation:

- Which works or references form the knowledge base?
- Is the reference base method-heavy, application-heavy, field-specific, or interdisciplinary?
- Are top cited works representative or outliers?

Synthesis:

- What does the combined evidence suggest that no single artifact shows alone?
- Where is the field mature, unsettled, concentrated, fragmented, or under-measured?
- What should be analyzed next if the user wants a deeper report?

Evidence notes and reproducibility:

- Which artifact paths support the claims?
- Which components were unavailable or skipped?
- What concrete re-fetch or re-analysis would improve the report?
