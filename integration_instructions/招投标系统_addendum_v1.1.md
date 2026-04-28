# 招投标系统 · Dify 知识库增补指令 v1.1

> **给**:招投标系统 AI 开发者
> **由**:长风知识整理系统架构师
> **日期**:2026-04-24
> **基线**:`招投标系统_integration_v1.md`(已完成)
> **优先级**:P2(信息性为主)

---

## 一、v1 整改回执确认

收到你们 v1 升级完成的回执:
- ✅ "单默认库" 升级为 "中央目录 + 按 role 多库检索"
- ✅ 公共业务库写入已收口为禁止

**后续(你们侧)**:把更多上层业务场景(正文生成 / 政策解读 / 报价)显式传入 roles — 长风已知悉,不阻塞。

---

## 二、2026-04-24 新信息通报

### 2.1 Dify 内网版本 **不支持** metadata filter

长风知识整理系统验证了 Dify v1.13.3 的 `metadata_filtering_conditions`:**静默忽略**。

**对你们的影响**:
- 目前的 role 路由 + `retrieval_orchestrator` 并列编排**不受影响**(没依赖 filter)
- 未来若想加"只看最近 30 天政策"等时间过滤,目前走不通,需等 Dify 升级或用应用层过滤兜底

### 2.2 `retrieval_orchestrator` 日志建议

目前 `orchestrate_retrieve(roles=[...])` 已支持按角色路由。建议在日志里加一条:
```
ORCHESTRATE query=... roles=[policy,product] p1_state=... p2_reachable=... datasets=[id1,id2]
```
便于运维排查"这个问题为什么没查到 XX 库"。

### 2.3 catalog 版本感知建议

长风 `kb_catalog.yaml` 已有 `version: 1` 字段。建议:
- 启动日志加一条 `[KBCatalog] loaded version=1 datasets=18 roles=22`
- 长风更新 catalog 后你们能立刻发现版本号变化

### 2.4 空库处理

`招投标流程文档` / `应用场景` 两个库目前 0 份文档,role 查询返回空 records 属于**正常**,不得当错误。

### 2.5 `KnowledgeMaterialService` 写入 guard 建议加 test

你们已经加了 guard 禁止向公共业务库写入。**强烈建议**加一条 pytest,保证未来改动不破坏约束:
```python
def test_writes_to_public_dataset_forbidden():
    svc = KnowledgeMaterialService()
    with pytest.raises(PermissionError):
        svc._check_write_permission("9b910bf7-...")  # 长风产品库
```

### 2.6 未来的写入需求走"私有库"

如果后续你们有真实业务写入需求(如用户上传的标书参考件),**申请一个你们专属的库**,不要往公共业务库写。申请流程:
1. 告知长风知识整理系统维护方需求
2. 长风在 Dify 新建库,写入 catalog(`ingest_source: manual`,但 `owner: 招投标系统`)
3. 把新库的 id 加入你们 `ALLOWED_WRITE_DATASETS` 白名单

---

## 三、100MB 标书 workflow 规划

长风预计会推进这个场景(你们之前的痛点之一),设计方向:
- 文件解析/表格抽取/参数比对放**招投标系统外部**(用长风知识整理系统的 MinerU 链路)
- 结构化后的需求条目,用 role 批量检索 Dify(产品库/价格库/供应商/案例库)
- Dify **不**直接吃 100MB 文件

**何时启动**:等你们上层场景 roles 传递工作告一段落后,长风会正式发起。**现在不用准备**,只是提醒别自己单独开发文件解析层,长风这边已有链路可复用。

---

## 四、命名约定更新

| 旧称 | 正式名称 |
|---|---|
| 方案生成系统团队 | **方案生成系统团队** |
| yibiao | **招投标系统**(就是你们) |
| 长风知识整理系统 | **长风知识整理系统**(catalog/schema 维护方) |
| (新增) | **外部来源知识系统**(`D:\changfeng\外部来源知识`,维护 4 个"自动--"库) |

---

## 五、无强制任务

本增补是**通报**,可在常规迭代中合并处理。建议优先级:

1. §2.5 写入 guard pytest(**强烈建议**)
2. §2.2 日志增强
3. §2.3 catalog 版本日志

其余只读。

有疑问联系长风知识整理系统维护方。
