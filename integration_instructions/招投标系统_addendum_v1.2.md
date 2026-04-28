# 招投标系统 · Dify 知识库增补指令 v1.2

> **给**:招投标系统 AI 开发者
> **由**:长风知识整理系统架构师
> **日期**:2026-04-25 夜
> **基线**:`招投标系统_integration_v1.md` + `招投标系统_addendum_v1.1.md`
> **优先级**:**P1**(metadata filter 已 live 生效,本版用于灰度转正接入)
> **说明**:当前 live `changfeng-Dify-api` 已修复 metadata filter 静默失效问题并完成在线验证;你们可继续坚持“roles 为主”,但现在可以开始按白名单灰度启用 metadata 精筛

---

## 一、本版覆盖结论

以下旧口径,自本版起作废:
- “Dify 内网版本不支持 metadata filter”
- “未来若要时间过滤,目前走不通”

当前新结论:
1. `POST /v1/datasets/{dataset_id}/retrieve` 顶层参数可用:
   - `metadata_filtering_mode`
   - `metadata_filtering_conditions`
   - `metadata_model_config`
2. 非法字段名会显式报错
3. 非法 operator 会显式报错
4. 合法但无命中时,仍是正常 `HTTP 200 + records=[]`

权威契约文件:
- `D:\changfeng\长风知识整理系统\integration_instructions\metadata_filter_contract_v1.md`

---

## 二、你们应继续坚持的接入顺序

统一顺序不变:
1. 先用 **roles** 做业务路由
2. 再用 **metadata filter** 做库内精筛
3. 不向页面层开放任意 JSON 条件编辑器
4. 不允许页面层/agent 层自由拼 metadata 字段名

这意味着:
- 你们当前 `retrieval_orchestrator` 的方向是对的
- 本版不是推翻 roles 路线,而是在 roles 之后补一层可控精筛

---

## 三、调用契约

### 3.1 顶层参数写法

后续统一优先用顶层参数:

```json
{
  "query": "...",
  "retrieval_model": {
    "search_method": "semantic_search",
    "top_k": 5,
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
- 旧 `retrieval_model.metadata_filtering_conditions` 仍兼容
- 新接入不要继续扩散旧写法

### 3.2 布尔结构约束

当前统一只支持:
- 一层 `logical_operator`
- `conditions` 平铺列表
- `and` / `or`

当前统一**不支持**:
- 嵌套布尔树
- 页面自由拼装复杂 JSON 条件

---

## 四、当前允许你们公开接入的字段白名单

### 4.1 政策 / 资讯相关

若你们场景命中 `news_hot / news_wechat / news_daily / news_entry`,当前稳定可用字段为:

| 字段 | 类型 | 推荐 operator | 说明 |
|---|---|---|---|
| `publish_date` | time | `before` / `after` | 主时间字段 |
| `publish_ts` | number | `>` / `<` / `≥` / `≤` / `=` | 时间戳兜底 |
| `source_name` | string | `is` / `contains` / `in` | 来源名 |
| `source_type` | string | `is` / `in` | 来源类型 |
| `keyword_group` | string | `is` / `contains` / `in` | 主题组 |
| `report_date` | string | `is` / `in` | 报告日期字面值 |
| `content_tags` | string | `contains` / `is` | 标签串 |
| `superseded_by` | string | `empty` / `not empty` | 旧代内容过滤 |

### 4.2 产品 / 供应商 / 竞品相关

若你们场景命中 `supplier_product / competitor`,当前稳定可用字段为:

| 字段 | 类型 | 推荐 operator | 说明 |
|---|---|---|---|
| `brand` | string | `is` / `contains` / `in` | 品牌 |
| `model` | string | `is` / `contains` | 型号 |
| `category` | string | `is` / `in` | 类别 |
| `first_seen_date` | time | `before` / `after` | 首次提及时间 |
| `mention_count` | number | `>` / `<` / `≥` / `≤` / `=` | 热度 |
| `completeness_score` | number | `>` / `<` / `≥` / `≤` / `=` | 参数完整度 |
| `角色` | string | `is` / `in` | `竞品 / 供应商 / 自家 / 其他` |
| `superseded_by` | string | `empty` / `not empty` | 旧代过滤 |
| `publish_date` | time | `before` / `after` | 发布时间 |
| `publish_ts` | number | `>` / `<` / `≥` / `≤` / `=` | 时间戳兜底 |

### 4.3 当前不建议开放给页面层

以下范围继续禁止直接开放为通用筛选 UI:
- 14 个人工库中文字段
- 内部治理字段(如 `ingest_ts` / `content_hash`)
- 精确溯源字段(如 `original_url`)

---

## 五、操作符白名单

跨系统优先统一到以下稳定子集:

| 类型 | 推荐 operator |
|---|---|
| string | `is` / `is not` / `contains` / `not contains` / `in` / `not in` / `empty` / `not empty` |
| number | `>` / `<` / `≥` / `≤` / `=` / `≠` |
| time | `before` / `after` |

补充说明:
- Service API 如历史上已用 `greater_than` / `less_than` 等英文别名,可继续兼容
- 新增接入建议固定一种风格,不要符号和英文别名混用

明确禁止:
- `number` 字段配 `contains`
- `time` 字段配 `contains`
- 使用不存在的 metadata 字段名

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

合法但无命中:
- `HTTP 200`
- `records = []`

你们必须把以下两类情况分开:
- **参数非法** → 调用错误 / 契约错误
- **无命中** → 正常业务空结果

不要都归为“没搜到”。

---

## 七、建议灰度顺序

按你们当前回执,建议以下顺序转正:
1. 政策解读 / 法规摘录
2. 报价检索
3. 案例检索

推荐策略:
- 先只给后端编排层开放白名单字段
- 再给前端暴露有限枚举筛选项
- 每批只放开白名单字段与白名单 operator
- 不开放任意 JSON 条件编辑器

---

## 八、你们本轮最小 TODO

| 优先级 | 任务 | 说明 |
|---|---|---|
| **P1** | 在后端编排层接入顶层 metadata 参数 | 优先顶层 `metadata_filtering_mode / metadata_filtering_conditions` |
| **P1** | 统一白名单校验 | 页面/API/后端三层只允许白名单字段与 operator |
| **P1** | 错误语义分流 | 区分 `HTTP 400` 与 `records=[]` |
| P2 | 第一批灰度启用 | 先政策解读 / 法规摘录 |
| P2 | 日志增强 | 记录 roles、filter 字段、operator、命中数 |

建议日志格式补充:
```text
ORCHESTRATE query=... roles=[policy] filters=[publish_date after 2026-04-22] datasets=[id1,id2] records=3
```

---

## 九、延续有效的旧建议

以下 v1.1 建议仍有效:
- `retrieval_orchestrator` 的 roles 显式路由保持不变
- `kb_catalog.yaml` 版本感知日志建议继续保留
- 空库返回空结果属于正常,不得当错误
- 公共业务库写入 guard 仍应保留
- 若未来有真实写入需求,继续申请你们专属私有库

---

## 十、命名约定

| 旧称 | 正式名称 |
|---|---|
| 方案生成系统团队 | **方案生成系统团队** |
| yibiao | **招投标系统**(就是你们) |
| 长风知识整理系统 | **长风知识整理系统**(catalog/schema 维护方) |
| (新增) | **外部来源知识系统**(`D:\changfeng\外部来源知识`) |

有疑问联系长风知识整理系统维护方。
