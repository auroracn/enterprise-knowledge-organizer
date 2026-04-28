from __future__ import annotations

import argparse
import logging
import re
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from minimum_workflow.contracts import ExtractionResult
from minimum_workflow.cli import resolve_mineru_token, resolve_qwen_runtime
from minimum_workflow.directory_extractors import (
    classify_image_directory as profile_classify_image_directory,
    collect_directory_image_paths as profile_collect_directory_image_paths,
    extract_image_directory_content as profile_extract_image_directory_content,
    is_directory_document_image as profile_is_directory_document_image,
    is_directory_page_image as profile_is_directory_page_image,
    sort_directory_image_key as profile_sort_directory_image_key,
)
from minimum_workflow.document_profiles import (
    clean_paragraph_text as profile_clean_paragraph_text,
    count_keyword_hits as profile_count_keyword_hits,
    infer_document_date as profile_infer_document_date,
    infer_document_profile as profile_infer_document_profile,
    infer_document_title as profile_infer_document_title,
    infer_document_version as profile_infer_document_version,
    infer_primary_organization as profile_infer_primary_organization,
    split_text_to_blocks as profile_split_text_to_blocks,
    strip_markdown_heading as profile_strip_markdown_heading,
)
from minimum_workflow.extractors import export_presentation_slides_to_images, extract_pdf_text, extract_text, run_mineru_batch
from minimum_workflow.legacy_markdown_outputs import (
    build_bullet_lines as legacy_build_bullet_lines,
    build_markdown as legacy_build_markdown,
    build_metadata_block as legacy_build_metadata_block,
    build_related_section as legacy_build_related_section,
    build_summary as legacy_build_summary,
    build_summary_markdown as legacy_build_summary_markdown,
    build_summary_trigger_reason as legacy_build_summary_trigger_reason,
    clean_metadata_value as legacy_clean_metadata_value,
    has_meaningful_summary_payload as legacy_has_meaningful_summary_payload,
    merge_metadata_items as legacy_merge_metadata_items,
    should_use_pdf_summary_mode as legacy_should_use_pdf_summary_mode,
    split_summary_text as legacy_split_summary_text,
)
from minimum_workflow.qwen_client import summarize_solution_document_with_qwen


W_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
W_TAG_PREFIX = f"{{{W_NS['w']}}}"
PDF_SUSPICIOUS_SNIPPETS = (
    "中国一中红广通国",
    "无人机驾驶飞行器故障检测报告书",
    "委托人持普通股数或优先股数",
    "反对票数反对股数弃权股数比例（%）",
    "单调地讲，改变单调本身后",
)
HEAVY_PDF_WATERMARKS = (
    "感谢您下载包图网平台上提供的PPT作品",
    "ibaotu.com",
    "请勿复制、传播、销售",
)
HEAVY_PDF_LAYOUT_MARKERS = (
    "环境温度",
    "目标温度设为",
    "货箱容积",
    "适配机型",
    "循环使用",
    "温控运输箱",
)
HEAVY_PDF_DIMENSION_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*(?:mm|cm|kg|g|L|°C|℃)")
DEFAULT_SELECTION_REASON = "当前保留该文件作为本轮主抽取源；未传入明确近似版本对比信息时，默认不判定其他文件为重复稿，后续如发现同目录近似版本，再按信息完整度、来源可靠性和重复关系补充取舍依据。"
OFFICE_MINERU_SUFFIXES = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".pdf"}
MARKITDOWN_SEARCH_PATHS = [
    PROJECT_ROOT / ".omc" / "generated" / "markitdown_compare_site",
]
MINERU_SINGLE_FILE_LIMIT_BYTES = 200 * 1024 * 1024


def _load_markitdown_converter() -> Any | None:
    try:
        from markitdown import MarkItDown  # type: ignore

        return MarkItDown
    except Exception as exc:
        logging.debug("MarkItDown导入失败: %s", exc)
        pass

    for extra_path in MARKITDOWN_SEARCH_PATHS:
        if not extra_path.exists():
            continue
        extra_path_str = str(extra_path)
        inserted = False
        if extra_path_str not in sys.path:
            sys.path.insert(0, extra_path_str)
            inserted = True
        try:
            from markitdown import MarkItDown  # type: ignore

            return MarkItDown
        except Exception as exc:
            logging.debug("markitdown导入失败: %s", exc)
            continue
        finally:
            if inserted and sys.path and sys.path[0] == extra_path_str:
                sys.path.pop(0)

    return None


# 仅在 MinerU 不可用或失败时，为 Office 文档尝试 MarkItDown 备用解析，不改变主链路优先级。
def try_extract_with_markitdown(source_path: Path, file_type: str) -> ExtractionResult | None:
    if file_type not in {"word", "presentation", "excel", "pdf"}:
        return None

    markitdown_cls = _load_markitdown_converter()
    if markitdown_cls is None:
        return None

    try:
        converter = markitdown_cls()
        result = converter.convert(str(source_path))
    except Exception as exc:
        logging.debug("MarkItDown转换失败: %s", exc)
        return None

    markdown = str(getattr(result, "markdown", "") or getattr(result, "text_content", "") or "").strip()
    if not markdown:
        return None

    suffix_label = source_path.suffix.lower().lstrip(".") or file_type
    return ExtractionResult(
        extractor_name=f"markitdown:{suffix_label}",
        extraction_status="已提取文本",
        extracted_text=markdown,
        preview_text=markdown[:200],
        text_length=len(markdown),
        page_count=None,
        source_encoding="utf-8",
        note=f"已通过 MarkItDown 完成 {source_path.suffix.lower()} 备用解析。",
    )


def should_use_mineru_presentation_image_chain(source_path: Path, file_type: str) -> bool:
    if file_type != "presentation" or source_path.suffix.lower() not in {".ppt", ".pptx"}:
        return False
    try:
        return source_path.stat().st_size > MINERU_SINGLE_FILE_LIMIT_BYTES
    except OSError:
        return False


# 把文档判型结果与真实抽取链路折叠成 frontmatter 元数据，确保终稿可直接看出唯一类别与处理方式。
def build_auto_metadata(source_path: Path, blocks: list[str], extraction_result: ExtractionResult) -> list[tuple[str, str]]:
    profile = infer_document_profile(source_path.name, blocks)
    extractor_name = extraction_result.extractor_name or "未识别"
    source_shape = "分页扫描图片目录" if source_path.is_dir() else source_path.suffix.lower().lstrip(".") or "未知"
    is_mineru = extractor_name.startswith("mineru:") or "mineru" in extractor_name.lower()
    is_markitdown = extractor_name.startswith("markitdown:")
    if is_mineru:
        conversion_status = "MinerU成功"
        processing_chain = "唯一类别判定 -> MinerU格式转换 -> 原文全量提取 -> 数据标签整理"
    elif is_markitdown:
        conversion_status = "MarkItDown降级成功"
        processing_chain = "唯一类别判定 -> MarkItDown备用解析 -> 原文全量提取 -> 数据标签整理"
    else:
        conversion_status = "回退本地解析"
        processing_chain = "唯一类别判定 -> 本地解析回退 -> 原文全量提取 -> 数据标签整理"
    metadata_items = [
        ("文件标题", profile.get("文件标题", "")),
        ("文档分类", profile.get("文档分类", "")),
        ("模板归属", profile.get("模板归属", "")),
        ("资料层级", profile.get("资料层级", "")),
        ("主体名称", profile.get("主体名称", "")),
        ("发布时间", profile.get("发布时间", "")),
        ("版本信息", profile.get("版本信息", "")),
        ("证据边界", profile.get("证据边界", "")),
        ("是否适合直接入Dify", profile.get("是否适合直接入Dify", "")),
        ("唯一类别判定", profile.get("模板归属", "")),
        ("来源形态", source_shape),
        ("抽取器", extractor_name),
        ("抽取状态", extraction_result.extraction_status),
        ("转换状态", conversion_status),
        ("处理链路", processing_chain),
    ]
    return [(key, value) for key, value in metadata_items if clean_metadata_value(value)]


# MinerU 支持的 Office/PDF 文档默认优先走批量 Markdown 转换；失败或文本不足时再按本地链路回退。
def extract_office_document_content(source_path: Path, file_type: str) -> dict[str, Any]:
    mineru_token = resolve_mineru_token(None)
    mineru_error = ""
    extraction_result: ExtractionResult | None = None
    source_suffix = source_path.suffix.lower()
    is_presentation = file_type == "presentation" and source_suffix in {".ppt", ".pptx"}
    local_docx_blocks: list[str] = []

    if should_use_mineru_presentation_image_chain(source_path, file_type) and mineru_token:
        try:
            extraction_result = extract_large_presentation_via_mineru_images(source_path, mineru_token)
        except Exception as exc:
            mineru_error = f"演示文稿超过 MinerU 单文件体积限制，分页图片 OCR 失败，已回退本地解析：{exc}"
    elif source_suffix in OFFICE_MINERU_SUFFIXES and mineru_token:
        try:
            batch_result = run_mineru_batch([source_path], mineru_token)
            mineru_item = batch_result["results"][0]
            markdown = str(mineru_item.get("markdown", "")).strip()
            mineru_error_text = str(mineru_item.get("error") or "")
            if mineru_item.get("state") == "done" and markdown:
                extraction_result = ExtractionResult(
                    extractor_name="mineru:batch",
                    extraction_status="已提取文本",
                    extracted_text=markdown,
                    preview_text=markdown[:200],
                    text_length=len(markdown),
                    page_count=None,
                    source_encoding="utf-8",
                    note=f"已通过 MinerU 批量接口完成 Markdown 提取，批次号：{batch_result['batch_id']}。",
                )
            elif is_presentation and "file size exceeds limit" in mineru_error_text.lower():
                try:
                    extraction_result = extract_large_presentation_via_mineru_images(source_path, mineru_token)
                except Exception as exc:
                    mineru_error = f"MinerU 演示文稿直传触发体积限制，分页图片 OCR 失败，已回退本地解析：{exc}"
            else:
                mineru_error = (
                    f"MinerU 未返回可用 Markdown，状态：{mineru_item.get('state') or 'unknown'}，"
                    f"错误：{mineru_error_text or '未注明'}。"
                )
        except Exception as exc:
            if is_presentation and "file size exceeds limit" in str(exc).lower():
                try:
                    extraction_result = extract_large_presentation_via_mineru_images(source_path, mineru_token)
                except Exception as image_exc:
                    mineru_error = f"MinerU 演示文稿直传触发体积限制，分页图片 OCR 失败，已回退本地解析：{image_exc}"
            else:
                mineru_error = f"MinerU 提取失败，已回退本地解析：{exc}"
    elif source_suffix in OFFICE_MINERU_SUFFIXES:
        mineru_error = "未提供 MinerU token，已回退本地解析。"

    if file_type == "word" and source_suffix == ".docx":
        local_docx_blocks = extract_docx_blocks(source_path)

    if extraction_result is None:
        markitdown_result = try_extract_with_markitdown(source_path, file_type)
        if markitdown_result is not None:
            if mineru_error:
                markitdown_result.note = f"{markitdown_result.note} {mineru_error}".strip()
            extraction_result = markitdown_result

    if extraction_result is None:
        if file_type == "word" and source_suffix == ".docx":
            local_text = "\n\n".join(local_docx_blocks)
            extraction_result = ExtractionResult(
                extractor_name="word:docx",
                extraction_status="已提取文本" if local_text.strip() else "待人工复核",
                extracted_text=local_text,
                preview_text=local_text[:200],
                text_length=len(local_text),
                page_count=None,
                source_encoding="docx",
                note=mineru_error,
            )
            blocks = local_docx_blocks
        else:
            extraction_result = extract_text(source_path, file_type)
            if mineru_error:
                extraction_result.note = f"{extraction_result.note} {mineru_error}".strip()
            blocks = split_text_to_blocks(extraction_result.extracted_text)
    else:
        blocks = split_text_to_blocks(extraction_result.extracted_text)
        if local_docx_blocks:
            local_table_blocks = [block for block in local_docx_blocks if block.lstrip().startswith("|") and "| ---" in block]
            merged_blocks = blocks[:]
            for table_block in local_table_blocks:
                if table_block not in merged_blocks:
                    merged_blocks.append(table_block)
            if merged_blocks != blocks:
                blocks = merged_blocks
                extraction_result = ExtractionResult(
                    extractor_name=extraction_result.extractor_name,
                    extraction_status=extraction_result.extraction_status,
                    extracted_text="\n\n".join(blocks),
                    preview_text="\n\n".join(blocks)[:200],
                    text_length=len("\n\n".join(blocks)),
                    page_count=extraction_result.page_count,
                    source_encoding=extraction_result.source_encoding,
                    note=f"{extraction_result.note} 已补充本地 docx 表格结构提取。".strip(),
                )

    if not extraction_result.extracted_text.strip():
        raise RuntimeError(f"未能从 {source_path.suffix} 提取到可用文本：{extraction_result.note}")

    auto_metadata = build_auto_metadata(source_path, blocks, extraction_result)
    selection_reason = "已按唯一类别判定后输出单版终稿 Markdown，正文尽量完整保留并记录真实抽取链路。"
    extraction_note = clean_paragraph_text(extraction_result.note)

    return {
        "blocks": blocks,
        "extracted_text": extraction_result.extracted_text,
        "is_heavy_pdf": False,
        "heavy_pdf_reason": "",
        "extraction_note": extraction_note,
        "auto_metadata": auto_metadata,
        "selection_reason": selection_reason,
        "extraction_result": extraction_result,
    }



# MinerU 返回单文件体积超限时，PPT/PPTX 先导出逐页图片再按页序走 MinerU OCR，尽量保持主链路不回退到本地解析。
def extract_large_presentation_via_mineru_images(source_path: Path, mineru_token: str) -> ExtractionResult:
    temp_dir, image_paths = export_presentation_slides_to_images(source_path)
    try:
        batch_result = run_mineru_batch(image_paths, mineru_token, poll_interval_seconds=5, max_polls=120)
        page_texts: list[str] = []
        failed_pages: list[str] = []
        for image_path, result in zip(image_paths, batch_result["results"]):
            markdown = str(result.get("markdown", "")).strip()
            if result.get("state") == "done" and markdown:
                page_texts.append(markdown)
            else:
                failed_pages.append(image_path.name)

        extracted_text = "\n\n".join(page_texts).strip()
        if not extracted_text:
            failed_summary = "、".join(failed_pages) if failed_pages else "无"
            raise RuntimeError(f"导出图片后 MinerU OCR 未返回可用正文，失败页：{failed_summary}。")

        failed_summary = "、".join(failed_pages) if failed_pages else "无"
        note = (
            f"原始演示文稿超过 MinerU 单文件体积限制，已导出 {len(image_paths)} 页图片后按页序走 MinerU OCR；"
            f"批次号：{batch_result['batch_id']}；OCR失败页：{failed_summary}。"
        )
        return ExtractionResult(
            extractor_name="mineru:presentation_images",
            extraction_status="已提取文本",
            extracted_text=extracted_text,
            preview_text=extracted_text[:200],
            text_length=len(extracted_text),
            page_count=len(image_paths),
            source_encoding="utf-8",
            note=note,
        )
    finally:
        temp_dir.cleanup()


# 提取节点中的纯文本，供段落和表格单元格复用。
def extract_text_from_node(node: ET.Element) -> str:
    texts = [text_node.text or "" for text_node in node.findall(".//w:t", W_NS)]
    return clean_paragraph_text("".join(texts))


# 把表格单元格里的多段文本收敛成纯文本，避免在终稿中留下 <br> 这类 HTML 标签。
def merge_table_cell_lines(cell_lines: list[str]) -> str:
    normalized_lines = [line.strip() for line in cell_lines if line.strip()]
    if not normalized_lines:
        return "-"

    merged = normalized_lines[0]
    for line in normalized_lines[1:]:
        if re.fullmatch(r"[0-9\-]{7,}", line):
            merged = f"{merged} {line}"
        elif (
            len(merged) <= 8
            and len(line) <= 8
            and re.fullmatch(r"[\u4e00-\u9fffA-Za-z]+", merged)
            and re.fullmatch(r"[\u4e00-\u9fffA-Za-z]+", line)
        ):
            merged = f"{merged}{line}"
        else:
            merged = f"{merged}；{line}"
    return merged.replace("|", r"\|")


# 将 Word 表格转成 Markdown 表格，避免表格内容被打散成连续段落。
def render_table_as_markdown(table: ET.Element) -> str:
    rows: list[list[str]] = []

    for row in table.findall("./w:tr", W_NS):
        row_cells: list[str] = []
        for cell in row.findall("./w:tc", W_NS):
            cell_lines: list[str] = []
            for paragraph in cell.findall("./w:p", W_NS):
                paragraph_text = extract_text_from_node(paragraph)
                if paragraph_text:
                    cell_lines.append(paragraph_text)
            cell_text = merge_table_cell_lines(cell_lines)
            row_cells.append(cell_text)
        if any(cell.strip("-") for cell in row_cells):
            rows.append(row_cells)

    if not rows:
        return ""

    column_count = max(len(row) for row in rows)
    normalized_rows = [row + ["-"] * (column_count - len(row)) for row in rows]
    header = normalized_rows[0]
    separator = ["---"] * column_count
    markdown_lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]

    for row in normalized_rows[1:]:
        markdown_lines.append("| " + " | ".join(row) + " |")

    return "\n".join(markdown_lines)


# 按文档顺序提取 docx 正文块，当前优先保留段落与表格，不走 OCR。
def extract_docx_blocks(docx_path: Path) -> list[str]:
    with zipfile.ZipFile(docx_path) as archive:
        xml_bytes = archive.read("word/document.xml")

    root = ET.fromstring(xml_bytes)
    body = root.find("w:body", W_NS)
    if body is None:
        return []

    blocks: list[str] = []

    for child in body:
        if child.tag == f"{W_TAG_PREFIX}p":
            paragraph = extract_text_from_node(child)
            if paragraph:
                blocks.append(paragraph)
        elif child.tag == f"{W_TAG_PREFIX}tbl":
            table_markdown = render_table_as_markdown(child)
            if table_markdown:
                blocks.append(table_markdown)

    return blocks


# 把解析层返回的整段文本切成 Markdown 块，尽量保持标题、表格和正文的可读性。
def split_text_to_blocks(text: str) -> list[str]:
    normalized_text = text.replace("\r", "").strip()
    if not normalized_text:
        return []
    return [block.strip() for block in re.split(r"\n\s*\n", normalized_text) if block.strip()]


# 检查 PDF 提取结果中是否混入了明显不属于当前文档的异常文本层；命中多个特征后再触发回退，避免误杀正常正文。
def has_suspicious_pdf_noise(text: str) -> bool:
    hit_count = sum(1 for snippet in PDF_SUSPICIOUS_SNIPPETS if snippet in text)
    return hit_count >= 2


# 对重版式 PDF 做保守判断：优先用显式水印、图表特征词和碎片化程度作为触发信号，避免把普通正文 PDF 误切到摘要模式。
def detect_heavy_pdf_layout(text: str, blocks: list[str]) -> tuple[bool, str]:
    reasons: list[str] = []
    watermark_hits = [snippet for snippet in HEAVY_PDF_WATERMARKS if snippet in text]
    layout_marker_hits = [marker for marker in HEAVY_PDF_LAYOUT_MARKERS if marker in text]
    fragmented_block_count = sum(1 for block in blocks if len(block) <= 18)
    block_count = max(len(blocks), 1)
    fragmented_ratio = fragmented_block_count / block_count
    dimension_hit_count = len(HEAVY_PDF_DIMENSION_PATTERN.findall(text))

    if watermark_hits:
        reasons.append("命中重版式水印：" + "、".join(watermark_hits[:2]))
    if len(layout_marker_hits) >= 3:
        reasons.append("命中图表/参数页特征词：" + "、".join(layout_marker_hits[:4]))
    if fragmented_block_count >= 25 and fragmented_ratio >= 0.35 and dimension_hit_count >= 6:
        reasons.append(
            f"短碎片段较多（{fragmented_block_count}/{block_count}），且参数单位片段较多（{dimension_hit_count}处）"
        )

    return bool(reasons), "；".join(reasons)


clean_paragraph_text = profile_clean_paragraph_text
split_text_to_blocks = profile_split_text_to_blocks
strip_markdown_heading = profile_strip_markdown_heading
count_keyword_hits = profile_count_keyword_hits
infer_document_title = profile_infer_document_title
infer_primary_organization = profile_infer_primary_organization
infer_document_date = profile_infer_document_date
infer_document_version = profile_infer_document_version
infer_document_profile = profile_infer_document_profile
sort_directory_image_key = profile_sort_directory_image_key
collect_directory_image_paths = profile_collect_directory_image_paths
is_directory_page_image = profile_is_directory_page_image
is_directory_document_image = profile_is_directory_document_image
classify_image_directory = profile_classify_image_directory
clean_metadata_value = legacy_clean_metadata_value
build_summary = legacy_build_summary
merge_metadata_items = legacy_merge_metadata_items
build_related_section = legacy_build_related_section
build_bullet_lines = legacy_build_bullet_lines
split_summary_text = legacy_split_summary_text
build_metadata_block = legacy_build_metadata_block
has_meaningful_summary_payload = legacy_has_meaningful_summary_payload
build_summary_trigger_reason = legacy_build_summary_trigger_reason
build_markdown = legacy_build_markdown
build_summary_markdown = legacy_build_summary_markdown
should_use_pdf_summary_mode = legacy_should_use_pdf_summary_mode


# 目录 OCR 主实现已迁到独立模块；这里保留兼容入口，避免旧调用点失效。
def extract_image_directory_content(source_dir: Path, mineru_token: str | None = None) -> dict[str, Any]:
    return profile_extract_image_directory_content(
        source_dir,
        mineru_token=mineru_token,
        token_resolver=resolve_mineru_token,
        batch_runner=run_mineru_batch,
    )


# 根据文件类型选用对应提取方式；目录型分页扫描件走整目录 OCR，Office/PDF 先走 MinerU，必要时回退本地解析。
def extract_source_content(source_path: Path) -> dict[str, Any]:
    if source_path.is_dir():
        return extract_image_directory_content(source_path)

    suffix = source_path.suffix.lower()

    if suffix in {".doc", ".docx"}:
        return extract_office_document_content(source_path, "word")

    if suffix == ".pdf":
        result = extract_office_document_content(source_path, "pdf")
        extraction_result = result.get("extraction_result")
        if extraction_result and extraction_result.extractor_name.startswith("mineru:") and has_suspicious_pdf_noise(extraction_result.extracted_text):
            fallback_result = extract_pdf_text(source_path)
            fallback_result.note = (
                f"{fallback_result.note} MinerU 提取结果疑似混入异常文本层，已回退本地解析。"
            ).strip()
            if not fallback_result.extracted_text.strip():
                raise RuntimeError(f"未能从 PDF 提取到可用文本：{fallback_result.note}")
            result["blocks"] = split_text_to_blocks(fallback_result.extracted_text)
            result["extracted_text"] = fallback_result.extracted_text
            result["extraction_note"] = clean_paragraph_text(fallback_result.note)
            result["auto_metadata"] = build_auto_metadata(source_path, result["blocks"], fallback_result)
            result["extraction_result"] = fallback_result
        is_heavy_pdf, heavy_pdf_reason = detect_heavy_pdf_layout(result["extracted_text"], result["blocks"])
        result["is_heavy_pdf"] = is_heavy_pdf
        result["heavy_pdf_reason"] = heavy_pdf_reason
        return result

    if suffix in {".ppt", ".pptx"}:
        return extract_office_document_content(source_path, "presentation")

    if suffix in {".xls", ".xlsx"}:
        return extract_office_document_content(source_path, "excel")

    raise ValueError(f"当前脚本暂不支持该文件类型：{source_path.suffix}")


# 解析命令行传入的 `键=值` 元数据，避免为每轮样本硬编码一套新字段。
def parse_metadata_pairs(raw_items: list[str]) -> list[tuple[str, str]]:
    parsed_items: list[tuple[str, str]] = []

    for raw_item in raw_items:
        if "=" not in raw_item:
            raise ValueError(f"元数据参数格式错误：{raw_item}，应为 键=值")
        key, value = raw_item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(f"元数据参数缺少字段名：{raw_item}")
        parsed_items.append((key, value))

    return parsed_items


# 解析命令行参数：支持 docx/pdf/pptx/xls/xlsx 单文件提取，也支持对重版式 PDF 切换到模型摘要模式。
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将 docx/pdf/pptx/xls/xlsx 或分页扫描图片目录样本提取为带元数据的 Markdown。")
    parser.add_argument("--source", required=True, help="源 docx/pdf/pptx/xls/xlsx 文件或分页扫描图片目录绝对路径")
    parser.add_argument("--output", required=True, help="输出 md 文件绝对路径")
    parser.add_argument(
        "--pdf-output-mode",
        choices=["fulltext", "summary", "auto"],
        default="fulltext",
        help="PDF 输出模式：fulltext 保留原文全量提取，summary 直接走模型摘要，auto 命中重版式特征时自动切到模型摘要。",
    )
    parser.add_argument("--qwen-api-key", help="覆盖配置文件中的 Qwen API Key。")
    parser.add_argument("--qwen-base-url", help="覆盖配置文件中的 Qwen 兼容接口地址。")
    parser.add_argument("--qwen-model", help="覆盖配置文件中的 Qwen 模型名。")
    parser.add_argument(
        "--discarded",
        nargs="*",
        default=[],
        help="未作为主抽取源的其他文件路径，可传多个",
    )
    parser.add_argument(
        "--meta",
        nargs="*",
        default=[],
        help="补充元数据，格式为 键=值，可传多个",
    )
    parser.add_argument(
        "--related-duplicates",
        nargs="*",
        default=[],
        help="关联近似重复版本文件路径，可传多个",
    )
    parser.add_argument(
        "--related-policies",
        nargs="*",
        default=[],
        help="关联政策依据文件路径，可传多个",
    )
    parser.add_argument(
        "--related-images",
        nargs="*",
        default=[],
        help="关联图件文件路径，可传多个",
    )
    parser.add_argument(
        "--selection-reason",
        default=DEFAULT_SELECTION_REASON,
        help="取舍说明",
    )
    return parser.parse_args()


# 主流程：先做稳定文本提取；PDF 再根据命令行模式和重版式判断决定输出原文版还是模型摘要版。
def main() -> None:
    args = parse_args()
    source_path = Path(args.source)
    output_path = Path(args.output)
    discarded_paths = [Path(path) for path in args.discarded]
    extra_metadata = parse_metadata_pairs(args.meta)
    related_duplicate_paths = [Path(path) for path in args.related_duplicates]
    related_policy_paths = [Path(path) for path in args.related_policies]
    related_image_paths = [Path(path) for path in args.related_images]

    if source_path.suffix.lower() != ".pdf" and args.pdf_output_mode != "fulltext":
        raise ValueError("当前 --pdf-output-mode 仅对 PDF 文件生效；其他文件类型请使用 fulltext 模式。")

    extraction = extract_source_content(source_path)
    extra_metadata = merge_metadata_items(extraction.get("auto_metadata", []), extra_metadata)
    selection_reason = extraction.get("selection_reason") or args.selection_reason
    use_summary_mode = should_use_pdf_summary_mode(
        source_path,
        args.pdf_output_mode,
        extraction["is_heavy_pdf"],
    )

    if use_summary_mode:
        qwen_runtime = resolve_qwen_runtime(
            enable_qwen=True,
            cli_api_key=args.qwen_api_key,
            cli_base_url=args.qwen_base_url,
            cli_model=args.qwen_model,
        )
        if not qwen_runtime:
            raise RuntimeError("当前输出模式需要 Qwen 运行时，请在配置文件.txt或命令行中提供 Qwen 的 api key、base url、model。")

        summary_payload = summarize_solution_document_with_qwen(
            source_path.name,
            extraction["extracted_text"],
            api_key=qwen_runtime["api_key"],
            base_url=qwen_runtime["base_url"],
            model=qwen_runtime["model"],
        )
        if not has_meaningful_summary_payload(summary_payload):
            raise RuntimeError("Qwen 未返回可用摘要结果，请检查接口配置或源文档提取文本。")

        markdown = build_summary_markdown(
            source_path,
            summary_payload,
            discarded_paths,
            selection_reason,
            extra_metadata,
            related_duplicate_paths,
            related_policy_paths,
            related_image_paths,
            summary_trigger=build_summary_trigger_reason(args.pdf_output_mode, extraction["heavy_pdf_reason"]),
            extraction_note=extraction["extraction_note"],
        )
    else:
        markdown = build_markdown(
            source_path,
            extraction["blocks"],
            discarded_paths,
            selection_reason,
            extra_metadata,
            related_duplicate_paths,
            related_policy_paths,
            related_image_paths,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")


if __name__ == "__main__":
    main()
