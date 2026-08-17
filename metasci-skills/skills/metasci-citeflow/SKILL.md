---
name: metasci-citeflow
description: >
  Agent-driven deep literature discovery. The agent reads problem seeds (research
  hypotheses), decomposes them into research directions, and adaptively searches
  using Semantic Scholar and OpenAlex. Decisions (which queries, which engine,
  when to rewrite) are made by the agent based on search result diagnosis.
allowed-tools:
  - Bash(python *)
  - Bash(metasci tools *)
---

# MetaSci CiteFlow — Agent-Driven Literature Discovery

This skill system replaces the old fixed-pipeline `metasci-deepsearch`.
The core principle: **tools execute, agent decides**.

## Skill Phases (each is a separate reference doc)

| Phase | Skill Reference | Agent Decisions |
|---|---|---|
| 1. Query Analysis + Search | `references/query-search.md` | keyword generation, engine choice, quality diagnosis, rewrite |
| 2. Co-citation + Backward Expansion | `references/backward-expansion.md` | hub diagnosis, direction coverage, expansion-source selection |
| 3. Forward Expansion (experimental) | `references/forward-expansion.md` | seed choice, parameters, repeat/stop decision |
| 4. Scoring + Ranking | core `cf.*` tools | score signals, filters, ranking profile |

## Runtime

```python
import asyncio
import metasci_universe as ms

async def main():
    print([t for t in ms.list_tools() if t.startswith("cf.")])

asyncio.run(main())
```

All `cf.*` tools share a **session_id**. Start with `cf.session.open`.

## Design Principles

1. **Agent decides, tools execute** — search/expand/score are atomic tool calls;
   what to search, when to stop, whether to rewrite is the agent's judgment.
2. **Direction coverage over depth** — a hypothesis spans multiple research
   communities; cover each direction before going deep on one.
3. **Diagnose before acting** — after every search call, check top_papers to
   assess quality before deciding the next action.
4. **Budget-aware** — each phase has a tool-call budget. The agent must
   prioritize within that budget, not exhaust all options.

## Current Scope

Phases 1 and 2 are the documented Skill workflow. The underlying forward
expansion tools and an evaluation script exist, but the Phase 3 recipe remains
experimental: it has not yet been established as an always-on default because
more expansion can improve store coverage while degrading the final top-K
ranking. Read `references/forward-expansion.md` before using it.

`metasci-universe.memory.curalib.PaperStore` is the persistent evidence store
behind every session. It owns identity resolution, discovery provenance,
in-domain citation signals, score fields, and final ranking; see
`metasci-universe/docs/curalib-citeflow.md` for its CiteFlow contract.
