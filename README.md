# 企业知识整理

把企业内部的政策、解决方案、证书/质检报告、公司介绍、产品设备、教育培训等异构文档（PDF / DOCX / DOC / PPT / XLSX / 图片等）批量结构化为带元数据标签的 Markdown，供 [Dify](https://dify.ai/) 等知识库底座检索与问答。

## 主链路

```
输入目录 → 文件类型与类别判定 → MinerU/本地解析转 Markdown
        → 全文保留 + 元数据标签 → 随机抽查搜索验收 → 落入审核输出目录
```

## 解析与兜底分层

1. **解析层**：MinerU 批量接口（强制优先），MarkItDown、`pypdf` / `pdfplumber` / `python-docx` / `openpyxl` 等作为补充
2. **模型层**：Qwen-Plus 用于分类、字段抽取与摘要润色（可选）
3. **兜底层**：Tesseract OCR（图片 / 扫描型 PDF 双层兜底），仍无法处理的留人工标注

## 类别模板

| 类别标识 | 说明 | 模板 |
|---|---|---|
| `policy` | 政策官方文件 | 政策官方文件模板 |
| `solution` | 解决方案 / 案例 | 方案案例模板 |
| `certificate` | 证书 / 质检报告 | 检测报告 / 产品设备模板 |
| `intro` | 公司介绍 / 供应商 | 供应商企业模板 |
| `product` | 产品 / 设备 | 产品设备模板 |
| `contract` | 合同 / 商务 | 合同商务模板 |
| `contact` | 单位联系人 | 单位联系人模板 |
| `education` | 教育培训 | 教育培训模板 |

## 目录结构

```
.
├── run_minimum_workflow.py            # 单文件 / 单样本最小闭环入口
├── run_claude_output_workflow.py      # 目录批量整理入口（含验收抽查）
├── 知识整理助手.py                    # 工具型脚本
├── minimum_workflow/                  # 主链路代码（解析、模板、契约、Dify 入库等）
│   ├── cli.py
│   ├── extractors.py                  # 解析器与 OCR 兜底
│   ├── pipeline.py                    # 抽取主管道
│   ├── markdown_templates.py          # 各类别 Markdown 模板
│   ├── document_profiles.py           # 文件类型判定规则
│   ├── detection_report_module.py     # 检测报告独立分类与字段抽取
│   ├── parameter_letter_module.py     # 参数函格式抽取
│   ├── dify_import_service.py         # Dify 知识库批量入库
│   ├── kb_catalog_validator.py        # 知识库目录契约校验
│   └── test_*.py                      # 配套单元测试
├── config/
│   └── minimum_workflow_contract.json # 字段契约
├── kb_catalog.yaml                    # 知识库目录契约
├── kb_metadata_schema.yaml            # 元数据 schema
├── integration_instructions/          # 与外部来源知识 / 招投标 / 方案生成系统的集成契约
└── 知识库结构化入Dify准备/             # Dify 入库的执行计划、分类、模板与去重规则
```

## 快速开始

需 Python 3.11+。按 `minimum_workflow/` 各模块按需安装可选依赖：

```bash
pip install requests pypdf pdfplumber python-docx openpyxl Pillow pymupdf
# OCR 兜底（可选）
pip install pytesseract        # 还需本机安装 Tesseract 与中文语言包 chi_sim
# 备用解析（可选）
pip install markitdown
```

运行单元测试：

```bash
python -m unittest discover -s minimum_workflow
```

最小闭环（单样本）：

```bash
python run_minimum_workflow.py --sample-id <样本ID> --pdf-extractor mineru
```

目录批量整理：

```bash
python run_claude_output_workflow.py --source-dir <源目录> --output-root <审核输出目录>
```

环境变量（可选）：

| 变量 | 用途 |
|---|---|
| `MINERU_TOKEN` | 启用 MinerU 真实 API |
| `QWEN_API_KEY` | 启用 Qwen-Plus 分类与字段抽取 |
| `DIFY_API_BASE` / `DIFY_API_KEY` | 批量入 Dify 知识库 |

## 验收口径

- **完整性**：从源文件随机抽 3 处正文短句，在生成的 Markdown 中字符串搜索均能精确命中
- **结构性**：每篇 Markdown 包含 YAML/表格元数据头部 + 原文主体 + 文末处理说明
- **可追溯**：源文件相对路径、文档类别、提取时间戳必填
- **优先级与去重**：同 stem 不同扩展名按 `docx > doc > xlsx > xls > pptx > ppt > pdf` 保留唯一稿

## 设计原则

- 主脚本只做类型判定与子模板调度，不嵌入业务生成逻辑
- 不删减原文段落、句子、表格数据
- 解析层优先于模型层，模型层优先于兜底层
- 所有变更先做最小回归测试再扩面

## License

未指定，仓库内容由仓库主自行决定使用方式。
