# Python Patterns

## Readiness then one analysis

```python
import asyncio
import metasci_universe as ms

async def main():
    dataset = "metasci_outputs/.../papers.json"
    rec = await ms.analysis.preflight(dataset, intent="topic_landscape")
    defaults = rec.data["safe_defaults"]

    result = await ms.analysis.topic_landscape(
        dataset,
        text_backend=defaults["text_backend"],
        modeling_backend=defaults["modeling_backend"],
        methods=defaults["topic_landscape_methods"],
        min_count=defaults["min_count"],
        nr_topics=defaults["nr_topics"],
        max_docs=defaults["max_docs"],
        output_dir="metasci_outputs/analysis/topic_landscape",
    )
    print(result.summary())
    print(result.artifacts)

asyncio.run(main())
```

## Broad saved-dataset landscape

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
    print(result.artifacts["summary_md"])

asyncio.run(main())
```

## In-memory dataset

The analysis loaders accept saved paths, `SavedDataset`, and in-memory records in most lower-level helpers, but public Pydantic schemas still expect paths for registered tools. Prefer saved dataset paths for skill workflows so artifacts can record provenance.

## Agent discovery

```python
import metasci_universe as ms

for name in ms.list_tools():
    if name.startswith("analysis."):
        print(name, ms.describe_tool(name)["description"])
```
