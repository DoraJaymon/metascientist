# 学者个人主页 URL 收集方案

目标的第一阶段不是读取网页内容，而是尽可能收集可归属到具体学者实体的个人主页 URL。建议把结构化、高精度来源放在前面，把搜索引擎作为补全渠道。

## 推荐优先级

### 1. CSRankings

适用范围：计算机科学、AI、ML、NLP、CV、系统、数据库、安全等方向。

优点：

- 直接维护 faculty 名单、机构和 homepage URL。
- 数据格式简单，适合第一批高质量种子数据。
- 人工维护，误匹配率较低。

局限：

- 学科覆盖窄，主要是 CS。
- 更多覆盖 faculty，对博士后、学生、工业研究员覆盖有限。

建议用法：

- 作为计算机领域个人主页数据库的第一批种子。
- 与 DBLP、OpenReview、OpenAlex 作者实体做后续对齐。

### 2. ORCID

适用范围：跨学科研究者。

优点：

- ORCID iD 是强身份锚点。
- ORCID record 中的 `researcher-urls` 往往包含个人主页、实验室主页、机构主页、GitHub 等。
- 适合从 OpenAlex、Crossref、Semantic Scholar 等来源获得 ORCID 后进行补全。

局限：

- 很多学者没有填写 researcher URLs。
- URL 类型混杂，需要区分 personal homepage、institution profile、social/profile links。

建议用法：

- 先用 OpenAlex、Crossref、论文元数据或作者表获取 ORCID。
- 批量查询 ORCID Public API 的 researcher URLs。
- 将结果作为高置信候选，但仍保留 URL 类型和来源。

### 3. DBLP

适用范围：计算机领域。

优点：

- 对 CS 学者覆盖非常好。
- DBLP RDF 中包含 `homepage`、`primaryHomepage` 等信息。
- 与论文、作者 disambiguation 关系紧密。

局限：

- 主要覆盖 CS。
- 并非所有作者都有主页字段。

### 4. OpenReview

适用范围：AI/ML/NLP/CV 社区。

优点：

- Profile 中可能有 homepage、Google Scholar、DBLP、GitHub 等字段。
- 对 ICLR、NeurIPS、ICML 相关社区有价值。

局限：

- 覆盖偏 ML 会议生态。
- Profile 字段完整度不稳定。

### 5. Wikidata

适用范围：知名学者、跨学科作者。

优点：

- 可以通过 `official website`、ORCID、DBLP、Google Scholar ID 等属性拿到主页或外部 ID。
- 适合做高精度补充和实体对齐。

局限：

- 覆盖不均匀，长尾学者少。

### 6. OpenAlex / Semantic Scholar

适用范围：大规模作者种子和身份对齐。

优点：

- 覆盖作者量大。
- 可提供论文、机构、ORCID、外部 ID 等上下文。
- 适合先构建作者实体池，再去其他渠道补主页。

局限：

- 通常不直接提供个人主页。
- 更适合作为上游作者和 ORCID/机构信息来源。

### 7. 机构、院系和实验室目录

适用范围：当前 faculty、研究组成员、特定机构。

优点：

- 能发现很多没有 ORCID/DBLP homepage 的当前主页。
- 对机构 profile 和个人主页都有帮助。

局限：

- 页面结构不统一。
- 需要做姓名、机构、职位、研究方向匹配。

### 8. 搜索引擎补全

适用范围：结构化来源缺失后的补全。

优点：

- 召回高，尤其适合 `github.io`、大学个人页、实验室主页。

局限：

- 直接大规模抓 Google 不稳定，也可能违反服务条款。
- 推荐使用合规 SERP API，例如 Google Custom Search API、Bing Web Search API、Brave Search API 或 SerpAPI。
- 同名作者误匹配风险较高。

建议查询模板：

```text
"{author_name}" "{affiliation}" homepage
"{author_name}" "{affiliation}" "personal website"
"{author_name}" site:{institution_domain}
"{author_name}" "github.io"
"{author_name}" "Google Scholar" homepage
```

## 推荐数据模型

建议不要只存一个 URL 字符串，而是保存来源、置信度和归属信息。

```json
{
  "scholar_name": "Diyi Yang",
  "affiliation": "Stanford University",
  "homepage_url": "https://cs.stanford.edu/~diyiy/index.html",
  "url_type": "personal_homepage",
  "source": "csrankings",
  "source_record_id": "Diyi Yang|Stanford University",
  "confidence": 0.95,
  "collected_at": "2026-05-15T12:00:00Z",
  "extra": {
    "orcid": null,
    "dblp": null,
    "note": null
  }
}
```

## 第一阶段实现建议

先实现两个容易落地且价值高的渠道：

1. CSRankings：直接下载并解析 faculty 数据，获得 CS 学者主页。
2. ORCID：给定一批 ORCID iD，批量查询 researcher URLs。

下一阶段再接：

1. 从 OpenAlex 批量获取作者和 ORCID，喂给 ORCID 采集器。
2. 解析 DBLP RDF 或 person pages 中的 homepage。
3. 使用合规 SERP API 对缺失主页的作者做搜索补全。
4. 建立 URL 类型分类和置信度校验。
