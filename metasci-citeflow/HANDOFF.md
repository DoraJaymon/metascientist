# CiteFlow 移植交接文档

> 状态：核心算法链路已跑通，**未提交**（在 `main` 分支）。
> 计划文档：`/home/dell/.claude/plans/warm-sleeping-toast.md`

## 一句话

把 AcaDeepR 的 CiteFlow 深度检索算法，以「原子工具 + 可插拔配方」的形态复现到 metascientist，
既能忠实重跑原算法做基线，也能让 LLM 在流程中做更多决策、支撑后续方法迭代。

---

## 1. 现状

**新包 `metasci-citeflow/`**，存储层复用 `metasci_universe.memory.curalib`。
**27 个 `cf.*` 工具**，`ms.list_tools()` 可见。**193（citeflow）+ 75（universe）测试全绿，全 mock 不打网络。**

完整链路已通：
```
cf.query.analyze → cf.papers.search → cf.citations.co_cite → cf.citations.expand_refs_guided
  → cf.seeds.select_refs → cf.citations.fetch_forward
  → [cf.seeds.select_citations → cf.store.distributions → cf.citations.decide_params
     → cf.citations.fetch_forward] × N
  → cf.store.autoscore → cf.papers.filter → cf.store.rank → cf.eval.score
```

**四个 LLM 决策点全部移植**（prompt yaml 与 AcaDeepR 逐字节一致，有 `test_prompts_fidelity.py` 守着）：
query analyzer（slot-based 三轮）、seed selector、relevance judge、citation params decider。

### 文件地图
```
src/metasci_citeflow/
  profiles.py      三套已验证参数预设 + 点号覆盖 resolve("acadeepr-run1", **{"refs.top_k_co_cited":10})
  session.py       落盘 session：store.json + session.json(ledger)，每次变更自动保存
  deps.py          CiteFlowDeps 注入 llm/s2/openalex/reranker/sleep —— 测试全靠这个 seam
  registry.py      27 个工具，先 pydantic 校验后分发
  llm/             四个决策点 + 四个 prompt yaml（勿改，改了 fidelity 测试会红）
  providers/       s2_search.py（S2 检索）、openalex_graph.py（引文图，建在 OpenAlexAPIProvider 上）
  graph/           cocitation.py（共被引/in-domain）、seeder.py（双策略选种子 + 引用预算）
  scoring/         reranker.py（BGE cross-encoder）、keywords.py（noisy-OR）、autoscore.py
  eval/            benchmark.py + metrics.py（移植自 PaperRankingEvaluator）
  filters.py  ranking.py  papers.py  schemas.py  errors.py
```

### 快速上手
```bash
cd metasci-citeflow && python3 -m pytest -q          # 193 passed

# 跑一个 query 的完整 Phase 1 + 评估
python3 dev_scripts/citeflow_batch.py --queries semantic_5

PYTHONPATH=metasci-universe/src:metasci-citeflow/src python3 -c "
import metasci_universe as ms
print([t for t in ms.list_tools() if t.startswith('cf.')])"
```
`.env` 已备齐：`OPENAI_API_KEY` / `OPENAI_API_BASE_URL` / `OPENALEX_EMAIL` / `S2_API_KEY` / `RERANKER_API_TOKEN`。
模型用 `gemini-2.5-flash`（网关是 chatanywhere，**没有** `gemini-flash-latest`）。

---

## 2. 修好的三个移植回归（都有实测证据）

| # | 问题 | 修复后 |
|---|---|---|
| 1 | S2 结果永远没有 `openalex_id` → 共被引/选种子/引文扩展全部静默失效 | OpenAlex 覆盖率 **95%**（DOI→MAG→title 三级解析）|
| 2 | `_parse_work` 硬编码 `abstract=""` | 摘要覆盖率 **89%**（从 `abstract_inverted_index` 重建）|
| 3 | 前向引文单页封顶 200、从不翻页 | 单个种子 200 → **326**（cursor 全量分页 + 服务端过滤）|

**注意我早期的一个错误判断**：我曾说回归#1 是"`_parse_paper` 漏读 `externalIds.OpenAlex`"。
**S2 根本不返回 OpenAlex id**（实测 externalIds 只有 ArXiv/ACL/DBLP/MAG/DOI/CorpusId）。
真实原因是 DOI→OpenAlex 的**解析步骤**没移植。

顺带修的 curalib bug（在 metasci-universe）：`save_to_json` 不写 `_api_index` 但 `load_from_json` 读它；
以及只有 openalex_id 的论文 `record.corpus_id` 为空但字典键不为空。都有回归测试。

---

## 3. 指标现状（semantic_5，GT=2）

| | store_cov | recall@100 |
|---|---|---|
| 原版完整流水线 | 50% | **0.00** |
| 我们 Phase 1（无前向循环） | 50% | **0.50** |
| 我们 + 完整 3 轮循环 | 50% | **0.00** |

Phase 1 四个 query 基线（`metasci_outputs/citeflow/batch_report.json`）：
```
semantic_144  GT=26  6/26=23%   (原版 7/15=47%，⚠️ benchmark 被改过，GT 15→26，不可比)
semantic_187  GT=7   0/7 =0%    (原版也是 0/7，非我方 bug)
semantic_5    GT=2   1/2 =50%   (原版 1/2，打平)
semantic_12   GT=1   1/1 =100%  (原版 1/1，打平)
```

---

## 4. 最重要的未决问题

### ⚠️ 前向扩展在 semantic_5 上**降低**最终指标
循环机制完全正常（3 轮、每轮选种子、参数决策 `clamped=False` 合理、store 566→1185），
但 SummaC 从第 80 位被 619 篇新论文挤到 100 名开外，recall@100 从 0.50 → 0.00。
**原版完整流水线同样是 0.00**，说明这是算法性质不是移植 bug。

**下一步第一件事**：拿 **semantic_144（GT=26）** 跑循环前后对比。
GT=2 时 recall@100 在 0/0.5 间跳变，噪声太大；GT=26 才能判断广度扩展到底值不值。

### 其他待办
- **#11 semantic_187 零种子**：强桶只有 13（其他 99-222），两个策略都没选出种子。
  怀疑是 profile 把 `init_search.year=(2015,2023)` 写死，而 GT 是 2024 年论文。
  验证方法：`resolve("acadeepr-run1", **{"init_search.year": (2015, 2025)})`。
- **#10 OpenAlex 死号**：282 个共被引里 50 个（含共被引最高的 18 次那个）返回 404，
  取不到元数据 → 进不了种子池。**成因未证实**（我曾说是"合并残留"，那个推断基于一次错误的
  `title.search` 模糊匹配，已撤回）。AcaDeepR 半年前的存档里同样是空壳记录，**旧项目也有，只是没报告过**。
  建议等能量化再决定修不修。
- **skill 文件一个没写**。且旧 `metasci-skills/skills/metasci-deepsearch/SKILL.md` 的 description
  自称 "the CiteFlow algorithm"，不处理会抢路由。
- 旧 `metasci-deepsearch/` 仍在，作只读参照，最后删。

---

## 5. 接手须知（踩过的坑）

1. **`.env` 结尾没换行**——直接 `>>` 追加会拼到上一行。我这么干过一次，把 `OPENREVIEW_PASSWORD` 弄坏了。
2. **测试约定**：`def test_x(): asyncio.run(_test_x())` + 手写 `Fake*` 构造注入。
   仓库虽声明 pytest-asyncio 但**全仓库零使用**，别引入。
3. **循环导入**：metasci-universe 的 registry 对 `cf.*` 的注册必须**惰性**（`_register_citeflow_tools()`
   在 `list_tools`/`_get_tool` 里调用，不能在模块顶层），否则和 citeflow 反向 import universe 打架。
4. **不要"统一"两个排序函数的返回顺序**：`rank_by_quality` 返回 `(papers, ids)`，
   `rank_by_importance` 返回 `(ids, papers)`，原项目两处调用各自依赖不同顺序且都是对的。
5. **`mid_sort_weights` 的空 dict 是原项目 run_my_3 的真实行为**，已用 `PASSTHROUGH` 显式命名，别当 bug 修。
6. **复现基线必须 `cf.query.analyze(from_yaml=...)`**。实时分析会选出不同的 `research_task` 槽位
   （实测：原版 `("alignment","factual")` vs 实时 `("summarization","machine-generated")`），
   直接改变检索锚点。
7. **不要移植** `ds.papers.judge`（逐篇 0-1 打分）、`find_seed_candidates`——
   都是上次移植时的发明，CiteFlow 里没有，会把 agent 带偏。

---

## 6. 建议顺序

1. semantic_144 跑循环前后对比 → 判断前向扩展价值（**最要紧**）
2. 按结论调 profile 或排序权重；semantic_187 试放宽年份
3. 写 skill：`metasci-skills/skills/metasci-citeflow/`
   （`references/recipes/citeflow-faithful.md` + `adaptive-expand.md`、`profiles.md`、`signals.md`），
   更新 `metasci-skills/AGENTS.md` 路由，退休 deepsearch skill
4. Phase 4 三套权重对比排序 + `cf.run.manifest`/`cf.run.compare` 实验工具
5. 提交（先开分支，`main` 是默认分支）
