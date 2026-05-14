# RAGFlow 集成使用说明

## 功能概述

本系统已集成 RAGFlow 支持，可以在处理文档后自动将生成的 Markdown 文件上传到 RAGFlow 知识库。

## 配置方法

### 方法一：配置文件（推荐）

在项目根目录创建或编辑 `配置文件.chanfengdikongzl.json`：

```json
{
  "ragflow": {
    "api_url": "http://localhost:9380",
    "api_key": "YOUR_RAGFLOW_API_KEY",
    "default_dataset_ids": [],
    "verify_ssl": false
  }
}
```

### 方法二：命令行参数

```bash
python run_minimum_workflow.py --source-dir "源目录路径" \
  --upload-to-ragflow \
  --ragflow-api-url "http://localhost:9380" \
  --ragflow-api-key "YOUR_RAGFLOW_API_KEY" \
  --ragflow-dataset-id "知识库ID"
```

### 方法三：环境变量

```powershell
$env:RAGFLOW_API_URL = "http://localhost:9380"
$env:RAGFLOW_API_KEY = "YOUR_RAGFLOW_API_KEY"
```

## 使用方法

### 基本用法

```bash
# 处理目录并上传到 RAGFlow
python run_minimum_workflow.py --source-dir "D:\path\to\docs" --upload-to-ragflow

# 指定目标知识库 ID
python run_minimum_workflow.py --source-dir "D:\path\to\docs" --upload-to-ragflow --ragflow-dataset-id "your-dataset-id"
```

### 创建知识库

```python
from minimum_workflow.ragflow_import_service import RagflowClient, RagflowRuntime

runtime = RagflowRuntime(
    api_url="http://localhost:9380",
    api_key="your-api-key",
    default_dataset_ids=[],
    verify_ssl=False
)
client = RagflowClient(runtime)

# 创建新知识库
result = client.create_dataset("我的知识库")
dataset_id = result["data"]["id"]
```

### 手动上传文档

```python
from minimum_workflow.ragflow_import_service import RagflowClient, RagflowRuntime, upload_markdown_to_ragflow
from pathlib import Path

runtime = RagflowRuntime(
    api_url="http://localhost:9380",
    api_key="your-api-key",
    default_dataset_ids=["your-dataset-id"],
    verify_ssl=False
)
client = RagflowClient(runtime)

# 上传单个文件
md_file = Path("path/to/your/document.md")
result = upload_markdown_to_ragflow(client, "your-dataset-id", md_file)
```

## RAGFlow 配置要求

### 必须配置 Embedding 模型

文档解析需要 embedding 模型支持。请在 RAGFlow Web UI 中：

1. 访问 http://localhost:18090
2. 进入 **设置** -> **模型管理**
3. 添加 embedding 模型（如 text2vec、bge 等）
4. 设置为默认 embedding 模型

### 推荐配置

- **Chunk 方法**: naive（默认）
- **Chunk Token 数**: 512
- **布局识别**: DeepDOC（推荐）
- **启用 GraphRAG**: 可选

## 命令行参数说明

| 参数 | 说明 |
|------|------|
| `--upload-to-ragflow` | 启用 RAGFlow 上传功能 |
| `--ragflow-api-url` | RAGFlow API 地址 |
| `--ragflow-api-key` | RAGFlow API Key |
| `--ragflow-dataset-id` | 目标知识库 ID |

## 完整示例

```bash
# 1. 处理文档并上传到 RAGFlow
python run_minimum_workflow.py \
  --source-dir "D:\changfeng\外部来源知识\招投标" \
  --upload-to-ragflow \
  --ragflow-dataset-id "a276935a4f3411f1a954c71c57823d40"

# 2. 使用配置文件（推荐）
# 先编辑配置文件，然后：
python run_minimum_workflow.py \
  --source-dir "D:\changfeng\外部来源知识\招投标" \
  --upload-to-ragflow
```

## 查看上传结果

上传完成后，可以通过以下方式查看：

1. **RAGFlow Web UI**: http://localhost:18090
2. **API 查询**: 使用 RAGFlow API 查询知识库和文档状态

## 故障排除

### 问题：文档解析失败 "No default embedding model is set"

**解决方案**: 在 RAGFlow Web UI 中配置默认 embedding 模型。

### 问题：上传失败 "Connection refused"

**解决方案**: 检查 RAGFlow 服务是否正常运行。

### 问题：权限错误

**解决方案**: 检查 API Key 是否正确，是否有知识库的访问权限。

## API 参考

RAGFlow API 文档: https://ragflow.io/docs/dev/api_reference

## 当前知识库

- **测试知识库 ID**: `a276935a4f3411f1a954c71c57823d40`
- **Web UI**: http://localhost:18090
- **API**: http://localhost:9380
