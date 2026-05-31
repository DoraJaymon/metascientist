# Common Mistakes

| Anti-pattern | Correct form |
| --- | --- |
| Running analysis through `metasci tools run ...` by default | Use Python APIs first; CLI is a fallback for terminal-only quick checks |
| Choosing topic modeling backend before inspecting text coverage | Run `ms.analysis.preflight(...)` and use `safe_defaults` |
| Running macro analysis on a dataset without authorship institutions | Re-fetch with `--include authors` or skip macro |
| Treating co-word/topic-model outputs as definitive topics when abstracts are sparse | Report coverage and diagnostics; frame them as exploratory |
| Using embedding/BERTopic backends in a quick agent run | Start with `sklearn_lda`; only use embedding backends when requested or prepared |
| Pasting `analysis.json` into the final answer | Report artifact paths and summarize the important findings |
| Silently dropping missing components in a broad landscape | Report skipped tools and the suggested fetch args |
