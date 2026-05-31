# Query, Topic, Source, And Entity Selection

Use this reference before writing retrieval commands when the request contains a
mix of keywords, topics, sources, venues, authors, institutions, or years.

## Main Distinctions

- Use `query` for literal terms expected in title/abstract/full text: method
  names, named constructs, exact phrases, software names, benchmarks, datasets,
  or a precise concept the user wants mentioned.
- Use `topic_name` for broad field or discipline constraints: Artificial
  Intelligence, Digital Humanities, Scientometrics, Sociology of Science,
  Quantum Computing.
- Use `source_name` when the user's primary unit is a journal, proceedings,
  repository, or venue in OpenAlex-style metadata.
- Use `venue` / `year` with `metasci conferences papers` when the user asks for
  accepted/proceedings papers from a supported CS conference.
- Use author search/disambiguation before author-constrained paper retrieval
  when the identity is not already clear.
- Use institution constraints when the user asks for works affiliated with an
  institution; report ambiguity diagnostics for institution name resolution.

## Common Choices

| Request shape | Retrieval shape |
| --- | --- |
| "papers mentioning peer review" | `query="peer review"` |
| "AI papers" | `topic_name="Artificial Intelligence"` if the user means the field; `query="AI"` only if the literal abbreviation matters |
| "AI papers mentioning peer review" | `topic_name="Artificial Intelligence"` plus `query="peer review"` |
| "Journal of Informetrics papers, 2022-2023" | `source_name="Journal of Informetrics"`, years |
| "CVPR 2024 accepted papers" | conference connector: `metasci conferences papers cvpr --year 2024 ...` |
| "Massimo Aria's papers" | search/disambiguate author first unless an OpenAlex Author ID is provided |
| "quantum computing papers from USTC" | `query` or `topic_name` plus `institution_name`, depending on whether the phrase is literal or a broad field |

## Coverage Versus Precision

Do not blindly combine every possible constraint. Over-constrained queries can
miss records, especially when one constraint is a broad coverage target and
another is a topical refinement.

- If the goal is complete coverage of a source/venue/year, fetch by
  source/venue/year first, then filter or analyze keywords/topics locally.
- If the goal is a topical corpus across many sources, use `topic_name`,
  `query`, or both.
- If the goal is a field plus a literal concept, combine `topic_name` with
  `query`.
- If a source or author name is ambiguous, resolve the entity first, then fetch
  by ID.

This is a coverage/precision rule, not a DB routing rule. Do not mention or
depend on private database paths.

## Analysis-Ready Retrieval

If the user says the dataset will be used for science landscape, macro analysis,
collaboration analysis, citation/reference analysis, or a report, also read
`refetch-for-analysis.md` before finalizing the command.
