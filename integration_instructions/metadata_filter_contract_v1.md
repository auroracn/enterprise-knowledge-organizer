# 长风知识生态 · Metadata Filter 契约白名单 v1

> **给**:方案生成系统 / 招投标系统 / 长风知识整理系统维护方
> **由**:长风知识整理系统架构师
> **日期**:2026-04-25
> **适用范围**:当前 live `changfeng-Dify-api`（v1.13.3 修复后）
> **目的**:统一 metadata filter 的字段白名单、操作符白名单、错误语义与灰度启用顺序，避免各系统各写各的

---

## 一、当前已确认的 live 能力

当前 live `changfeng-Dify-api` 已确认：

1. `POST /v1/datasets/{dataset_id}/retrieve` 顶层参数可用：
   - `metadata_filtering_mode`
   - `metadata_filtering_conditions`
   - `metadata_model_config`
2. 非法字段名会显式报错，不再静默忽略
3. 非法操作符会显式报错，不再静默忽略
4. `string / number / time` 三类字段已完成 live 实测

**本轮统一原则**:
- 先用 **roles** 缩小库范围
- 再用 **metadata filter** 做库内精筛
- 不允许页面层或 agent 层自由拼任意字段名
- 不允许假定“传错也会 200 且自动忽略”

---

## 一-补、知识库目录契约（防止调库后取错库）

metadata filter 只负责“库内怎么筛”，**不负责决定应该查哪些库**。下游系统选库必须先走中央知识库目录：

- 唯一真源：`D:\changfeng\长风知识整理系统\kb_catalog.yaml`
- 当前目录版本：`version: 5`，`last_updated: 2026-04-28`
- 下游读取入口：`role_index` / `tier_index`
- 稳定契约：`roles` 名称
- 非稳定字段：Dify `dataset_id` / `name` 都可能随知识库迁移、重建、重命名而变化

### 目录变更后的强制顺序

当 Dify 内调整知识库目录、重命名库、重建库或迁移数据时，维护方必须按以下顺序发布：

1. 更新 live Dify 知识库
2. 同步 `kb_catalog.yaml` 的 `datasets` / `role_index` / `tier_index`
3. bump `version` 与 `last_updated`
4. 通知方案生成系统团队、招投标系统团队等下游重载目录
5. 按关键 role 做一次 smoke test：`role -> dataset ids -> retrieve`

下游系统不得继续使用旧版缓存的 dataset id。若本地缓存到的 catalog `version` 或 `last_updated` 落后，应拒绝静默继续使用旧路由，并在日志中打出当前版本与期望版本。

### 2026-04-28 已同步的关键变化

| 影响面 | 当前 live 口径 |
|---|---|
| 产品库 | `产品库`，id `9b910bf7-796e-4754-9f76-e1a08f95ae72` |
| 案例库 | `案例库`，id `6d70c0ba-0af1-405a-ab2f-cab255a17bc0` |
| 合作供应商资料 | id 已变更为 `e10ba417-785e-44e6-9914-4c71215f218f` |
| 新增/恢复库 | `行业知识` / `教育培训` / `长风实例库` / `低空行业动态` / `行业标准` |

注意：本契约后文的“先用 roles 缩小库范围”，明确指从 `kb_catalog.yaml` 的 `role_index` 解析 dataset ids，不是读取 Dify tag，也不是按页面展示名称猜库。

---

## 一-补-2、检索参数基线（2026-04-28 方案生成系统团队反馈后确认）

下游系统调用 `POST /v1/datasets/{dataset_id}/retrieve` 时，若没有单库特例，推荐采用 `kb_catalog.yaml` 的 `retrieval_defaults`：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `search_method` | `hybrid_search` | 兼容纯向量库与混合检索/Rerank 库 |
| `reranking_enable` | `true` | 库未配置 Rerank 时由 Dify 侧处理 |
| `score_threshold_enabled` | `false` | 建议由应用层做粗排截断 |
| `top_k` | `5` | 单库默认截断；单库可覆盖 |

当前 `政策文件` / `官方指导` / `政府动态` 三个库已在 `kb_catalog.yaml` 的单库 `retrieval` 字段覆盖为：

```yaml
retrieval:
  search_method: hybrid_search
  reranking_enable: true
  score_threshold_enabled: false
  top_k: 4
```

2026-04-28 复测结果：上述 3 个库在当前 live Dify 服务下，`semantic_search` 与 `hybrid_search + reranking_enable:true` 均返回 `HTTP 200`；因此当前不能认定为“后台强制只能混合检索”。但统一接入基线仍建议优先使用 `hybrid_search + reranking_enable:true`，以减少不同库后台策略差异对下游的影响。

---

## 二、调用面契约

### 2.1 Service API 顶层参数

推荐使用顶层参数，而不是只依赖旧的 `retrieval_model.metadata_filtering_conditions`：

```json
{
  "query": "...",
  "retrieval_model": {
    "search_method": "hybrid_search",
    "reranking_enable": true,
    "top_k": 5,
    "score_threshold_enabled": false
  },
  "metadata_filtering_mode": "manual",
  "metadata_filtering_conditions": {
    "logical_operator": "and",
    "conditions": [
      {
        "name": "publish_date",
        "comparison_operator": "after",
        "value": "2026-04-22"
      }
    ]
  }
}
```

### 2.2 布尔结构约束

当前统一约束为：
- 仅支持 **一层** `logical_operator`
- `conditions` 为**平铺列表**
- 只支持：
  - `logical_operator: and`
  - `logical_operator: or`
- **不支持嵌套布尔树**（例如 `(A and B) or (C and D)` 这种层级表达）

### 2.3 Workflow DSL 节点字段

Dify `knowledge-retrieval` 节点 DSL 当前字段为：
- `metadata_filtering_mode`
- `metadata_filtering_conditions`
- `metadata_model_config`

但在混合多库节点上，**只有当过滤字段是该节点选中知识库的稳定公共字段时**，才建议开启手动过滤。

---

## 三、操作符白名单

## 3.1 推荐稳定子集（跨系统优先用这一组）

| 类型 | 推荐操作符 | 说明 |
|---|---|---|
| string | `is` / `is not` / `contains` / `not contains` / `in` / `not in` / `empty` / `not empty` | 最稳妥 |
| number | `>` / `<` / `≥` / `≤` / `=` / `≠` | 推荐用于数值字段 |
| time | `before` / `after` | 推荐用于 `publish_date` / `first_seen_date` |

## 3.2 API 别名兼容

当前 live 后端还兼容若干 API 别名：
- `greater_than`
- `less_than`
- `greater_than_or_equal`
- `less_than_or_equal`

但为减少跨系统歧义：
- **Workflow DSL** 优先用符号型操作符
- **Service API** 若已用上述英文别名，可继续保留
- 新增接入时，建议在本系统文档里固定一种写法，不要同一仓混用两套风格

## 3.3 明确禁止

以下情况视为非法参数：
- `number` 字段配 `contains`
- `time` 字段配 `contains`
- 使用不存在的 metadata 字段名
- 在页面层放开任意自定义字段名输入

---

## 四、字段白名单（当前稳定可用）

> 这里只列**已在中央契约中稳定定义**、且适合下游做过滤的字段。
> 不在白名单中的字段，不代表数据库里绝对没有，而是**当前不建议作为公开契约对下游开放**。

## 4.1 `news_hot / news_wechat / news_daily / news_entry` 白名单

对应 schema：`news_v1` → `_external_common_v1`

| 字段 | 类型 | 推荐操作符 | 用途 | 备注 |
|---|---|---|---|---|
| `publish_date` | time | `before` / `after` | 新闻时间主过滤字段 | **主字段**，统一用它，不用中文`发布日期` |
| `publish_ts` | number | `>` / `<` / `≥` / `≤` / `=` | Unix 秒兜底 | 仅作兜底，不替代 `publish_date` |
| `source_name` | string | `is` / `contains` / `in` | 来源名筛选 | 如公众号名、媒体名 |
| `source_type` | string | `is` / `in` | 来源类型筛选 | `wechat / trendradar_daily / trendradar_item / product` |
| `keyword_group` | string | `is` / `contains` / `in` | 主题分组筛选 | 仅部分新闻条目有值 |
| `report_date` | string | `is` / `in` | 报告日期字面值 | 仅 news_item 有值，格式 `YYYY-MM-DD` |
| `content_tags` | string | `contains` / `is` | 业务标签筛选 | **不是数组**，多值以 `|` 分隔 |
| `superseded_by` | string | `empty` / `not empty` | 过滤旧代内容 | 推荐默认保留 `empty` |
| `original_url` | string | `is` | 精确溯源 | 不建议页面层暴露 |

### `news_*` 使用约束

1. 统一优先使用：
   - `publish_date`
   - 兜底 `publish_ts`
2. `content_tags` 是**单个 string**，不是 JSON 数组
   - 下游应用层若要多值拆分，用 `.split("|")`
3. `superseded_by` 非空表示旧代内容
   - 若做热点/推荐类检索，建议默认排除非空项

---

## 4.2 `supplier_product / competitor` 白名单

对应 schema：`product_auto_v1`

| 字段 | 类型 | 推荐操作符 | 用途 | 备注 |
|---|---|---|---|---|
| `brand` | string | `is` / `contains` / `in` | 品牌筛选 | 竞品/供应商常用 |
| `model` | string | `is` / `contains` | 型号筛选 | 精确匹配优先 |
| `category` | string | `is` / `in` | 产品类别 | 无人机 / 机场 / eVTOL / 飞控 / 电池 / 传感器 / 其他 |
| `first_seen_date` | time | `before` / `after` | 首次提及时间 | 新品时间窗口可用 |
| `mention_count` | number | `>` / `<` / `≥` / `≤` / `=` | 热度指标 | 推荐排序/筛选 |
| `completeness_score` | number | `>` / `<` / `≥` / `≤` / `=` | 参数完整度 | 推荐筛高质量条目 |
| `角色` | string | `is` / `in` | 竞品/供应商区分 | 枚举:`竞品 / 供应商 / 自家 / 其他` |
| `superseded_by` | string | `empty` / `not empty` | 排除旧代型号 | 推荐默认保留 `empty` |
| `publish_date` | time | `before` / `after` | 原始发布时间 | 继承自外部通用字段 |
| `publish_ts` | number | `>` / `<` / `≥` / `≤` / `=` | 时间戳兜底 | 继承自外部通用字段 |

### `supplier_product / competitor` 使用约束

1. `competitor` role 与 `supplier_product` role 共用同一个库
   - `competitor` 语义上仍应再看 `metadata.角色 == "竞品"`
2. `superseded_by` 非空视为旧代
   - 推荐默认过滤掉
3. `brand + model` 是重要业务聚合键
   - 若做推荐/去重，可在应用层聚合

---

## 4.3 当前**不建议公开开放**给页面层自由拼装的范围

以下范围当前不建议直接暴露为通用 metadata filter UI：

1. **人工/手动库中文字段**
   - 虽然 schema 里存在大量中文字段，但并未形成对下游统一开放的稳定白名单
   - 不同库字段覆盖不一致，容易让页面层拼出“这个库有、那个库没有”的无效条件

2. **内部治理字段**
   - 如 `ingest_ts` / `content_hash` 等
   - 允许底层系统或排障脚本使用
   - 不建议产品层或业务页面直接暴露

3. **精确溯源字段**
   - 如 `original_url`
   - 仅在排障、去重或回链时使用

---

## 五、错误语义约定

## 5.1 参数非法

### 非法字段名

```json
HTTP 400
Unknown metadata field: missing_field
```

### 非法操作符

```json
HTTP 400
Metadata field 'publish_ts' with type 'number' does not support operator 'contains'
```

## 5.2 无命中

统一按**正常检索结果为空**处理：
- 请求参数合法
- HTTP 200
- `records = []`

下游系统必须区分：
- **参数非法** → 调用错误 / 契约错误
- **无命中** → 正常业务结果为空

不要把两者混成一种“没搜到”。

---

## 六、灰度启用顺序（统一建议）

## 6.1 招投标系统

推荐顺序：
1. 政策解读 / 法规摘录
2. 报价检索
3. 案例检索

推荐策略：
- 先 `roles`
- 再 `roles + metadata filter`
- 页面层只允许选择**白名单字段与白名单操作符**
- 不开放任意 JSON 条件编辑器

## 6.2 方案生成系统

推荐顺序：
1. `news_hot` 时间窗过滤（`publish_date` 主字段，`publish_ts` 兜底）
2. `supplier_product` / `competitor` 的品牌、型号、角色、热度精筛
3. 视 agent 需要补充 `content_tags` / `superseded_by`

## 6.3 长风知识库机器人

当前策略：
- 已先移除 3 个 C 层新闻库
- 默认只查 A/B 层
- **不在当前混合 A/B 检索节点上直接硬挂 `publish_date` 手动过滤**

原因：
- `publish_date` 不是当前节点所有选中库的稳定公共 metadata
- 在单节点混挂多类库时，硬挂新闻时间过滤存在误伤人工库风险

---

## 七、推荐调用示例

## 7.1 新闻时间过滤

```json
{
  "query": "低空 发展",
  "retrieval_model": {
    "search_method": "hybrid_search",
    "reranking_enable": true,
    "top_k": 8,
    "score_threshold_enabled": false
  },
  "metadata_filtering_mode": "manual",
  "metadata_filtering_conditions": {
    "logical_operator": "and",
    "conditions": [
      {
        "name": "publish_date",
        "comparison_operator": "after",
        "value": "2026-04-22"
      }
    ]
  }
}
```

## 7.2 竞品产品过滤

```json
{
  "query": "机场",
  "retrieval_model": {
    "search_method": "hybrid_search",
    "reranking_enable": true,
    "top_k": 8,
    "score_threshold_enabled": false
  },
  "metadata_filtering_mode": "manual",
  "metadata_filtering_conditions": {
    "logical_operator": "and",
    "conditions": [
      {
        "name": "角色",
        "comparison_operator": "is",
        "value": "竞品"
      },
      {
        "name": "mention_count",
        "comparison_operator": ">",
        "value": 3
      },
      {
        "name": "superseded_by",
        "comparison_operator": "empty",
        "value": null
      }
    ]
  }
}
```

## 7.3 来源名过滤

```json
{
  "query": "公众号",
  "retrieval_model": {
    "search_method": "hybrid_search",
    "reranking_enable": true,
    "top_k": 8,
    "score_threshold_enabled": false
  },
  "metadata_filtering_mode": "manual",
  "metadata_filtering_conditions": {
    "logical_operator": "and",
    "conditions": [
      {
        "name": "source_name",
        "comparison_operator": "is",
        "value": "低空产业圈"
      }
    ]
  }
}
```

---

## 八、当前版本结论

当前 v1 统一口径如下：

1. live Dify metadata filter 已可正式使用
2. 下游系统必须按白名单字段、白名单操作符接入
3. 招投标系统 走“roles 为主、metadata 灰度转正”
4. 方案生成系统 的 `news_hot` 过滤链路可转正
5. 长风知识库机器人 当前先靠**缩小默认检索库范围**解决新闻稀释，不在混合节点上冒险硬挂新闻时间过滤

后续若新增稳定字段或 operator 约束，直接 bump 本文档版本。
