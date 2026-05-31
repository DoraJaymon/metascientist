# Data-Fetch Agent Test Notes

Date: 2026-05-08

## Rename Check

The old `MetaSciReactAgent` module/class was renamed to `DataFetchAgent`:

- module: `metasci_agent.agents.data_fetch_agent`
- class: `DataFetchAgent`
- internal agent name: `metasci_data_fetch_agent`

Package tests passed after the rename:

```bash
python -m pytest
```

Result: `5 passed`.

## Real LLM Client Test

We tested `DataFetchAgent` with a real OpenAI-compatible LLM client loaded from
`/home/dell/Desktop/metascientist/.env`.

Task:

```text
请检索 2025到2026 年 Nature 期刊中关于 large language model 的论文，限制 50 条。
```

The LLM selected this direct MetaSci tool call:

```python
metasci_search_works({
    "query": "large language model",
    "source_name": "Nature",
    "from_year": 2025,
    "to_year": 2026,
    "limit": 50,
    "provider": "auto",
})
```

The run completed successfully:

- data file: `metasci_outputs/works_large-language-model_2c86721b30f5/papers.json`
- metadata file: `metasci_outputs/works_large-language-model_2c86721b30f5/metadata.json`
- returned count: `50`
- filtered total: `148`
- provider: `openalex`
- source resolution: `Nature` resolved to OpenAlex source `S137773608`

## 2026-05-08 本次 Session 测试进度

本次 session 主要验证了 MetaSci 数据检索相关 skills 的加载、命令选择、联网检索、JSON 结果解析和 artifact 路径回传。

### 1. `metasci-data-fetch` skill 加载检查

用户要求使用 `$metasci-data-fetch`，但先不要运行任何检索命令。

已加载的 skill 文件：

```text
/home/dell/.codex/skills/metasci/skills/metasci-data-fetch/SKILL.md
```

确认该 skill 在 Codex / terminal-only 环境中要求优先使用的 CLI 命令为：

```bash
metasci works search
```

同时确认该 skill 还提到用于查看已保存数据集信息的命令模式：

```bash
metasci dataset info
```

在 `metasci-agent` 环境中，该 skill 要求优先使用的 direct tools 为：

- `metasci_search_works`
- `metasci_dataset_info`

本步骤未运行任何检索命令。

### 2. `metasci-author-lookup` 作者候选检索测试

用户要求使用 `metasci-author-lookup`，在 OpenAlex 中搜索 `weinan e` 的作者候选，并返回候选作者 ID、姓名、机构信息、论文数、被引数、diagnostics 和保存的数据文件路径。

已加载的 skill 文件：

```text
/home/dell/.codex/skills/metasci/skills/metasci-author-lookup/SKILL.md
```

执行的 CLI 命令：

```bash
metasci authors search "weinan e" --limit 10 --json
```

第一次在沙箱内执行时因为联网受限失败：

```text
Error: All connection attempts failed
```

随后使用联网权限重新执行，命令成功返回 OpenAlex JSON 结果。

结果摘要：

- provider: `openalex`
- returned count: `10`
- filtered total: `50`
- diagnostics: `[]`
- dataset directory: `metasci_outputs/authors_weinan-e_62e691a54e2f`
- data file: `metasci_outputs/authors_weinan-e_62e691a54e2f/authors.json`
- metadata file: `metasci_outputs/authors_weinan-e_62e691a54e2f/metadata.json`

返回的候选作者包括：

| OpenAlex Author ID | 姓名 | 机构信息 | 论文数 | 被引数 |
|---|---|---|---:|---:|
| `A5071854504` | E Weinan | Princeton University, US, education, `I20089843`, ROR `00hx57361` | 491 | 36733 |
| `A5108166949` | E. Manca | University of California System, US, education, `I2803209242`, ROR `00pjdza24` | 852 | 27490 |
| `A5100441502` | Wei Zhang | South China Agricultural University, CN, education, `I101479585`, ROR `05v9jqt67` | 758 | 21033 |
| `A5112570365` | Weinan E Weinan E | 无 primary affiliation | 7 | 227 |
| `A5089562732` | E Weinan | Peking University, CN, education, `I20231570`, ROR `02v51f717` | 8 | 27 |
| `A5105528283` | W. N. E | Princeton University, US, education, `I20089843`, ROR `00hx57361` | 3 | 345 |
| `A5058289676` | E Weinan | 无 primary affiliation | 1 | 19 |
| `A5077459745` | E Weinan | 无 primary affiliation | 1 | 12 |
| `A5064737794` | E Weinan | Princeton University, US, education, `I20089843`, ROR `00hx57361` | 8 | 9 |
| `A5053351653` | Jiequn Han Weinan E | University of Vienna, AT, education, `I129774422`, ROR `03prydq77` | 1 | 5 |

观察：最可能对应数学家 Weinan E 的主候选是 `A5071854504`，因为其姓名为 `E Weinan`，ORCID 为 `0000-0003-0272-9500`，primary affiliation 为 Princeton University，且论文数和被引数显著高于其他同名或近似候选。

### 3. `metasci-data-fetch` 期刊论文检索测试

用户要求使用 `$metasci-data-fetch`，检索 `2025` 到 `2026` 年 `Journal of Informetrics` 中关于 `LLM` 的论文，限制 `50` 条，并返回 returned count、filtered total、diagnostics 和保存的 `papers.json` 路径。

执行的 CLI 命令：

```bash
metasci works search "LLM" --source-name "Journal of Informetrics" --from-year 2025 --to-year 2026 --limit 50 --json
```

第一次在沙箱内执行时因为联网受限失败：

```text
Error: All connection attempts failed
```

随后使用联网权限重新执行，命令成功返回 OpenAlex JSON 结果，并保存 artifact。

结果摘要：

- provider: `openalex`
- returned count: `4`
- filtered total: `4`
- diagnostics: `sources name 'Journal of Informetrics' resolved to top result 'Journal of Informetrics'; inspect resolved_entities for alternatives.`
- dataset directory: `metasci_outputs/works_llm_887ae4a0c3ed`
- data file: `metasci_outputs/works_llm_887ae4a0c3ed/papers.json`
- metadata file: `metasci_outputs/works_llm_887ae4a0c3ed/metadata.json`

Source name resolution：

| 输入 | 解析到的 Source ID | 解析到的期刊名 |
|---|---|---|
| `Journal of Informetrics` | `S205292342` | Journal of Informetrics |

候选 source：

| Source ID | 名称 | works_count | cited_by_count |
|---|---|---:|---:|
| `S205292342` | Journal of Informetrics | 1685 | 81356 |
| `S4387285432` | Journal of Data Science Informetrics and Citation Studies | 133 | 147 |
| `S4210236642` | ARID International Journal of Informetrics | 63 | 3 |

返回的 4 篇论文包括：

| OpenAlex Work ID | 标题 | 年份 | DOI | 被引数 |
|---|---|---:|---|---:|
| `W4413040352` | Quantifying the impact of digital technology on enterprise processes using LLM-based causal claim networks | 2025 | `10.1016/j.joi.2025.101713` | 2 |
| `W4410219692` | Exploring the change in scientific readability following the release of ChatGPT | 2025 | `10.1016/j.joi.2025.101679` | 1 |
| `W4409186139` | Annotating scientific uncertainty: A comprehensive model using linguistic patterns and comparison with existing approaches | 2025 | `10.1016/j.joi.2025.101661` | 0 |
| `W7143483484` | Relationship between peer review quality and scientific impact: Insights from LLMs-assessed reviews | 2026 | `10.1016/j.joi.2026.101801` | 0 |

### 当前结论

截至 `2026-05-08`，本次 session 已验证：

- `metasci-data-fetch` 的 SKILL.md 可以正常加载，并明确要求在终端环境中使用 `metasci works search`。
- `metasci-author-lookup` 可以通过 `metasci authors search ... --json` 检索 OpenAlex 作者候选，并保存 `authors.json` artifact。
- `metasci-data-fetch` 可以通过 `metasci works search ... --json` 检索 OpenAlex works 数据，并保存 `papers.json` artifact。
- 在当前环境中，MetaSci/OpenAlex 检索需要联网权限；沙箱内直接运行会出现 `All connection attempts failed`。
- 两次成功检索都能从 JSON envelope 中读取 `metadata.returned_count`、`metadata.filtered_total`、`diagnostics` 和 `artifacts.data_file`。
