# WoS 和 Scopus 论文元数据获取

本文档记录 MetaDataGet 中 Web of Science 和 Scopus 元数据获取的推荐起点、API/client、认证要求和订阅限制。

## 当前实现

代码位置：

- `MetaDataGet/paper_metadata/wos.py`：Clarivate Web of Science Starter API 客户端。
- `MetaDataGet/paper_metadata/scopus.py`：Elsevier Scopus Search API 和 Abstract Retrieval API 客户端。
- `MetaDataGet/paper_metadata/cli.py`：命令行入口。

运行方式：

```bash
PYTHONPATH=MetaDataGet python3 -m paper_metadata.cli wos search \
  --query 'TS=("machine learning")' \
  --limit 10 \
  --output wos_machine_learning.jsonl

PYTHONPATH=MetaDataGet python3 -m paper_metadata.cli wos doi \
  --doi '10.1038/s41586-020-2649-2' \
  --raw \
  --output wos_doi.json

PYTHONPATH=MetaDataGet python3 -m paper_metadata.cli scopus search \
  --query 'TITLE-ABS-KEY("machine learning")' \
  --count 10 \
  --output scopus_machine_learning.jsonl

PYTHONPATH=MetaDataGet python3 -m paper_metadata.cli scopus doi \
  --doi '10.1038/s41586-020-2649-2' \
  --raw \
  --output scopus_doi.json
```

默认输出为 JSONL，每行一个记录；加 `--raw` 或 `--format json` 可保存原始 API JSON。

## API 和认证要求

| 数据库 | 推荐 API/client | 环境变量 | 是否需要 key/token | 订阅和网络要求 |
| --- | --- | --- | --- | --- |
| Web of Science | Web of Science Starter API；官方 Python client `wosstarter_python_client` 可作为后续增强 | `CLARIVATE_API_KEY` 或 `WOS_API_KEY` | 需要 Clarivate API key | Starter 有试用/基础访问限制；API Expanded 通常需要付费许可，权限取决于机构订阅 |
| Scopus | Elsevier Scopus Search API / Abstract Retrieval API；高阶 Python client 推荐 `pybliometrics` | `ELSEVIER_API_KEY` 或 `SCOPUS_API_KEY`；可选 `ELSEVIER_INST_TOKEN` 或 `SCOPUS_INST_TOKEN` | 需要 Elsevier API key；机构外访问完整权限时常需要 InstToken | 完整 Scopus API 权限通常要求机构订阅，并在机构网络/VPN/IP 范围内访问 |

## 获取凭证

### Web of Science

1. 登录 Clarivate Developer Portal。
2. 创建 application，启用 Web of Science Starter API 或 API Expanded。
3. 获取 API key。
4. 在运行环境设置：

```bash
export CLARIVATE_API_KEY='your-clarivate-api-key'
```

说明：

- Starter API 是最稳的实现起点，适合先打通标题、作者、DOI、来源、出版年等基础元数据。
- 如果需要更完整字段、引用次数、资助、地址和更高配额，应申请 Web of Science API Expanded。

### Scopus

1. 登录 Elsevier Developer Portal。
2. 创建 API key。
3. 确认所在机构是否订阅 Scopus，并通过机构网络/VPN 访问。
4. 如果机构要求 InstToken，在环境中额外设置：

```bash
export ELSEVIER_API_KEY='your-elsevier-api-key'
export ELSEVIER_INST_TOKEN='your-institution-token'
```

说明：

- Elsevier API key 本身不等于 Scopus 全量授权。
- 在非机构网络下，即使 API key 正确，也可能只返回受限字段或返回授权错误。
- `pybliometrics` 是 Scopus Python 生态里最成熟的 client，但仍然使用 Elsevier API key/InstToken，不绕过订阅限制。

## 查询语法

### WoS Starter API

常用：

- 主题检索：`TS=("machine learning")`
- 标题检索：`TI=("large language models")`
- DOI 检索：`DO="10.xxxx/yyyy"`

CLI 示例：

```bash
PYTHONPATH=MetaDataGet python3 -m paper_metadata.cli wos search \
  --query 'TI=("large language models")' \
  --limit 25
```

### Scopus

常用：

- 标题、摘要、关键词：`TITLE-ABS-KEY("machine learning")`
- 标题：`TITLE("large language models")`
- DOI：使用 `scopus doi --doi ...` 走 Abstract Retrieval API。

CLI 示例：

```bash
PYTHONPATH=MetaDataGet python3 -m paper_metadata.cli scopus search \
  --query 'TITLE-ABS-KEY("large language models")' \
  --count 25
```

## 推荐扩展路线

1. 先用当前标准库客户端打通凭证和最小数据流。
2. Scopus 大规模采集时接入 `pybliometrics`，复用其配额、缓存和字段解析。
3. WoS 如需 Expanded 字段，新增 `WebOfScienceExpandedClient`，不要和 Starter API 混在一个方法里。
4. 为两个 provider 增加统一 schema：`title`、`doi`、`year`、`authors`、`source`、`abstract`、`keywords`、`citation_count`、`provider_ids`、`raw`。
5. 加入分页采集、断点续跑、速率限制和错误重试日志。

## 官方入口

- Clarivate Web of Science APIs: https://developer.clarivate.com/apis/wos
- Web of Science Starter API: https://developer.clarivate.com/apis/wos-starter
- Elsevier Scopus APIs: https://dev.elsevier.com/sc_apis.html
- Elsevier API authentication: https://dev.elsevier.com/tecdoc_api_authentication.html
- pybliometrics: https://pybliometrics.readthedocs.io/
