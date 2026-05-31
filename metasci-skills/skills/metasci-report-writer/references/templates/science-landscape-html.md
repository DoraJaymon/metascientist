# Static HTML Science Landscape Template

Use this template when producing `outputs/<slug>-science-landscape.html`. The HTML should be a hand-finished static report, not an automatic dump of Markdown. Keep all paths relative when possible so the file can be opened locally. Treat the section blocks as reusable layout pieces; delete, duplicate, reorder, and rename them to fit the user's question.

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{title}} Science Landscape</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f7f4;
      --paper: #ffffff;
      --ink: #1f2933;
      --muted: #667085;
      --rule: #d9dee7;
      --accent: #2f6f73;
      --accent-2: #8a5a44;
      --soft: #eef4f3;
      --soft-2: #f5eee9;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 16px/1.65 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    main {
      max-width: 1120px;
      margin: 0 auto;
      padding: 32px 20px 56px;
    }

    header {
      border-bottom: 1px solid var(--rule);
      padding: 28px 0 24px;
      margin-bottom: 28px;
    }

    .kicker {
      color: var(--accent);
      font-size: 0.82rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    h1 {
      max-width: 900px;
      margin: 8px 0 14px;
      font-size: clamp(2rem, 4vw, 4rem);
      line-height: 1.05;
      letter-spacing: 0;
    }

    .lead {
      max-width: 860px;
      color: #344054;
      font-size: 1.14rem;
    }

    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 18px;
      color: var(--muted);
      font-size: 0.92rem;
    }

    .pill {
      border: 1px solid var(--rule);
      border-radius: 999px;
      background: var(--paper);
      padding: 5px 10px;
    }

    .metrics {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 12px;
      margin: 26px 0 32px;
    }

    .metric {
      border-top: 3px solid var(--accent);
      background: var(--paper);
      padding: 14px 16px;
      box-shadow: 0 1px 2px rgba(16, 24, 40, 0.06);
    }

    .metric strong {
      display: block;
      font-size: 1.55rem;
      line-height: 1.2;
    }

    .metric span {
      color: var(--muted);
      font-size: 0.9rem;
    }

    section {
      margin: 34px 0;
      padding-top: 4px;
    }

    h2 {
      max-width: 850px;
      margin: 0 0 12px;
      font-size: 1.55rem;
      line-height: 1.25;
      letter-spacing: 0;
    }

    p {
      max-width: 850px;
      margin: 0 0 14px;
    }

    .section-grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(280px, 420px);
      gap: 24px;
      align-items: start;
    }

    figure {
      margin: 4px 0 0;
      background: var(--paper);
      border: 1px solid var(--rule);
      padding: 12px;
    }

    figure img,
    figure iframe {
      display: block;
      width: 100%;
      max-width: 100%;
      border: 0;
    }

    figure iframe {
      min-height: 340px;
    }

    figcaption {
      margin-top: 10px;
      color: var(--muted);
      font-size: 0.92rem;
    }

    .callout {
      max-width: 900px;
      border-left: 4px solid var(--accent-2);
      background: var(--soft-2);
      padding: 14px 18px;
    }

    .evidence {
      background: var(--soft);
      border-top: 1px solid var(--rule);
      border-bottom: 1px solid var(--rule);
      padding: 18px;
    }

    ul {
      max-width: 850px;
      padding-left: 1.2rem;
    }

    a {
      color: #1b5f73;
    }

    code {
      background: rgba(31, 41, 51, 0.08);
      border-radius: 4px;
      padding: 0.12rem 0.28rem;
      font-size: 0.92em;
    }

    @media (max-width: 820px) {
      main {
        padding: 22px 16px 44px;
      }

      .section-grid {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div class="kicker">MetaSci Science Landscape</div>
      <h1>{{title}}</h1>
      <p class="lead">{{lead_narrative}}</p>
      <div class="meta">
        <span class="pill">Dataset: <code>{{dataset_path}}</code></span>
        <span class="pill">{{record_count}} records</span>
        <span class="pill">{{year_range}}</span>
      </div>
    </header>

    <!-- Optional: delete the metrics strip when metrics do not help the report. -->
    <div class="metrics" aria-label="Key metrics">
      <div class="metric"><strong>{{metric_1_value}}</strong><span>{{metric_1_label}}</span></div>
      <div class="metric"><strong>{{metric_2_value}}</strong><span>{{metric_2_label}}</span></div>
      <div class="metric"><strong>{{metric_3_value}}</strong><span>{{metric_3_label}}</span></div>
      <div class="metric"><strong>{{metric_4_value}}</strong><span>{{metric_4_label}}</span></div>
    </div>

    <section>
      <h2>Scope and Evidence Base</h2>
      <p>{{scope_and_evidence}}</p>
      <p>{{field_coverage_and_caveats}}</p>
    </section>

    <!-- Reusable analytical section block. Duplicate, delete, reorder, or rename. -->
    <section>
      <div class="section-grid">
        <div>
          <h2>{{reader_facing_section_title}}</h2>
          <p>{{section_analysis_para_1}}</p>
          <p>{{section_analysis_para_2}}</p>
        </div>
        <figure>
          {{visual_embed_or_link}}
          <figcaption>{{interpretive_caption}}</figcaption>
        </figure>
      </div>
    </section>

    <!-- Optional second analytical section block. -->
    <section>
      <div class="section-grid">
        <div>
          <h2>{{reader_facing_section_title}}</h2>
          <p>{{section_analysis_para_1}}</p>
          <p>{{section_analysis_para_2}}</p>
        </div>
        <figure>
          {{visual_embed_or_link}}
          <figcaption>{{interpretive_caption}}</figcaption>
        </figure>
      </div>
    </section>

    <!-- Optional text-first analytical section for arguments that do not need a side figure. -->
    <section>
      <h2>{{reader_facing_section_title}}</h2>
      <p>{{section_analysis_para_1}}</p>
      <p>{{section_analysis_para_2}}</p>
      <p>{{section_analysis_para_3}}</p>
    </section>

    <section>
      <h2>Synthesis: What Is Changing and What Remains Unclear</h2>
      <div class="callout">{{synthesis_lead}}</div>
      <p>{{synthesis_para_1}}</p>
      <p>{{synthesis_para_2}}</p>
    </section>

    <section class="evidence">
      <h2>Evidence Notes and Reproducibility</h2>
      <p>{{evidence_notes}}</p>
      <ul>
        <li>Landscape summary: <code>{{science_landscape_summary}}</code></li>
        <li>Bibliometrics: <code>{{bibliometrics_artifacts}}</code></li>
        <li>Macro/collaboration: <code>{{macro_artifacts}}</code></li>
        <li>Topic landscape: <code>{{topic_landscape_artifacts}}</code></li>
        <li>Citation/reference overview: <code>{{citation_artifacts}}</code></li>
        <li>Visualizations: <code>{{visualization_artifacts}}</code></li>
      </ul>
    </section>
  </main>
</body>
</html>
```

## HTML Writing Notes

- Delete empty metric cards rather than filling them with placeholders.
- If an HTML figure is safe to display locally, use `<iframe src="{{relative_path}}"></iframe>`. Otherwise use a normal link inside the figure block.
- Duplicate, delete, reorder, or rename analytical section blocks to fit the report. The template does not prescribe the number or order of sections.
- Keep narrative paragraphs concise. HTML improves scanning, but it does not fix weak argument structure.
- Preserve a matching Markdown report for portability and easier review.
