# MetaSci Agent

Thin `light-agent` adapter layer for the `metasci-universe` package.

This package intentionally keeps orchestration separate from data acquisition:

```text
metasci-universe  # deterministic API, schemas, providers, storage, registry
metasci-skills    # thin task rules for Codex/Claude/agents
metasci-agent     # light-agent tools and minimal workflows
```

Current scope:

- direct light-agent tools for the main `metasci_universe` data-fetch APIs:
  `metasci_search_works`, `metasci_get_work`, `metasci_search_authors`,
  `metasci_get_author_profile`, `metasci_get_work_authors`, and
  `metasci_dataset_info`
- one `DataFetchAgent` that loads `metasci-skills` text into the system prompt and
  lets the model choose among those direct tools
- no data-fetcher sub-agent layer in the default phase-1 path
- a tiny CLI for smoke testing adapter calls

Examples:

```bash
metasci-agent tools list --json
metasci-agent tools describe metasci_search_works --json
metasci-agent tools run metasci_search_works '{"query":"science of science","from_year":2024,"limit":5}' --json
metasci-agent react "Get 5 OpenAlex papers about science of science since 2024 and report the saved papers.json path"
```
