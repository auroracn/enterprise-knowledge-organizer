# 方案生成系统 · Dify 知识库增补指令 v1.1

> **给**:方案生成系统 AI 开发者
> **由**:长风知识整理系统架构师
> **日期**:2026-04-24
> **基线**:`方案生成系统_integration_v1.md`(已完成)
> **优先级**:P2(信息性为主,1 处可改可不改)

---

## 一、v1 整改回执确认

收到你们 7 次提交(`e1ca863` → `6953908`),全量 pytest **302 passed** 已确认。以下已验收通过:

- ✅ `/hit-testing` → `/retrieve`
- ✅ `search_all` / `retrieve("all")` / `search("all")` 全抛 `DeprecationWarning`
- ✅ `KBCatalog().dataset_ids_by_role("product")` 命中
- ✅ 单次请求 Dify 调用数从 540 降到 Σ(roles × datasets)
- ✅ `news_hot` 时间过滤 opt-in

---

## 二、2026-04-24 新信息通报

### 2.1 Dify 内网版本 **不支持** metadata filter(重要)

长风知识整理系统验证了 Dify v1.13.3 的 `metadata_filtering_conditions`:HTTP 200 返回,但**静默忽略**过滤条件。验证脚本:`D:\changfeng\长风知识整理系统\_dify_metadata_filter_probe.py`。

**对你们的影响**:
- `news_hot` 时间过滤 opt-in 代码**可以保留**,但**实际效果为零**
- 不要基于"时间过滤能工作"做新业务设计
- 等 Dify 升级后再启用(长风会通告)

### 2.2 时间过滤字段名**与实际不符**(待修,但不紧急)

你们 v1 里 `news_hot` 时间过滤用的字段名是 **`发布日期`**(中文)。

外部来源知识系统(维护"自动--"4 个库的方 `D:\changfeng\外部来源知识`)实际注册的字段是 **`publish_date`**(time 类型)和 **`publish_ts`**(number 类型,时间戳)。

**待修**:
- 修改 `news_hot` 时间过滤代码里的字段名从 `发布日期` → `publish_date`
- 反正 Dify 现在也不过滤,修不修不影响当前运行
- **建议等长风知识整理系统更新 catalog 的 `news_v1` schema 后(字段名英文化)再一次性改**

长风会在外部来源知识系统产出字段映射后立即更新 catalog 并通知你们。

### 2.3 新闻治理实际由 disable 机制承担

外部来源知识系统的 `archive_stale.py` 已在跑,超期文档会被 **disable**(Dify 检索不召回)。这意味着:
- 你们 `news_hot` 检索到的文档已经是"未过期的"(靠 disable 实现)
- **不需要等 Dify filter 能用**,新闻稀释问题**已经在 Dify 入库侧解决**
- 你们的 role 路由 + 外部系统的 disable 归档,两者组合已经足够

### 2.4 catalog 版本感知建议

长风的 `kb_catalog.yaml` 已有 `version: 1` 字段。建议:
- 你们 `kb_catalog_loader` 启动时打印一条日志:
  ```
  [KBCatalog] loaded version=1 datasets=18 roles=22
  ```
- 方便长风更新 catalog 后你们排查是否生效

### 2.5 空库处理

`招投标流程文档` / `应用场景` 两个库目前 0 份文档,role 查询会返回空 records。这是**正常状态**,agent 不得视为错误。

---

## 三、竞品库 role 进展

`competitor_library` role 长风还没最终决定:
- 选项 A:Dify 新建"长风竞品库" (长风维护入库)
- 选项 B:`自动--产品库` 文档加 `角色=竞品` metadata 区分

**你们无需等**:当前 `CompetitorAgent: [supplier_product]` 占位继续用;决定后长风更新 catalog,你们改 `agent_kb_roles.yaml` 即可。

---

## 四、命名约定更新

长风生态统一命名如下(请你们内部文档/注释也逐步更新):

| 旧称 | 正式名称 |
|---|---|
| 方案生成系统团队 | **方案生成系统团队** |
| yibiao | **招投标系统** |
| 长风知识整理系统 | **长风知识整理系统**(本系统,catalog/schema 维护方) |
| (新增) | **外部来源知识系统**(D:\changfeng\外部来源知识,维护 4 个"自动--"库) |

---

## 五、你们的当前 TODO(来自 v1 回执,长风已知悉)

- scripts/test_dify.py / test_new_dify_url.py 残留 `hit-testing` / `'all'` → ops 清理
- RESUME.md 同步"整改 v1 已落地"
- 上层场景化 roles 继续(已在迭代)

不阻塞长风侧任何工作。

---

## 六、无需求、无阻塞

本增补是**通报**,不要求立即改动。可与下次常规迭代合并处理。

有疑问联系长风知识整理系统维护方。
