# Author Lookup And Disambiguation

Use this reference when the user asks to search for authors, disambiguate a
person name, retrieve an OpenAlex author profile, list authors from a DOI/work,
or fetch works by a selected author.

Inside `metasci-agent`, prefer these direct light-agent tools:

- `metasci_search_authors`
- `metasci_get_author_profile`
- `metasci_get_work_authors`
- `metasci_search_works` with `author_id` after an author candidate is selected

In Codex, Claude Code, or a terminal-only environment, prefer the installed
`metasci` CLI. Fall back to the Python API only when the CLI is unavailable.

## Search Candidate Authors

Use this when the user provides a name and the identity may be ambiguous.

Direct tool:

```json
{
  "tool": "metasci_search_authors",
  "arguments": {
    "name": "Massimo Aria",
    "limit": 5
  }
}
```

CLI:

```bash
metasci authors search "Massimo Aria" --limit 5 --json
```

Report candidate IDs, display names, affiliations when present, works count,
and cited-by count. If the user later asks for papers by a candidate, use the
selected `author_id` with `metasci works search --author-id ...`.

## Author Profile

Use this when the user provides an OpenAlex Author ID or has selected one from
candidate search.

Direct tool:

```json
{
  "tool": "metasci_get_author_profile",
  "arguments": {
    "identifier": "A5069892096",
    "detail_level": "full"
  }
}
```

CLI:

```bash
metasci authors profile A5069892096 --detail-level full --json
```

Use `--detail-level summary` for compact profile output.

## DOI / Work Authorships

Use this when the user asks for authors of a paper by DOI or OpenAlex Work ID.

Direct tool:

```json
{
  "tool": "metasci_get_work_authors",
  "arguments": {
    "identifier": "10.1038/s41597-020-0543-2",
    "all_authors": true
  }
}
```

CLI:

```bash
metasci authors from-work "10.1038/s41597-020-0543-2" --all-authors --json
```

For a specific author position:

```bash
metasci authors from-work "10.1038/s41597-020-0543-2" \
  --author-position 2 \
  --detail-level full \
  --json
```

Avoid asking for all authors with full profiles in one command. First list all
authors in summary form, then profile specific author IDs.

## Python API Fallback

```python
import metasci_universe as ms

print(ms.describe_tool("authors.search"))
result = await ms.run_tool("authors.search", {
    "name": "Massimo Aria",
    "limit": 5,
})
```

## Output Requirements

Return:

1. the exact direct tool call or CLI command used
2. candidate author IDs or profile ID
3. saved artifact path when present
4. any diagnostics from the JSON result
