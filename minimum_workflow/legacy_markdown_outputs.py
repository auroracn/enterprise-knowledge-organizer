from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from minimum_workflow.document_profiles import clean_paragraph_text, strip_markdown_heading


# frontmatter 字段必须保持单行，避免路径、摘要等长文本把 YAML 结构打散。
def clean_metadata_value(value: str) -> str:
    normalized = str(value).replace("\r", " ").replace("\n", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


# 从原文标题中提取章节线索，生成一个极简摘要，便于 Dify 调试时先看到主要覆盖范围。
def build_summary(blocks: list[str]) -> str:
    heading_patterns = (
        r"^[一二三四五六七八九十]+、",
        r"^第[一二三四五六七八九十]+章",
        r"^\d+\.\d+",
        r"^\d+、",
    )
    headings: list[str] = []

    for block in blocks:
        normalized_block = strip_markdown_heading(block)
        if normalized_block.startswith("|"):
            continue
        if any(re.match(pattern, normalized_block) for pattern in heading_patterns):
            headings.append(normalized_block)

    if not headings:
        return "该文档已完成原文全量提取。"

    top_headings: list[str] = []
    for heading in headings:
        if heading not in top_headings:
            top_headings.append(heading)
        if len(top_headings) >= 8:
            break

    return "该文档主要包含以下章节或内容：" + "；".join(top_headings) + "。"


# 合并默认元数据与命令行补充元数据；同名字段以后传值为准，未出现的新字段按传入顺序追加。
def merge_metadata_items(
    default_items: list[tuple[str, str]],
    extra_items: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    merged = list(default_items)
    indexes = {key: index for index, (key, _) in enumerate(merged)}

    for key, value in extra_items:
        if key in indexes:
            merged[indexes[key]] = (key, value)
        else:
            indexes[key] = len(merged)
            merged.append((key, value))

    return merged


# 把关联文件整理成轻量小节，直接写入主 Markdown，避免额外拆分说明文件。
def build_related_section(title: str, description: str, paths: list[Path]) -> str:
    lines = [f"# {title}", "", f"- 说明：{description}"]

    if not paths:
        lines.append("- 无")
        return "\n".join(lines)

    for path in paths:
        lines.append(f"- 文件名：{path.name}")
        lines.append(f"  - 文件位置：{path}")

    return "\n".join(lines)


# 把模型摘要字段统一转换成 Markdown 列表，空值时也保留稳定占位，方便后续批处理产物结构一致。
def build_bullet_lines(items: list[str]) -> str:
    cleaned_items = [clean_paragraph_text(item) for item in items if clean_paragraph_text(item)]
    if not cleaned_items:
        return "- 无"
    return "\n".join(f"- {item}" for item in cleaned_items)


# 模型返回的字符串字段通常是多句摘要，这里只按显式分号或换行切分，避免把正文事实拆得过碎。
def split_summary_text(text: str) -> list[str]:
    normalized = text.replace("\r", "\n")
    items = [clean_paragraph_text(item) for item in re.split(r"[；\n]+", normalized) if clean_paragraph_text(item)]
    return items


# frontmatter 只保留有值字段，避免出现空行空键，提升 Dify 入库时的元数据稳定性。
def build_metadata_block(metadata_items: list[tuple[str, str]]) -> str:
    lines = []
    for key, value in metadata_items:
        cleaned_value = clean_metadata_value(value)
        if cleaned_value:
            lines.append(f"{key}: {cleaned_value}")
    return "\n".join(lines)


# 统一判断模型摘要是否真的提取到了内容，避免接口返回空壳 JSON 时也被当作成功。
def has_meaningful_summary_payload(payload: dict[str, Any]) -> bool:
    for value in payload.values():
        if isinstance(value, list) and value:
            return True
        if isinstance(value, str) and value.strip():
            return True
    return False


# 记录摘要模式的触发依据，方便批处理结果后续回查为什么不是原文全量版。
def build_summary_trigger_reason(pdf_output_mode: str, heavy_pdf_reason: str) -> str:
    if pdf_output_mode == "summary":
        return "命令行指定 PDF 摘要模式。"
    if heavy_pdf_reason:
        return f"auto 模式命中重版式特征：{heavy_pdf_reason}"
    return "auto 模式下命中重版式 PDF 判断。"


# 生成 Markdown，保留源文档文件名与位置元数据，正文以原文全文为主，摘要和取舍说明排在文末。
def build_markdown(
    source_path: Path,
    blocks: list[str],
    discarded_paths: list[Path],
    selection_reason: str,
    extra_metadata: list[tuple[str, str]],
    related_duplicate_paths: list[Path],
    related_policy_paths: list[Path],
    related_image_paths: list[Path],
) -> str:
    summary = build_summary(blocks)
    original_text = "\n\n".join(blocks)
    discarded_text = "\n".join(f"- {path.name}" for path in discarded_paths) if discarded_paths else "- 无"
    metadata_items = merge_metadata_items(
        [
            ("源文档文件名", source_path.name),
            ("源文档位置", str(source_path)),
            ("来源目录", str(source_path.parent)),
            ("文档分类", "项目方案文档"),
            ("输出类型", "原文全量提取Markdown"),
        ],
        extra_metadata,
    )
    metadata_block = build_metadata_block(metadata_items)
    duplicate_section = build_related_section(
        "关联近似版本",
        "以下文件与主方案同主题，当前按近似重复版本处理，不作为主抽取源，但保留关联关系与取舍依据。",
        related_duplicate_paths,
    )
    policy_section = build_related_section(
        "关联政策依据",
        "以下文件作为当前项目的政策/规划依据层关联材料保留，用于后续与主方案联动检索。",
        related_policy_paths,
    )
    image_section = build_related_section(
        "关联图件",
        "以下图件作为区域规划背景补充材料引用，图件关联信息直接写入主方案 Markdown。",
        related_image_paths,
    )

    return f"""---
{metadata_block}
---

# 原文全文

{original_text}

{duplicate_section}

{policy_section}

{image_section}

# 摘要

{summary}

# 取舍说明

保留主文件：
- {source_path.name}

未作为主抽取源的文件：
{discarded_text}

依据：
- {selection_reason}
"""


# 对重版式 PDF 输出摘要版 Markdown：保留核心元数据、结构化摘要和关联关系，不再硬塞低质量原文碎片。
def build_summary_markdown(
    source_path: Path,
    summary_payload: dict[str, Any],
    discarded_paths: list[Path],
    selection_reason: str,
    extra_metadata: list[tuple[str, str]],
    related_duplicate_paths: list[Path],
    related_policy_paths: list[Path],
    related_image_paths: list[Path],
    *,
    summary_trigger: str,
    extraction_note: str,
) -> str:
    discarded_text = "\n".join(f"- {path.name}" for path in discarded_paths) if discarded_paths else "- 无"
    metadata_items = merge_metadata_items(
        [
            ("源文档文件名", source_path.name),
            ("源文档位置", str(source_path)),
            ("来源目录", str(source_path.parent)),
            ("文档分类", "方案/案例"),
            ("输出类型", "模型摘要提取Markdown"),
            ("主体名称", summary_payload.get("主体名称", "")),
            ("方案名称/案例名称", summary_payload.get("方案名称/案例名称", "")),
            ("所属场景", summary_payload.get("所属场景", "")),
            ("客户/使用单位", summary_payload.get("客户/使用单位", "")),
            ("文件日期", summary_payload.get("文件日期", "")),
            ("转换状态", "基于重版式PDF的模型摘要提取"),
            ("摘要触发方式", summary_trigger),
            (
                "证据边界",
                "原始文件为重版式/图文混排 PDF，本 Markdown 仅保留可稳定识别的主要信息，金额、参数表、图件细节需回看原 PDF 复核。",
            ),
            ("解析备注", extraction_note),
        ],
        extra_metadata,
    )
    metadata_block = build_metadata_block(metadata_items)
    duplicate_section = build_related_section(
        "关联近似版本",
        "以下文件与主方案同主题，当前按近似重复版本处理，不作为主抽取源，但保留关联关系与取舍依据。",
        related_duplicate_paths,
    )
    policy_section = build_related_section(
        "关联政策依据",
        "以下文件作为当前项目的政策/规划依据层关联材料保留，用于后续与主方案联动检索。",
        related_policy_paths,
    )
    image_section = build_related_section(
        "关联图件",
        "以下图件作为区域规划背景补充材料引用，图件关联信息直接写入主方案 Markdown。",
        related_image_paths,
    )

    return f"""---
{metadata_block}
---

# 一、资料摘要

{build_bullet_lines(split_summary_text(summary_payload.get("资料摘要", "")))}

# 二、应用背景

{build_bullet_lines(summary_payload.get("应用背景", []))}

# 三、解决的问题

{build_bullet_lines(summary_payload.get("解决的问题", []))}

# 四、资料形态判断

{build_bullet_lines(split_summary_text(summary_payload.get("资料形态判断", "")))}

# 五、投入的产品/设备/能力

{build_bullet_lines(summary_payload.get("投入的产品/设备/能力", []))}

# 六、实施方式

{build_bullet_lines(summary_payload.get("实施方式", []))}

# 七、预算、进度与组织方式

{build_bullet_lines(summary_payload.get("预算、进度与组织方式", []))}

# 八、结果与效果数据

{build_bullet_lines(summary_payload.get("结果与效果数据", []))}

# 九、可复用经验

{build_bullet_lines(summary_payload.get("可复用经验", []))}

# 十、入库与归档判断

{build_bullet_lines(summary_payload.get("入库与归档判断", []))}

# 十一、备注

{build_bullet_lines(summary_payload.get("备注", []))}

{duplicate_section}

{policy_section}

{image_section}

# 取舍说明

保留主文件：
- {source_path.name}

未作为主抽取源的文件：
{discarded_text}

依据：
- {selection_reason}
- {summary_trigger}
"""


def should_use_pdf_summary_mode(source_path: Path, pdf_output_mode: str, is_heavy_pdf: bool) -> bool:
    if source_path.suffix.lower() != ".pdf":
        return False
    if pdf_output_mode == "summary":
        return True
    if pdf_output_mode == "auto":
        return is_heavy_pdf
    return False
