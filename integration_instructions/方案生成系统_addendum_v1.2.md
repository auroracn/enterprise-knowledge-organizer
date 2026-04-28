# 方案生成系统 · Dify 知识库增补指令 v1.2

> **给**:方案生成系统 AI 开发者
> **由**:长风知识整理系统架构师
> **日期**:2026-04-24 晚
> **基线**:`方案生成系统_integration_v1.md` + `方案生成系统_addendum_v1.1.md`
> **优先级**:**P1**(含一个字段名错位需修,其余通报)
> **说明**:外部来源知识系统已产出字段映射文档,long-feng 的 catalog 和 schema 已对齐;本增补反哺到方案生成系统

---

## 一、关键变更 · 字段名错位必修

### 1.1 `news_hot` 时间过滤字段名:`发布日期` → `publish_date`

外部来源知识系统明确:4 个"自动--"库的时间字段**英文**是 **`publish_date`**(Dify 类型 **`time`**)。方案生成系统 v1 里用的 `发布日期`(中文)**不存在**于实际 metadata,即使 Dify filter 能用也过滤不到任何东西。

**修改点**:
- `base_agent.retrieve_kb` 或相关 news_hot 过滤代码中,过滤字段名 `发布日期` → **`publish_date`**
- 兜底字段可选:`publish_ts`(number,Unix 秒)
- 继续保持 opt-in(Dify v1.13.3 静默忽略过滤,不会立即生效,但修正字段名是无害的前置准备)

**权威字段定义**:`D:\changfeng\外部来源知识\docs\external_kb_field_mapping.md`

---

## 二、中央目录已 bump v2

`D:\changfeng\长风知识整理系统\kb_catalog.yaml` 版本升至 **v2**。主要变更:

| 项 | v1 | v2(实际) |
|---|---|---|
| `自动--公众号` retention_days | 7 | **180** |
| `自动--新闻条目` retention_days | 30 | **90** |
| `自动--新闻日报` retention_days | 90 | 90(不变) |
| `自动--产品库` retention_days | null | **3650**(不做 disable) |
| `自动--产品库` metadata_schema | product_v1 | **product_auto_v1** |

**影响**:
- 方案生成系统 `kb_catalog_loader` 下次启动会自动加载 v2,代码**不需要改**(只要没硬编码 version)
- `retention_days` 对方案生成系统无直接作用(归档是外部来源知识系统做的)
- `product_auto_v1` schema 新增 7 个产品专属字段,详见 §三

---

## 三、`自动--产品库` 新增的可用字段

以下字段**只在 `自动--产品库`** 存在,方案生成系统的 `CompetitorAgent` / `ProductMatchAgent` / `TechnicalArchitectureAgent` 查询 `supplier_product` role 时可识别到这些 metadata:

| 字段 | 类型 | 用途 |
|---|---|---|
| `brand` | string | 品牌,如"大疆"/"亿航"/"小鹏汇天" |
| `model` | string | 型号,如"机场3"/"FC200" |
| `category` | string | 类别:无人机/机场/eVTOL/飞控/电池/传感器/其他 |
| `first_seen_url` | string | 首次提及的文章 URL |
| `first_seen_date` | time | 首次提及日期 |
| `mention_count` | number | 累计被提及次数(**热度指标**) |
| `completeness_score` | number | 参数完整度 0-100 |

**建议优化点**(非强制):
- `CompetitorAgent` / `ProductMatchAgent` 拿到产品 chunk 后,可读 `brand` / `model` metadata 做**聚合去重**(同品牌同型号的多份 chunk 合并)
- 可按 `mention_count desc` 或 `completeness_score desc` 做**优先推荐**

---

## 四、过滤策略补充 · `superseded_by`

外部来源知识系统明确:`superseded_by` 字段**非空**代表该文档是**被替代的旧代产品**相关内容。

建议:查询 `news_hot` 或 `supplier_product` role 时,**默认过滤掉 `superseded_by` 非空**的文档(应用层自筛,Dify filter 尚不可用)。

实现方式:`retrieve_kb` 返回后,在代码里过滤 `metadata.superseded_by is empty`。

---

## 五、`content_tags` 使用注意

- `content_tags` 是**单个 string**,多值以 **`|`** 分隔(例:`政策|落地应用`)
- **不是 JSON 数组**(Dify v1.13 尚无 array 类型)
- 下游过滤时用 `.split("|")` 而非 `json.loads`
- 可选值固定 6 个:`政策` / `机型产品` / `价格` / `融资` / `落地应用` / `技术研发`

`FactCheckAgent` / `GeographicPolicyAgent` 若要按标签细分资讯可用。

---

## 六、Dify metadata filter 状态(v1.1 已通报,再次确认)

- Dify 内网 v1.13.3 **仍然静默忽略** `metadata_filtering_conditions`
- 修复字段名(§1.1)是**铺路**,不会立刻有效果
- 目前资讯治理主要靠外部来源知识系统的 `archive_stale.py` **disable** 动作
- Dify 升级后 long-feng 会统一通告

---

## 六B、竞品库方案 B 落地 · `CompetitorAgent` 切换

长风于 2026-04-25 决定采用**方案 B**:**不新建竞品库**,复用 `自动--产品库`,靠 metadata `角色` 区分。

### 6B.1 catalog 已到位
- `competitor` role 加入 `kb_catalog.yaml`(v3),指向 `自动--产品库` 同一个 UUID
- `product_auto_v1` schema 新增可选字段 `角色`(string,枚举:`竞品` / `供应商` / `自家` / `其他`)

### 6B.2 你们需要做的
1. `configs/agent_kb_roles.yaml` 里把 `CompetitorAgent: [supplier_product]` 改为 **`CompetitorAgent: [competitor]`**
2. 在 `retrieve_kb` 拿回 competitor role 的 chunks 后,**应用层过滤** `metadata.角色 == "竞品"`(因为 Dify filter 不生效)
3. 若某 chunk 的 `角色` 字段为空(外部来源知识系统尚未下发或未打标),**应保守处理**(可选:先按 `brand/model` 匹配已知竞品白名单,否则跳过)

### 6B.3 上游动作(外部来源知识系统侧,已发通知)
- 他们会在 `自动--产品库` 注册 `角色` metadata 字段
- 按 `sync_config.yaml` 中的 `competitor_brands` 白名单**自动打标**竞品
- 完成时间:他们按自己节奏,不阻塞你们**改 role 名和应用层过滤代码**(即使`角色`字段暂时为空,你们的代码也应能跑通,只是过滤掉所有文档)

### 6B.4 过渡期建议
在外部来源知识系统完成下发**之前**,为避免 `CompetitorAgent` 一直空返回,可以临时保留 **双 role**:
```yaml
CompetitorAgent: [competitor, supplier_product]
```
并用以下过滤策略:
```python
if chunk.metadata.get("角色") == "竞品":
    keep(chunk)
elif chunk.metadata.get("角色") is None:
    # 过渡期:无 角色 字段时,保守按 supplier_product 处理
    keep_if_brand_in_competitor_whitelist(chunk)
```
下发完成后切回单 role `[competitor]` 即可。

---

## 七、本增补 TODO 摘要

| 优先级 | 任务 | 说明 |
|---|---|---|
| **P1** | `news_hot` 过滤字段名 `发布日期` → `publish_date` | §1.1 |
| **P1** | `CompetitorAgent` roles `[supplier_product]` → `[competitor]` + 应用层过滤 `角色 == 竞品` | §六B |
| P3(建议) | `CompetitorAgent` / `ProductMatchAgent` 按 `brand/model` 聚合 | §三 |
| P3(建议) | 过滤 `superseded_by` 非空 | §四 |
| P3(建议) | `content_tags` 正确按 `\|` 切分 | §五 |

**其余** 为只读通报,不要求立即改动。

---

## 八、命名约定提醒

(与 v1.1 一致,不重复)

| 旧称 | 正式名称 |
|---|---|
| 方案生成系统团队 | **方案生成系统团队** |
| yibiao | **招投标系统** |
| (新知) | **外部来源知识系统**(`D:\changfeng\外部来源知识`) |
| long-feng | **长风知识整理系统**(本系统,catalog/schema 维护方) |

有疑问联系长风知识整理系统维护方。
