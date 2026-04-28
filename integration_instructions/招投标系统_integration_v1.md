# 招投标系统(智能标书系统)Dify 知识库接入整改指令 v1

> **给**:招投标系统 项目的 AI 开发者
> **由**:长风知识整理系统架构师
> **日期**:2026-04-24
> **优先级**:P1(现状可用,本次是**升级**而非救火)
> **项目根**:`D:\changfeng\智能标书\yibiao`

---

## 一、背景(先读完)

你们的 招投标系统 项目目前 Dify 接入**实现质量良好**:
- 正确使用官方 `/datasets/{id}/retrieve` 接口 ✓
- 有合理的抽象层 `KBRetriever` + `DifyKBRetriever` ✓
- 有 `retrieval_orchestrator` 做 P1/P2 并列检索 ✓
- retry / health_check / SSL 处理齐全 ✓

**本次整改的核心目的**:
1. 对接长风知识整理系统新产出的**中央目录**,不再写死单个 `knowledge_default_dataset_id`
2. 按业务场景支持**多库 / 按 role 检索**
3. 约束写入边界(避免与长风知识整理系统入库链路冲突)

影响**远小于** 方案生成系统 系统,本文档相对紧凑。

---

## 二、关键基础事实

### 2.1 中央目录文件(权威数据,**必须从文件读**)

| 文件 | 绝对路径 | 用途 |
|---|---|---|
| **KB Catalog** | `D:\changfeng\长风知识整理系统\kb_catalog.yaml` | 所有 dataset 的 id/name/tier/roles/metadata_schema |
| **Metadata Schema** | `D:\changfeng\长风知识整理系统\kb_metadata_schema.yaml` | 通用字段 + 各类扩展字段 |

### 2.2 Dify API 事实

- **Base URL**:`https://192.168.110.78:18443/v1`(内网,SSL 自签)
- **单把 API Key**(调试阶段,后续拆分):`dataset-xxxxxxxxxxxxxxxxxxxxxxxxxx`
- **正式接口**:你们已在用 `/datasets/{id}/retrieve`,**保持**

### 2.3 18 个库的全景(见 catalog)

重点要让 招投标系统 能用上这些库(之前只用了默认一个):
- **A 核心业务层** 7 个:长风产品库/案例库/话术库/供应商/价格库/政府联系方式/长风内部资料
- **B 结构化参考层** 8 个:政策文件/官方指导/政府动态/林业知识/自动--产品库/检测报告/招投标流程/应用场景
- **C 资讯流层** 3 个:公众号/新闻日报/新闻条目

招投标系统 作为**标书书写**场景,主要会用:A 层 + B 层里的政策/检测报告/价格库。资讯层(C)一般不用。

---

## 三、改造任务清单

### 任务 1:加载中央目录(必改)

新增模块 `backend/app/utils/kb_catalog.py`:

```python
from __future__ import annotations
import yaml
from pathlib import Path
from functools import lru_cache

_CATALOG_PATH = Path(r"D:\changfeng\长风知识整理系统\kb_catalog.yaml")

@lru_cache(maxsize=1)
def load_catalog() -> dict:
    return yaml.safe_load(_CATALOG_PATH.read_text(encoding="utf-8"))

def dataset_ids_by_role(role: str) -> list[str]:
    return list(load_catalog().get("role_index", {}).get(role, []))

def dataset_ids_by_tier(tier: str) -> list[str]:
    return list(load_catalog().get("tier_index", {}).get(tier, []))

def dataset_name(dataset_id: str) -> str:
    for ds in load_catalog().get("datasets", []):
        if ds.get("id") == dataset_id:
            return ds.get("name", "")
    return ""
```

**验收**:`dataset_ids_by_role("policy")` 返回政策文件 + 官方指导的 id 列表。

### 任务 2:`KBRetriever` 扩展支持多库检索(推荐)

**现状**:`DifyKBRetriever.__init__(dataset_id=...)` 只绑定单个 dataset_id。

**改法**:增加一个新方法(不破坏现有接口):

```python
class DifyKBRetriever(KBRetriever):
    ...
    async def retrieve_in_datasets(
        self, query: str, dataset_ids: list[str], top_k: int = 5, filters: dict | None = None
    ) -> KBRetrieveOutcome:
        """按给定 dataset_ids 并行检索,结果合并按 score 排序后取 top_k。"""
        import asyncio
        tasks = [self._retrieve_single(ds_id, query, top_k, filters) for ds_id in dataset_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_chunks: list[KBChunk] = []
        any_reachable = False
        for r in results:
            if isinstance(r, KBRetrieveOutcome) and r.kb_reachable:
                any_reachable = True
                all_chunks.extend(r.chunks)
        all_chunks.sort(key=lambda c: c.score, reverse=True)
        return KBRetrieveOutcome(
            chunks=all_chunks[:top_k],
            kb_reachable=any_reachable,
            unreachable_reason="" if any_reachable else "all datasets unreachable",
        )

    async def _retrieve_single(
        self, dataset_id: str, query: str, top_k: int, filters: dict | None
    ) -> KBRetrieveOutcome:
        """原 retrieve 改造成单库版本,走 /datasets/{id}/retrieve"""
        # 参照现有 _do_retrieve 逻辑,url 用 f"{self.api_url}/datasets/{dataset_id}/retrieve"
        ...
```

**兼容原则**:保留原 `retrieve(query, top_k)` 方法,内部调用 `retrieve_in_datasets([self._dataset_id], ...)`。

**验收**:`retriever.retrieve_in_datasets("低空政策", dataset_ids_by_role("policy"))` 能返回命中。

### 任务 3:`retrieval_orchestrator` 按场景选库

**现状**:`orchestrate_retrieve(query)` 只查 `knowledge_default_dataset_id` 一个库。

**改法**:增加 `roles: list[str] | None = None` 参数:

```python
async def orchestrate_retrieve(
    query: str,
    top_k: int = 5,
    *,
    bypass_p1: Optional[bool] = None,
    roles: list[str] | None = None,   # 新增
) -> OrchestratedRetrievalOutcome:
    ...
    # 计算要查的 dataset_ids
    if roles:
        from app.utils.kb_catalog import dataset_ids_by_role
        dataset_ids = []
        for r in roles:
            dataset_ids.extend(dataset_ids_by_role(r))
        dataset_ids = list(dict.fromkeys(dataset_ids))  # 去重
    else:
        dataset_ids = [retriever._dataset_id] if retriever and retriever._dataset_id else []

    if dataset_ids:
        kb_out = await retriever.retrieve_in_datasets(query, dataset_ids, top_k=top_k)
    ...
```

**调用方**(上层业务 API)根据标书场景决定 roles:
- 查政策条款 → `roles=["policy"]`
- 查产品参数 → `roles=["product", "supplier_product"]`
- 查历史报价 → `roles=["pricing"]`
- 查公司案例 → `roles=["case"]`

### 任务 4:写入路径收归(必改 / 约束性)

**现状**:`KnowledgeMaterialService` 支持向 Dify 推文档。

**约束**(新规则):
- 招投标系统 **禁止**向业务库(tier A/B)直接写入
- chunking / metadata 统一由长风知识整理系统负责
- 如业务需要写入(比如用户上传的参考资料),只写入**你们自己的"招投标系统 私有库"**(后续申请,不在当前 catalog 中)

**执行**:
1. 在 `KnowledgeMaterialService` 的所有写入方法顶部加 guard:
   ```python
   from app.utils.kb_catalog import load_catalog
   ALLOWED_WRITE_DATASETS: set[str] = set()  # 暂时空 set = 禁止所有写入

   def _check_write_permission(self, dataset_id: str):
       if dataset_id not in ALLOWED_WRITE_DATASETS:
           raise PermissionError(
               f"招投标系统 禁止向 dataset {dataset_id} 直接写入;"
               f"请由长风知识整理系统负责入库。"
           )
   ```
2. 调用任何写入 API 前先 `_check_write_permission`
3. 如有真实业务写入需求,联系 KB 维护方申请专属库

### 任务 5:保持现有优点

以下**不要改**,它们做得很好:
- `KBRetriever` 抽象基类
- `get_kb_retriever` 单例模式
- `retrieval_orchestrator` 的 P1/P2 并列设计(禁止改成自动合并/选优)
- retry / health_check 机制
- `knowledge_httpx_verify` SSL 处理

---

## 四、边界与禁止事项

| 允许 | 禁止 |
|---|---|
| 读 `kb_catalog.yaml` / `kb_metadata_schema.yaml` | 硬编码 dataset UUID |
| 通过 role 解析 dataset_ids 后检索 | 把 role → id 映射写死在代码 |
| 多库并行检索 | 全库 "all" 散弹 |
| 单把 `dataset-xxxxxxxxxxxxxxxxxxxxxxxxxx` key(调试阶段) | 把 key 硬编码在非 config 处 |
| 向 招投标系统 专属库写入(后续申请) | 向 tier A/B 公共业务库直接写入 |
| 继续使用 `/datasets/{id}/retrieve` | 切换到 `/hit-testing` |

---

## 五、验收标准

- [ ] `backend/app/utils/kb_catalog.py` 加载中央目录成功
- [ ] `DifyKBRetriever.retrieve_in_datasets` 多库并行检索可用
- [ ] `orchestrate_retrieve(roles=[...])` 按角色路由到正确库
- [ ] `KnowledgeMaterialService` 写入路径有 guard,测试确保无法向业务库写入
- [ ] 原有 `KBRetriever` 抽象 / P1 本地政策 / retry 机制保持不变
- [ ] 现有 `test_kb_retriever.py` 全部通过

---

## 六、问题反馈

遇到问题直接联系长风知识整理系统维护方(问项目所有者),尤其:
- 需要新 role(当前 roles 列表见 `kb_catalog.yaml` 的 `role_index`)
- 需要 metadata schema 新字段
- 需要专属写入库

**禁止擅自修改** `D:\changfeng\长风知识整理系统\*.yaml`,必须由 KB 维护方统一更新。
