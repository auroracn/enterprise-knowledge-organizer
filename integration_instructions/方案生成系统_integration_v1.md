# 方案生成系统(方案生成系统)Dify 知识库接入整改指令 v1

> **给**:方案生成系统 项目的 AI 开发者
> **由**:长风知识整理系统架构师
> **日期**:2026-04-24
> **优先级**:P0(含线上隐患,须在 2 周内完成阶段 1 + 2)
> **项目根**:`D:\aurora\方案生成系统`

---

## 一、背景与缘由(请先读完)

你们维护的 方案生成系统 项目(`D:\aurora\方案生成系统`)通过 `knowledge_base/dify_client.py` 访问 Dify 知识库。近期架构审计发现 **3 个必须修复的问题**,以及**整个公司知识库在长风知识整理系统侧已产出中央目录**,方案生成系统 必须对接。

### 审计发现的 3 个 P0 问题

#### 问题 1(必改):你们调用的是 Dify 调试接口,不是正式接口

- **现状**:`knowledge_base/dify_client.py` 所有检索都打 `POST /v1/datasets/{id}/hit-testing`
- **问题**:`hit-testing` 是 Dify UI 里"命中测试"调试用接口,官方文档不承诺稳定性,升级会变或下线
- **修复**:换成官方 Dataset Retrieval API `POST /v1/datasets/{id}/retrieve`
- **参考实现**:`D:\changfeng\智能标书\yibiao\backend\app\utils\kb_retriever.py`(同团队的 招投标系统 系统已在使用正式接口)

#### 问题 2(必改):`search_all` 是散弹检索,会打爆 Dify

- **现状**:`DifyKnowledgeClient.search_all()` 并发打账户下**所有**知识库
- **问题**:账户下目前有 **18 个**知识库;方案生成系统 里有 30+ 个 agent。如果每个 agent 都调用一次 `search_all`,一次用户请求会发出最多 **30 × 18 = 540 次** Dify 请求。
- **附加问题**:不同库的 score **不可比**(reranking 关闭),按 score 排序实际是按 chunk 长度排 → 新闻库的长 chunk 会稀释业务库
- **修复**:废弃 `search_all`,改为**按角色(role)精准检索**,agent 声明要查哪些库

#### 问题 3(必改):dataset 硬编码 + 库利用率不足

- **现状**:`configs/dify_config.json` 里只映射 4 个 dataset(case/script/product/competitor_library),代码 fallback 里还有硬编码 UUID
- **问题**:账户实际有 **18 个**库,**14 个没暴露给 agent**(政策/政府动态/价格/供应商/联系方式/林业知识等全没用上)
- **修复**:废弃硬编码,统一从**长风知识整理系统产出的中央目录**读取

---

## 二、关键基础事实(必须知道)

### 2.1 中央目录文件(你们要读的权威数据)

两份 YAML 文件由长风知识整理系统维护,**禁止 方案生成系统 复制粘贴或硬编码**,必须每次启动时从文件读:

| 文件 | 绝对路径 | 用途 |
|---|---|---|
| **KB Catalog** | `D:\changfeng\长风知识整理系统\kb_catalog.yaml` | 所有 dataset 的 id/name/tier/roles/metadata_schema |
| **Metadata Schema** | `D:\changfeng\长风知识整理系统\kb_metadata_schema.yaml` | 通用字段 + 各类扩展字段 |

### 2.2 Dify API 事实

- **Base URL**:`https://192.168.110.78:18443/v1`(**内网**,SSL 自签,`verify=False`)
- **单把 API Key**(调试阶段,后续拆分):`dataset-xxxxxxxxxxxxxxxxxxxxxxxxxx`
- **正式检索接口**:`POST /datasets/{dataset_id}/retrieve`
- **请求体格式**(强制使用):
  ```json
  {
    "query": "搜索文本",
    "retrieval_model": {
      "search_method": "semantic_search",
      "reranking_enable": false,
      "top_k": 5,
      "score_threshold_enabled": false
    }
  }
  ```
- **metadata filter 参数**(后续使用):
  ```json
  {
    "query": "...",
    "retrieval_model": {...},
    "metadata_filtering_conditions": {
      "logical_operator": "and",
      "conditions": [
        {"name": "发布日期", "comparison_operator": "after", "value": "2026-03-25"}
      ]
    }
  }
  ```

### 2.3 Tier 与 Role 机制

| Tier | 说明 | Agent 使用模式 |
|---|---|---|
| **A 核心业务层** | 长风产品库/案例库/话术库/价格库/供应商/联系方式/内部资料 | 大部分业务 agent 默认主检索 |
| **B 结构化参考层** | 政策/政府动态/官方指导/林业知识/自动--产品库 | 按主题命中时检索 |
| **C 资讯流层** | 自动--公众号/新闻日报/新闻条目 | **仅情报/新闻类 agent 使用**,必须带时间过滤 |

**role 名称**在 `kb_catalog.yaml` 的 `role_index` 里,下游可稳定依赖。常用 role:
`product`, `supplier_product`, `case`, `solution`, `script`, `pricing`, `bid_response`, `policy`, `official_guide`, `govt_dynamic`, `govt_contact`, `forestry_knowledge`, `internal`, `news_hot`, `detection_report`

---

## 三、改造任务清单(分阶段)

### 阶段 1 · 紧急止血(1 周内)

#### 任务 1.1:API 端点替换 `hit-testing` → `/retrieve`

- 修改 `knowledge_base/dify_client.py` 中所有检索调用
- 原来的 payload:
  ```json
  {"query": "...", "retrieval_model": {"search_method": "hybrid_search", ...}}
  ```
- 改为:
  ```json
  {"query": "...", "retrieval_model": {"search_method": "semantic_search", "reranking_enable": false, "top_k": ..., "score_threshold_enabled": false}}
  ```
- **兼容**:`hit-testing` 返回 `records[0].segment.content`,`/retrieve` 返回 **`records[0].segment.content`**(结构相同,无需改解析逻辑)
- **验收**:调用一次 `/datasets/{id}/retrieve`,HTTP 200,records 非空

#### 任务 1.2:禁用 `search_all` 全库散弹

- **立即**:在 `DifyKnowledgeClient.search_all()` 方法顶部加 `raise DeprecationWarning`
- **立即**:`retrieve(query, dataset_id="all")` 的 "all" 分支改为:**如果传 "all" 则抛异常**,不再转发到 `search_all`
- 替换方案:agent 必须声明要查什么 role,由 role 解析出 dataset_ids,再并发检索(数量可控)
- **验收**:`grep -r "search_all\|dataset_id=\"all\"" D:\aurora\方案生成系统` 无业务代码引用

#### 任务 1.3:加载中央目录

- 新增模块 `knowledge_base/kb_catalog_loader.py`:
  ```python
  import yaml
  from pathlib import Path

  CATALOG_PATH = Path(r"D:\changfeng\长风知识整理系统\kb_catalog.yaml")

  class KBCatalog:
      def __init__(self, catalog_path: Path = CATALOG_PATH):
          self.data = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
      def dataset_ids_by_role(self, role: str) -> list[str]:
          return list(self.data.get("role_index", {}).get(role, []))
      def dataset_ids_by_tier(self, tier: str) -> list[str]:
          return list(self.data.get("tier_index", {}).get(tier, []))
      def dataset_name(self, dataset_id: str) -> str:
          for ds in self.data.get("datasets", []):
              if ds.get("id") == dataset_id:
                  return ds.get("name", "")
          return ""
  ```
- 启动时实例化一次,所有 agent 共享
- **验收**:`KBCatalog().dataset_ids_by_role("product")` 返回长风产品库的 uuid

### 阶段 2 · 角色路由(2 周内)

#### 任务 2.1:新增 `configs/agent_kb_roles.yaml`

为每个 agent 声明要查的 role 列表。建议起点(可调整):

```yaml
# agent_name -> roles
ProductMatchAgent:       [product, supplier_product]
CaseBenchmarkingAgent:   [case, solution]
PainPointStrategicAgent: [case, script]
RelationStrategyAgent:   [script, govt_contact]
GeographicPolicyAgent:   [policy, govt_dynamic, official_guide]
PriceRetrievalAgent:     [pricing, bid_response]
BudgetTierAgent:         [pricing]
ProfitCostAgent:         [pricing]
InvestmentBenefitAgent:  [case, pricing]
TechnicalArchitectureAgent: [product, supplier_product, official_guide]
DetailedPlanAgent:       [case, product, policy]
AppendixAgent:           [policy, internal]
ScraperAgent:            [news_hot]          # 只查资讯层
FactCheckAgent:          [news_hot, policy]
CompetitorAgent:         [supplier_product]  # 竞品库待建,暂用第三方产品库
EvidenceVerificationAgent: [policy, official_guide]
KBRetrievalAgent:        [case, solution, product]
# ... 其他未列出的 agent 不查 KB
```

- **规则**:未在本 yaml 列出的 agent,**禁止调用 Dify**
- **空值**:roles 为空列表 `[]` 表示该 agent 明确不查 KB

#### 任务 2.2:改造 `base_agent.py`

- 从 yaml 读当前 agent 的 roles
- 封装检索方法 `retrieve_kb(query, top_k=5)`,自动按 roles 解析 dataset_ids 并行检索,结果合并
- 原 `self.dify.search/retrieve/search_all` 调用逐一替换

伪代码:
```python
from knowledge_base.kb_catalog_loader import KBCatalog
from knowledge_base.agent_roles_loader import AGENT_ROLES  # 读 yaml

class SalesAgent(AgentBase):
    async def retrieve_kb(self, query: str, top_k: int = 5):
        roles = AGENT_ROLES.get(self.__class__.__name__, [])
        if not roles:
            return []
        catalog = KBCatalog()
        dataset_ids = []
        for r in roles:
            dataset_ids.extend(catalog.dataset_ids_by_role(r))
        dataset_ids = list(dict.fromkeys(dataset_ids))  # 去重
        # 并行打 /retrieve
        tasks = [self.dify.retrieve_by_id(ds_id, query, top_k) for ds_id in dataset_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return self._merge(results, top_k)
```

- **验收**:
  - 一个典型用户请求 Dify 调用次数 ≤ **agent 数 × 平均 role 关联库数(≈2)** = ~60 次(比原 540 次降 90%)
  - 每次调用打日志,可追溯 agent/role/dataset

#### 任务 2.3:资讯类 agent 加时间过滤

对 `roles` 含 `news_hot` 的 agent,检索时 payload 加:
```json
"metadata_filtering_conditions": {
  "logical_operator": "and",
  "conditions": [
    {"name": "发布日期", "comparison_operator": "after", "value": "<30 days ago>"}
  ]
}
```
(暂可先留 TODO,等长风知识整理系统把新闻库发布日期字段补齐后再启用)

---

## 四、边界与禁止事项

| 允许 | 禁止 |
|---|---|
| 读 `kb_catalog.yaml` / `kb_metadata_schema.yaml` | 硬编码 dataset UUID 在代码里 |
| 读 `agent_kb_roles.yaml` | 硬编码 role→dataset 映射 |
| 调用 `/datasets/{id}/retrieve` | 调用 `/datasets/{id}/hit-testing` |
| 按 role 并行检索(数量有限) | 全库 `search_all` 散弹 |
| 反向飞轮回填案例库(经审核闸门) | 直接写入业务库,绕过审核 |
| 继续用单把 `dataset-xxxxxxxxxxxxxxxxxxxxxxxxxx` key(调试阶段) | 把 key 硬编码在非 config 文件里 |

---

## 五、验收标准

阶段 1 完成标志:
- [ ] `grep hit-testing` 在 方案生成系统 代码里无业务调用
- [ ] `search_all` 被废弃或明确抛异常
- [ ] `kb_catalog_loader.py` 能加载中央目录并按 role 返回正确 dataset_ids
- [ ] 一次完整 `sales_flow` 运行不报错

阶段 2 完成标志:
- [ ] `agent_kb_roles.yaml` 存在,覆盖所有活跃 agent
- [ ] `base_agent.retrieve_kb` 替换原有散弹调用
- [ ] 单次用户请求 Dify 调用次数日志可统计,≤100 次
- [ ] 资讯类 agent 调用时带(或预留)时间过滤

---

## 六、问题反馈

改造中遇到任何问题,反馈给长风知识整理系统维护方(问项目所有者要联系方式),特别是:
- 中央目录字段需要新增(比如你们需要新的 role)
- Dify API 行为与文档不一致
- metadata schema 需要新字段

**禁止擅自修改** `D:\changfeng\长风知识整理系统\*.yaml`,必须由 KB 维护方统一更新。
