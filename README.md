# 企业知识整理系统

把企业内部的政策文件、解决方案、证书质检报告、公司介绍、产品设备、教育培训、招投标等异构文档（PDF / DOCX / DOC / PPT / XLSX / 图片等）批量结构化为带元数据标签的 Markdown，供 RAGFlow / Dify 等知识库底座检索与问答。

## 主链路

```
输入目录 → 递归扫描与去重 → 文件类型与类别判定 → MinerU/本地解析转 Markdown
        → 全文保留 + 元数据标签 → 随机抽查搜索验收 → 落入审核输出目录
        → （可选）自动上传至 RAGFlow / Dify 知识库
```

## 核心功能

### 文档解析（三层兜底）

| 层级 | 工具 | 说明 |
|------|------|------|
| 解析层（优先） | MinerU 批量接口 | PDF / DOCX / PPTX 等主流格式强制走 MinerU；大文件自动分片 |
| 补充层 | MarkItDown、pypdf、pdfplumber、python-docx、openpyxl | MinerU 不可用或失败时的本地解析兜底 |
| 兜底层 | Tesseract OCR | 扫描型 PDF / 纯图片文字识别 |
| 模型层（可选） | Qwen-Plus | 分类、字段抽取、摘要润色 |

### 文档分类与模板

自动识别文档类别并匹配对应模板填充元数据：

| 类别标识 | 说明 | 模板 |
|----------|------|------|
| `policy` | 政策官方文件、标准规范 | 政策官方文件模板 |
| `solution` | 解决方案 / 案例 | 方案案例模板 |
| `certificate` | 证书 / 质检报告 | 检测报告模板 |
| `intro` | 公司介绍 / 供应商 | 供应商企业模板 |
| `product` | 产品 / 设备资料 | 产品设备模板 |
| `contract` | 合同 / 商务 | 合同商务模板 |
| `contact` | 单位联系人 | 单位联系人模板 |
| `education` | 教育培训 | 教育培训模板 |
| `quotation` | 报价清单 | 报价清单模板 |

### 目录扫描与去重

- **递归扫描**：`Path.rglob("*")` 递归遍历子目录，自动跳过纯照片、劳动合同、保单等非知识库文件
- **同名去重**：同目录下 stem 相同但扩展名不同的文件，按优先级 `docx > doc > xlsx > xls > pptx > ppt > pdf` 保留一个
- **跨目录内容去重**：对剩余文件计算 MD5 哈希，内容相同的文件只保留一个，跳过项写入扫描报告
- **大文件分片**：超过阈值的文件自动拆分为 chunk，支持 chunk cache 跳过已完成分片

### 知识库上传

#### RAGFlow（推荐）

处理完成后可自动或手动将 Markdown 上传至 RAGFlow 知识库：

```bash
# 命令行自动上传
python -m minimum_workflow.cli --source-dir "D:\docs" --upload-to-ragflow \
  --ragflow-api-url "http://localhost:9380" \
  --ragflow-api-key "your-api-key" \
  --ragflow-dataset-id "your-dataset-id"
```

也可通过 Web UI 勾选"启用 RAGFlow 上传"，处理完成后自动上传。

#### Dify

同样支持 Dify 知识库批量入库，通过 `dify_import_service.py` 模块实现。

### Web UI（知识整理助手）

基于 Gradio 的图形界面，支持：

- 配置管理（MinerU / Qwen / Dify / RAGFlow 参数）
- 资料目录选择与处理
- 批次管理与历史查看
- 手动上传到 RAGFlow / Dify
- 实时进度与日志显示

```bash
python 知识整理助手.py
```

## 快速开始

### 环境要求

- Python 3.11+
- 可选依赖按需安装

```bash
# 核心依赖
pip install requests pypdf pdfplumber python-docx openpyxl Pillow pymupdf

# OCR 兜底（可选，还需本机安装 Tesseract + chi_sim 语言包）
pip install pytesseract

# 备用解析（可选）
pip install markitdown
```

### 单样本处理

```bash
python run_minimum_workflow.py --sample-id <样本ID> --pdf-extractor mineru
```

### 目录批量处理

```bash
python run_claude_output_workflow.py --source-dir <源目录> --output-root <审核输出目录>
```

### CLI 完整参数

```bash
python -m minimum_workflow.cli --source-dir <源目录> \
  --pdf-extractor mineru          # PDF 解析策略：mineru（默认）或 local
  --mineru-token <token>          # MinerU API token
  --enable-ocr                    # 启用 OCR 兜底
  --enable-qwen                   # 启用 Qwen 字段增强
  --resume                        # 重跑上轮失败条目
  --upload-to-ragflow             # 处理后自动上传到 RAGFlow
  --ragflow-dataset-id <id>       # 目标知识库 ID
  --output-dir <目录>             # 审核输出目录
  --internal-output-dir <目录>    # 内部结构化输出目录
```

## 配置

### 配置文件

在项目根目录创建 `配置文件.<profile>.json`（profile 用于多公司隔离）：

```json
{
  "mineru": {
    "token": "your-mineru-token"
  },
  "qwen": {
    "api_key": "your-qwen-api-key",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "model": "qwen-plus"
  },
  "ragflow": {
    "api_url": "http://localhost:9380",
    "api_key": "your-ragflow-api-key",
    "default_dataset_ids": [],
    "verify_ssl": false
  }
}
```

### 环境变量

| 变量 | 用途 |
|------|------|
| `MINERU_TOKEN` | MinerU API token |
| `QWEN_API_KEY` / `QWEN_BASE_URL` / `QWEN_MODEL` | Qwen 模型配置 |
| `RAGFLOW_API_URL` / `RAGFLOW_API_KEY` / `RAGFLOW_DEFAULT_DATASET_IDS` | RAGFlow 配置 |
| `DIFY_API_BASE` / `DIFY_API_KEY` / `DIFY_DEFAULT_DATASET_IDS` | Dify 配置 |

## 目录结构

```
.
├── run_minimum_workflow.py              # 单样本最小闭环入口
├── run_claude_output_workflow.py        # 目录批量整理入口（含验收抽查）
├── 知识整理助手.py                      # Gradio Web UI
├── minimum_workflow/                    # 核心模块
│   ├── cli.py                           # CLI 入口与目录扫描逻辑
│   ├── pipeline.py                      # 抽取主管道
│   ├── extractors.py                    # 文本提取器（PDF/Word/Excel/PPT/图片）
│   ├── document_profiles.py             # 文档分类与类型判定
│   ├── field_extractors.py              # 结构化字段抽取
│   ├── markdown_templates.py            # 各类别 Markdown 模板渲染
│   ├── qwen_client.py                   # Qwen LLM 调用
│   ├── runtime_config.py                # 配置加载（文件/环境变量/别名）
│   ├── contracts.py                     # 字段契约与样本管理
│   ├── ragflow_import_service.py        # RAGFlow API 客户端
│   ├── dify_import_service.py           # Dify API 客户端
│   ├── detection_report_module.py       # 检测报告独立分类
│   ├── parameter_letter_module.py       # 参数函格式抽取
│   ├── directory_extractors.py          # 图片目录抽取
│   ├── mineru_large_file.py             # 大文件分片处理
│   ├── llm_registry.py                  # LLM 模型注册
│   ├── kb_catalog_validator.py          # 知识库目录契约校验
│   └── test_*.py                        # 单元测试
├── config/
│   └── minimum_workflow_contract.json   # 字段契约定义
├── ragflow_config_example.json          # RAGFlow 配置示例
└── test_ragflow_integration.py          # RAGFlow 集成测试
```

## 验收标准

- **内容完整性**：从源文件随机抽 3 处正文短句（≥12 字），在生成的 Markdown 中字符串搜索均能精确命中
- **结构规范性**：每篇 Markdown 包含 YAML frontmatter 元数据 + 原文主体 + 文末处理说明
- **可追溯性**：源文件路径、文档类别、提取时间戳必填
- **纯表格豁免**：报价清单、Excel 等纯表格资料无散文短句时自动豁免抽查
- **去重完整性**：同名去重 + 跨目录内容去重（MD5），跳过项全部写入扫描报告

## 设计原则

- 主脚本只做类型判定与子模板调度，不嵌入业务生成逻辑
- 不删减原文段落、句子、表格数据
- 解析层优先于模型层，模型层优先于兜底层
- 空字段不输出，只保留有实际内容的字段
- 所有变更先做最小回归测试再扩面

## License

未指定，仓库内容由仓库主自行决定使用方式。
