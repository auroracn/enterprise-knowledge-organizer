# 方案生成系统 · Dify 知识库增补指令 v1.3

> **给**:方案生成系统 AI 开发者
> **由**:长风知识整理系统架构师
> **日期**:2026-04-25 夜
> **基线**:`方案生成系统_integration_v1.md` + `方案生成系统_addendum_v1.1.md` + `方案生成系统_addendum_v1.2.md`
> **优先级**:**P1**(metadata filter 已 live 生效,本版用于把旧口径切到正式启用口径)
> **说明**:当前 live `changfeng-Dify-api` 已完成 metadata filter 修复与在线验证;本增补用于覆盖 v1.2 中“filter 尚不生效/仅占位”的旧表述

---

## 一、本版覆盖结论

以下旧口径,自本版起**作废**:

1. `metadata_filtering_conditions` 在 Dify v1.13.3 内网环境中静默忽略
2. `news_hot` 过滤链路只能继续保留占位,暂不能正式启用
3. `CompetitorAgent` 只能依赖应用层过滤,不考虑 Dify metadata filter

当前新结论:
- live `changfeng-Dify-api` 已确认支持 `POST /v1/datasets/{dataset_id}/retrieve` 顶层 metadata filter
- 非法字段名会显式报错
- 非法 operator 会显式报错
- `string / number / time` 三类字段均已做 live 实测

权威契约文件:
- `D:\changfeng\长风知识整理系统\integration_instructions\metadata_filter_contract_v1.md`

---

## 二、你们现在应采用的统一接入原则

### 2.1 检索顺序

统一按以下顺序接入:
1. 先用 **roles** 缩小库范围
2. 再用 **metadata filter** 做库内精筛
3. 仍保留应用层兜底过滤,但不再假定“Dify 会静默忽略错误条件”

### 2.2 参数口径

后续调用 `retrieve` 时,优先使用**顶层参数**:

```json
{
  "query": "...",
  "retrieval_model": {
    "search_method": "semantic_search",
    "top_k": 8,
    "score_threshold": 0.3
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

兼容说明:
- 旧的 `retrieval_model.metadata_filtering_conditions` 兼容能力仍在
- 新增接入统一改为顶层字段,不要继续扩散旧写法

### 2.3 布尔结构约束

当前只按中央契约使用:
- 只支持一层 `logical_operator`
- `conditions` 为平铺列表
- 当前只放开 `and` / `or`
- **不支持嵌套布尔树**

---

## 三、方案生成系统当前应立即采用的字段白名单

### 3.1 `news_hot / news_wechat / news_daily / news_entry`

统一只用以下稳定字段:

| 字段 | 类型 | 推荐 operator | 说明 |
|---|---|---|---|
| `publish_date` | time | `before` / `after` | 主时间字段 |
| `publish_ts` | number | `>` / `<` / `≥` / `≤` / `=` | Unix 秒兜底 |
| `source_name` | string | `is` / `contains` / `in` | 来源名筛选 |
| `source_type` | string | `is` / `in` | 来源类型 |
| `keyword_group` | string | `is` / `contains` / `in` | 主题组 |
| `report_date` | string | `is` / `in` | 日报日期字面值 |
| `content_tags` | string | `contains` / `is` | 标签串,不是数组 |
| `superseded_by` | string | `empty` / `not empty` | 旧代内容过滤 |

使用约束:
- 主字段统一 `publish_date`,不用中文 `发布日期`
- `content_tags` 是单个 string,多值以 `|` 分隔,不是 JSON 数组
- 若做热点/推荐类检索,建议默认保留 `superseded_by empty`

### 3.2 `supplier_product / competitor`

统一只用以下稳定字段:

| 字段 | 类型 | 推荐 operator | 说明 |
|---|---|---|---|
| `brand` | string | `is` / `contains` / `in` | 品牌 |
| `model` | string | `is` / `contains` | 型号 |
| `category` | string | `is` / `in` | 产品类别 |
| `first_seen_date` | time | `before` / `after` | 首次提及时间 |
| `mention_count` | number | `>` / `<` / `≥` / `≤` / `=` | 热度 |
| `completeness_score` | number | `>` / `<` / `≥` / `≤` / `=` | 参数完整度 |
| `角色` | string | `is` / `in` | `竞品 / 供应商 / 自家 / 其他` |
| `superseded_by` | string | `empty` / `not empty` | 旧代过滤 |
| `publish_date` | time | `before` / `after` | 发布时间 |
| `publish_ts` | number | `>` / `<` / `≥` / `≤` / `=` | 时间戳兜底 |

使用约束:
- `competitor` role 虽与 `supplier_product` 共用同一库,但语义上仍应附加 `metadata.角色 == "竞品"`
- `brand + model` 仍可在应用层做聚合去重
- `superseded_by` 非空建议默认排除

---

## 四、你们现在要改的不是字段名,而是启用口径

### 4.1 `news_hot` 链路

若你们代码/文档/测试中已统一到:
- 主字段 `publish_date`
- 兜底字段 `publish_ts`

则**不需要重复修字段名**。

本版真正要求你们做的是:
1. 把“仅占位/当前无效”的文案统一删掉
2. 将 `news_hot` 的 metadata filter 视为**正式可用能力**
3. 在需要时间窗过滤时,按白名单字段/operator 直接传参
4. 写错字段或 operator 时,按显式 `HTTP 400` 修正,不要再按“静默忽略”理解

### 4.2 `CompetitorAgent` 链路

当前建议分两层:

第一层: role 路由
- `CompetitorAgent` 主路由使用 `[competitor]`

第二层: metadata 精筛
- 逐步引入 `角色 is 竞品`
- 需要时间过滤时可叠加 `publish_date`
- 需要热度精筛时可叠加 `mention_count > N`
- 需要排除旧代时可叠加 `superseded_by empty`

过渡期说明:
- 若上游 `角色` 字段尚未全量打标,可继续保留应用层白名单兜底
- 但从本版开始,不要把“Dify filter 不生效”再当作兜底理由

---

## 五、明确禁止

以下做法本版起不再接受:
- 继续在新代码里使用中文时间字段 `发布日期`
- 继续保留“传错字段也会 200 且自动忽略”的假设
- 在 agent 层自由拼任意 metadata 字段名
- 对 `content_tags` 做 `json.loads`
- 让 number/time 字段配 `contains`

---

## 六、错误语义

### 6.1 参数非法

非法字段:
```json
HTTP 400
Unknown metadata field: missing_field
```

非法 operator:
```json
HTTP 400
Metadata field 'publish_ts' with type 'number' does not support operator 'contains'
```

### 6.2 无命中

合法请求但无结果:
- `HTTP 200`
- `records = []`

你们必须区分:
- **参数非法** → 契约错误 / 调用错误
- **无命中** → 正常业务空结果

---

## 七、建议灰度顺序

### 7.1 第一批(建议立即转正)
1. `news_hot` 时间窗过滤
   - 主字段 `publish_date`
   - 兜底字段 `publish_ts`
2. `CompetitorAgent`
   - `角色 == 竞品`
   - `superseded_by empty`

### 7.2 第二批(建议稳定后再加)
3. `supplier_product` 的 `brand / model / category` 精筛
4. `mention_count` / `completeness_score` 精筛
5. `content_tags` 细分资讯标签过滤

---

## 八、你们本轮应完成的最小 TODO

| 优先级 | 任务 | 说明 |
|---|---|---|
| **P1** | 清理旧文案 | 删除“metadata filter 当前无效/仅占位”相关表述 |
| **P1** | `news_hot` 正式启用 | 按 `publish_date` / `publish_ts` 白名单启用时间过滤 |
| **P1** | `CompetitorAgent` 切正式口径 | 以 `competitor` role 为主,逐步加 `角色 == 竞品` 精筛 |
| P2 | 参数错误处理 | 把 400 与空结果区分开 |
| P2 | 保留应用层兜底 | 仅作过渡,不替代 Dify filter |

---

## 九、命名约定提醒

| 旧称 | 正式名称 |
|---|---|
| 方案生成系统团队 | **方案生成系统团队** |
| yibiao | **招投标系统** |
| (新知) | **外部来源知识系统**(`D:\changfeng\外部来源知识`) |
| long-feng | **长风知识整理系统**(本系统,catalog/schema 维护方) |

有疑问联系长风知识整理系统维护方。
