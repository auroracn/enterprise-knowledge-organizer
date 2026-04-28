# 外部来源知识系统 · 增补指令 v1.1

> **给**:外部来源知识系统 AI 开发者
> **由**:长风知识整理系统架构师
> **日期**:2026-04-25
> **基线**:`外部来源知识系统_integration_v1.md`
> **优先级**:P2(不紧急,协调完成即可)

---

## 一、背景

字段映射文档 v1(`docs/external_kb_field_mapping.md`)**长风已全部吸收**。catalog/schema 已 bump 到 v2,你们 4 个"自动--"库的 dataset_id / retention_days / 字段名/类型 全部对齐。

本增补只有**一项新需求**:配合**竞品库方案 B**。

---

## 二、决策背景:竞品库选 B

用户 2026-04-25 拍板竞品库方案:
- **A**(新建"长风竞品库",长风维护入库)— **不采用**
- **B**(复用 `自动--产品库`,加 `角色` metadata 区分)— **采用**

原因:你们系统**已经**在抓取第三方厂家产品并写入 `自动--产品库`,再新建库会造成数据重复和二次同步负担。加一个 metadata 字段**最轻**。

---

## 三、需要你们做的(4 步)

### 3.1 在 `自动--产品库` 注册新 metadata 字段

字段名 `角色`,类型 `string`,枚举值:
- `竞品`
- `供应商`
- `自家`
- `其他`

**建议改法**:
- 在 `config/metadata_schema.yaml` 为 `products` 库新增该字段
- 跑 `scripts/bootstrap_metadata.py` 幂等下发到 Dify

### 3.2 在 `config/sync_config.yaml` 新增 `competitor_brands` 白名单

```yaml
competitor_brands:
  # 示例,以长风知识整理系统维护方最终确认的列表为准
  - 大疆
  - 亿航
  - 小鹏汇天
  - 峰飞航空
  # ...
```

长风知识整理系统维护方后续会**提供正式竞品品牌清单**。过渡期你们可以先放几个明显的做验证。

### 3.3 `sync_products.py` 入库时按白名单打标

伪代码:
```python
def classify_role(brand: str, config) -> str:
    competitors = config.get("competitor_brands") or []
    our_brand = config.get("our_brand", "长风")
    suppliers = config.get("supplier_brands") or []

    if brand == our_brand:
        return "自家"
    if brand in competitors:
        return "竞品"
    if brand in suppliers:
        return "供应商"
    return "其他"
```

并在 Dify metadata 上传时带上 `角色` 字段。

### 3.4 存量文档重刷

白名单变更或代码逻辑变更时 bump `tagging.version`,触发存量重刷。或手工跑 `scripts/reprocess.py --kb products` 指定刷新。

---

## 四、时间与节奏

- **不紧急**,长风正在并行推进聊天机器人 yml 修改
- 方案生成系统已收到指令,会先改 `CompetitorAgent` 的 role 映射(从 `[supplier_product]` → `[competitor]`),并在应用层过滤
- 在你们下发 `角色` 字段之前,方案生成系统会采用"临时双 role + 品牌白名单兜底"的过渡策略,**不会因你们没下发而报错**
- 你们完成后请在一轮回执里告知,长风会通知方案生成系统切回单 role

---

## 五、边界重申

与 v1 指令一致:
- 你们**只动** 4 个 `自动--` 库 ✓
- 禁止对 14 个人工库做任何写操作
- 禁止调用 Dify DELETE;只做 disable
- 变更 metadata schema 前先知会长风(本次算已知会)

---

## 六、字段版本

- `cleaning.version` / `tagging.version` 变更时,请在下一版 `external_kb_field_mapping.md` 顶部更新
- 长风这边会在你们确认后 bump `kb_catalog.yaml` / `kb_metadata_schema.yaml` 到 v4(目前 v3 已有 `角色` 占位定义)

有疑问联系长风知识整理系统维护方。
