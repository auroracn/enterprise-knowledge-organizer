from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from minimum_workflow.contracts import (
    GENERATED_DIR,
    ExtractionResult,
    PipelineResult,
    SampleRecord,
    WorkflowContract,
)
from minimum_workflow.directory_extractors import extract_image_directory_content
from minimum_workflow.document_profiles import infer_document_profile, split_text_to_blocks
from minimum_workflow.extractors import extract_pdf_with_mineru, extract_pdf_with_mineru_ocr, extract_pdf_with_pypdf, extract_text
from minimum_workflow.mineru_large_file import (
    extract_large_file_via_split,
    is_mineru_page_limit_error,
    should_use_split_strategy,
)
from minimum_workflow.field_extractors import extract_fields
from minimum_workflow.markdown_templates import (
    build_markdown as render_structured_markdown,
    FIELD_DISPLAY_LABELS,
    SUPPLEMENTAL_FIELD_ORDER,
    TEMPLATE_PRIMARY_FIELDS,
    build_education_training_sections,
    build_generic_sections,
    build_policy_sections,
    build_procurement_sections,
    build_product_sections,
    build_contact_sections,
    build_solution_sections,
    build_supplier_sections,
    build_contract_sections,
    build_price_quote_sections,
    build_industry_knowledge_sections,
    build_supplemental_field_lines,
    format_markdown_value,
    is_empty_payload_value,
    parse_markdown_frontmatter,
)
from minimum_workflow.qwen_client import enrich_payload_with_qwen
from minimum_workflow.runtime_config import load_runtime_settings, resolve_llm_runtime


DIRECTORY_TYPE = "directory"
DIRECTORY_TEMPLATE_ALLOWLIST = {
    "政策官方文件模板",
    "方案案例模板",
    "产品设备模板",
    "单位联系人模板",
    "教育培训模板",
    "行业知识模板",
}
# MinerU 官方 API 直接受理的文档型格式：docx / doc / pptx / ppt / html 会被 MinerU 解析为
# 完整 Markdown，含正文、表格以及内嵌扫描图 OCR。本地 XML 解析只能读到文字层，
# 对"封面文字 + 扫描件数据页"这种混合检测报告会漏掉关键数据。
MINERU_DOCUMENT_FILE_TYPES = {"pdf", "word", "presentation", "html"}
FILE_TYPE_MAP = {
    ".pdf": "pdf",
    ".doc": "word",
    ".docx": "word",
    ".xls": "excel",
    ".xlsx": "excel",
    ".ppt": "presentation",
    ".pptx": "presentation",
    ".txt": "txt",
    ".md": "markdown",
    ".json": "json",
    ".csv": "csv",
    ".log": "log",
    ".html": "html",
    ".htm": "html",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
}

# MinerU 公开批量接口单文件上限约 200 MB，超过的文件回退到本地解析。
MINERU_SINGLE_FILE_MAX_BYTES = 200 * 1024 * 1024


def detect_file_type(source_path: Path) -> str:
    if source_path.is_dir():
        return DIRECTORY_TYPE
    return FILE_TYPE_MAP.get(source_path.suffix.lower(), "unknown")


def decide_processing_route(file_type: str) -> str:
    # 这里只决定处理路径，不在第二阶段里直接接入完整 OCR/解析链。
    if file_type in {"image"}:
        return "ocr"
    if file_type in {DIRECTORY_TYPE, "pdf", "word", "excel", "presentation"}:
        return "document_parse"
    if file_type in {"txt", "markdown", "json", "csv", "log"}:
        return "text_direct"
    return "manual_review"


def build_dedup_keys(sample: SampleRecord) -> list[str]:
    keys = [sample.subject_name_hint, sample.title_hint, sample.source_path]
    if sample.product_name_hint:
        keys.append(sample.product_name_hint)
    if sample.unit_name_hint:
        keys.append(sample.unit_name_hint)
    return [item for item in keys if item]


QWEN_CLASSIFICATION_KEYS = {
    "一级分类",
    "二级分类",
    "分类置信度",
    "分类依据",
    "文档分类",
    "推荐模板",
}


def merge_qwen_updates(payload: dict[str, Any], qwen_updates: dict[str, Any]) -> None:
    for key, value in qwen_updates.items():
        if key in QWEN_CLASSIFICATION_KEYS:
            payload[key] = value
            continue
        if is_empty_payload_value(payload.get(key)):
            payload[key] = value




TEMPLATE_FIELD_KEYS = {field for fields in TEMPLATE_PRIMARY_FIELDS.values() for field in fields}


def drop_stale_template_fields(payload: dict[str, Any], *, keep_keys: set[str]) -> None:
    for key in TEMPLATE_FIELD_KEYS:
        if key in keep_keys:
            continue
        payload.pop(key, None)


def should_skip_qwen_for_sample(
    sample: SampleRecord,
    payload: dict[str, Any] | None = None,
    file_type: str | None = None,
) -> bool:
    template_name = payload.get("推荐模板") if payload else sample.recommended_template
    evidence_boundary = (payload.get("证据边界") if payload else "") or ""
    if template_name == "政策官方文件模板":
        return True
    if file_type == DIRECTORY_TYPE and template_name not in DIRECTORY_TEMPLATE_ALLOWLIST:
        return True
    if file_type == DIRECTORY_TYPE and "会议/PPT/说明会类混合材料" in evidence_boundary:
        return True
    return False


# 目录自动判定可能会覆盖样例初始模板与标题提示，这里生成一份当前轮次实际生效的样例快照供后续字段规则复用。
def build_effective_sample(sample: SampleRecord, payload: dict[str, Any]) -> SampleRecord:
    title_hint = payload.get("标题") or sample.title_hint
    template_name = payload.get("推荐模板") or sample.recommended_template
    if sample.recommended_template == "待人工补规则" and template_name == "待人工补规则" and title_hint and sample.title_hint:
        title_hint = sample.title_hint
    return replace(
        sample,
        recommended_template=template_name,
        document_category=payload.get("文档分类") or sample.document_category,
        title_hint=title_hint,
        subject_name_hint=payload.get("主体名称") or sample.subject_name_hint,
        unit_name_hint=payload.get("单位名称") or sample.unit_name_hint,
    )


# 目录扫描生成的是泛化样本，这里对非目录单文件复用 sample_docx 的规则判型，补齐模板归属与元数据。
def build_auto_profile_payload(
    sample: SampleRecord,
    source_path: Path,
    extraction: ExtractionResult,
    file_type: str,
) -> dict[str, Any]:
    if sample.recommended_template != "待人工补规则":
        return {}
    if extraction.extra_metadata or not extraction.extracted_text.strip() or file_type == DIRECTORY_TYPE:
        return {}

    blocks = split_text_to_blocks(extraction.extracted_text)
    if not blocks:
        return {}
    profile = infer_document_profile(source_path.stem, blocks)
    if profile["模板归属"] == "待人工补规则":
        return {}

    source_form_map = {
        "txt": "文本文件",
        "markdown": "文本文件",
        "json": "文本文件",
        "csv": "文本文件",
        "log": "文本文件",
        "pdf": "PDF文档",
        "word": "Word文档",
        "excel": "Excel文档",
        "presentation": "演示文稿",
        "image": "单张图片文件",
    }
    auto_payload: dict[str, Any] = {
        "文档分类": profile["文档分类"],
        "推荐模板": profile["模板归属"],
        "模板归属": profile["模板归属"],
        "标题": profile["文件标题"],
        "文件标题": profile["文件标题"],
        "主体名称": profile["主体名称"],
        "资料层级": profile["资料层级"],
        "发布时间": profile["发布时间"],
        "版本信息": profile["版本信息"],
        "证据边界": profile["证据边界"],
        "来源形态": source_form_map.get(file_type, "文档文件"),
        "分流结果": "直接入" if profile["是否适合直接入Dify"] == "是" else "待审核",
        "是否适合直接入库": profile["是否适合直接入Dify"] == "是",
    }
    if profile["主体名称"]:
        auto_payload[profile["主体字段名"]] = profile["主体名称"]
        auto_payload["单位名称"] = profile["主体名称"]
    if profile["主体字段名"] == "发布单位":
        auto_payload["发文单位"] = profile["主体名称"]
        auto_payload["成文日期"] = profile["发布时间"]
    return auto_payload


# Qwen 只作为分类与字段补强层；未启用、未配置或调用失败时都必须保守回退，不影响主流程产物生成。
def resolve_qwen_runtime(
    *,
    enable_qwen: bool = False,
    qwen_api_key: str | None = None,
    qwen_base_url: str | None = None,
    qwen_model: str | None = None,
) -> dict[str, str]:
    settings = load_runtime_settings()
    runtime = resolve_llm_runtime(
        provider="qwen",
        api_key=qwen_api_key,
        base_url=qwen_base_url,
        model=qwen_model,
        settings=settings,
        allow_fallback=False,
    )
    if not enable_qwen or not runtime.is_usable():
        return {}
    return {
        "api_key": runtime.api_key,
        "base_url": runtime.base_url,
        "model": runtime.model,
    }


def decide_flow_result(sample: SampleRecord, extraction: ExtractionResult, payload: dict[str, Any] | None = None) -> str:
    if sample.fallback_decision == "跳过":
        return "跳过"
    if extraction.extraction_status == "跳过":
        return "跳过"
    if extraction.extraction_status in {"待OCR", "待人工复核", "源文件不存在"}:
        return "待审核"
    if payload and payload.get("分流结果") in {"直接入", "待审核", "跳过"}:
        return str(payload["分流结果"])
    return sample.fallback_decision


def extract_with_strategy(
    source_path: Path,
    file_type: str,
    *,
    pdf_extractor: str = "mineru",
    mineru_token: str | None = None,
    enable_ocr: bool = False,
    chunk_cache_dir: Path | None = None,
) -> ExtractionResult:
    if file_type == DIRECTORY_TYPE:
        directory_result = extract_image_directory_content(source_path, mineru_token=mineru_token)
        extracted_text = directory_result["extracted_text"]
        preview_text = extracted_text[:300].replace("\n", " ").strip()
        page_count_raw = (directory_result.get("auto_payload") or {}).get("OCR页数")
        page_count = int(page_count_raw) if str(page_count_raw or "").isdigit() else None
        return ExtractionResult(
            extractor_name="ocr:mineru:image_directory",
            extraction_status="已提取文本",
            extracted_text=extracted_text,
            preview_text=preview_text,
            text_length=len(extracted_text),
            page_count=page_count,
            source_encoding="utf-8",
            note=directory_result["extraction_note"],
            extra_metadata=directory_result.get("auto_payload"),
        )

    # docx / pptx / html 等文档型格式在 MinerU API 直接受理，MinerU 会同时处理文字层和内嵌扫描图 OCR；
    # 本地 XML 解析只能读到文字层，检测报告这种"封面文字 + 扫描数据页"会漏掉关键表格，因此有 token 时统一走 MinerU。
    if file_type in MINERU_DOCUMENT_FILE_TYPES and pdf_extractor == "mineru" and mineru_token:
        try:
            file_size = source_path.stat().st_size
        except OSError:
            file_size = 0
        if file_size and file_size > MINERU_SINGLE_FILE_MAX_BYTES:
            local_result = extract_text(source_path, file_type, enable_ocr=enable_ocr, ocr_token=mineru_token)
            local_result.note = (
                f"{local_result.note} 文件大小 {file_size / 1024 / 1024:.1f} MB 超过 MinerU 单文件上限 "
                f"{MINERU_SINGLE_FILE_MAX_BYTES / 1024 / 1024:.0f} MB，已回退本地解析。"
            ).strip()
            return local_result

        # >100MB docx/PDF 或 >100 页 PDF：走拆分链路（docx→PDF→切片→MinerU 批量并行），
        # 绕开 MinerU "200 页/文件"上限，失败回退整份上传。
        if should_use_split_strategy(source_path, file_type):
            try:
                return extract_large_file_via_split(
                    source_path, file_type, mineru_token,
                    cache_dir=chunk_cache_dir,
                )
            except Exception as exc:
                print(
                    f"[Pipeline] 大文件拆分链路失败，回退整份 MinerU：{exc}",
                    flush=True,
                )

        try:
            mineru_result = extract_pdf_with_mineru(source_path, mineru_token)
        except Exception as exc:
            local_result = extract_text(source_path, file_type, enable_ocr=enable_ocr, ocr_token=mineru_token)
            local_result.note = f"{local_result.note} MinerU 优先抽取失败，已回退本地解析：{exc}".strip()
            return local_result

        # 后置保险：MinerU 返回 "pages exceeds limit (200 pages)" 时，
        # 说明前置页数预估未命中（docProps/app.xml 没有 Pages 字段或 PDF 未预先计数），
        # 这里捕获错误字符串 → 自动回退到拆分链路补救。
        if is_mineru_page_limit_error(mineru_result.note):
            print(
                f"[Pipeline] MinerU 返回 200 页上限错误，自动回退拆分链路：{source_path.name}",
                flush=True,
            )
            try:
                return extract_large_file_via_split(
                    source_path, file_type, mineru_token,
                    cache_dir=chunk_cache_dir,
                )
            except Exception as exc:
                print(
                    f"[Pipeline] 拆分回退失败：{exc}",
                    flush=True,
                )
                mineru_result.note = (
                    f"{mineru_result.note} 页数上限回退拆分亦失败：{exc}"
                ).strip()

        # 统一把抽取器名改成对应的文档类型前缀，便于日志识别；pdf 路径保留稀疏文本 OCR 兜底。
        if file_type == "pdf":
            if enable_ocr and mineru_result.extraction_status in {"已提取文本", "待审核"}:
                local_text, local_pages, _ = extract_pdf_with_pypdf(source_path)
                page_count = local_pages or 0
                avg_chars = (len(mineru_result.extracted_text) / page_count) if page_count else len(mineru_result.extracted_text)
                if page_count > 0 and avg_chars < 120:
                    try:
                        ocr_result = extract_pdf_with_mineru_ocr(source_path, mineru_token, page_count=page_count)
                        if len(ocr_result.extracted_text) > len(mineru_result.extracted_text):
                            ocr_result.note = (
                                f"MinerU VLM 返回稀疏（平均 {avg_chars:.0f} 字/页，共 {page_count} 页），已切换 OCR 兜底。"
                                f" {ocr_result.note}"
                            ).strip()
                            return ocr_result
                    except Exception as exc:
                        mineru_result.note = f"{mineru_result.note} 稀疏文本 OCR 兜底失败：{exc}".strip()
        else:
            mineru_result.extractor_name = f"mineru:{file_type}"
            mineru_result.note = f"已通过 MinerU 完整解析 {file_type}（含正文、表格与内嵌扫描图 OCR）。{mineru_result.note}".strip()
        return mineru_result

    if file_type == "pdf" and pdf_extractor == "mineru" and not mineru_token:
        local_result = extract_text(source_path, file_type, enable_ocr=enable_ocr, ocr_token=mineru_token)
        local_result.note = f"{local_result.note} 未提供 MinerU token，已回退本地解析。".strip()
        return local_result
    return extract_text(source_path, file_type, enable_ocr=enable_ocr, ocr_token=mineru_token)



def build_structured_payload(
    sample: SampleRecord,
    contract: WorkflowContract,
    *,
    pdf_extractor: str = "local",
    mineru_token: str | None = None,
    enable_ocr: bool = False,
    enable_qwen: bool = False,
    qwen_api_key: str | None = None,
    qwen_base_url: str | None = None,
    qwen_model: str | None = None,
    chunk_cache_dir: Path | None = None,
) -> tuple[dict[str, Any], ExtractionResult]:
    # 第三阶段把 OCR 占位层与模板填充接起来：若抽取器已降级到 OCR，占位路由也同步切到 ocr。
    source_path = Path(sample.source_path)
    file_type = detect_file_type(source_path)
    processing_route = decide_processing_route(file_type)
    extraction = extract_with_strategy(
        source_path,
        file_type,
        pdf_extractor=pdf_extractor,
        mineru_token=mineru_token,
        enable_ocr=enable_ocr,
        chunk_cache_dir=chunk_cache_dir,
    )
    if extraction.extractor_name.startswith("ocr:"):
        processing_route = "ocr"
    if extraction.extractor_name.startswith("skip:"):
        processing_route = "skip"
    if extraction.extractor_name.startswith("素材:"):
        processing_route = "素材"

    markdown_frontmatter: dict[str, str] = {}
    markdown_body_text = extraction.extracted_text
    if file_type == "markdown":
        markdown_frontmatter, markdown_body_text = parse_markdown_frontmatter(extraction.extracted_text)
        if markdown_body_text != extraction.extracted_text:
            extraction = ExtractionResult(
                extractor_name=extraction.extractor_name,
                extraction_status=extraction.extraction_status,
                extracted_text=markdown_body_text,
                preview_text=markdown_body_text[:300].replace("\n", " ").strip(),
                text_length=len(markdown_body_text),
                page_count=extraction.page_count,
                source_encoding=extraction.source_encoding,
                note=extraction.note,
                extra_metadata=extraction.extra_metadata,
            )

    auto_payload = build_auto_profile_payload(sample, source_path, extraction, file_type)
    if extraction.extra_metadata:
        auto_payload.update(extraction.extra_metadata)
    payload = {
        "原始文件名": source_path.name,
        "原始路径": str(source_path),
        "文件格式": source_path.suffix.lower().lstrip("."),
        "文件类型": file_type if file_type != DIRECTORY_TYPE else "image_directory",
        "处理路径": processing_route,
        "文档分类": sample.document_category,
        "推荐模板": sample.recommended_template,
        "主体名称": sample.subject_name_hint,
        "产品名称": sample.product_name_hint,
        "单位名称": sample.unit_name_hint,
        "标题": sample.title_hint,
        "核心摘要": extraction.preview_text,
        "提取正文": extraction.extracted_text,
        "内容主题标签": sample.tags,
        "证据等级": sample.evidence_level,
        "处理状态": extraction.extraction_status,
        "抽取状态": extraction.extraction_status,
        "抽取器": extraction.extractor_name,
        "文本预览": extraction.preview_text,
        "文本长度": extraction.text_length,
        "页数": extraction.page_count or "",
        "文本编码": extraction.source_encoding,
        "抽取说明": extraction.note,
        "版本信息": contract.version,
        "去重主键": build_dedup_keys(sample),
        "是否适合直接入库": False,
        "是否需要拆分": sample.split_required,
        "拆分说明": sample.split_note,
        "分流结果": sample.fallback_decision,
        "风险说明": sample.risks,
        "备注": sample.notes,
        "生成时间": datetime.now().isoformat(timespec="seconds"),
        "原始Markdown元数据": markdown_frontmatter,
    }
    payload.update(auto_payload)
    if file_type == "markdown":
        markdown_template_hint = str(markdown_frontmatter.get("推荐模板") or "").strip()
        markdown_category_hint = str(markdown_frontmatter.get("文档分类") or "").strip()
        if markdown_template_hint:
            payload["推荐模板"] = markdown_template_hint
        if markdown_category_hint:
            payload["文档分类"] = markdown_category_hint

    effective_sample = build_effective_sample(sample, payload)
    extracted_fields = extract_fields(effective_sample, extraction)
    payload.update(extracted_fields)
    if not payload.get("文件标题") and payload.get("标题"):
        payload["文件标题"] = payload["标题"]

    flow_result = decide_flow_result(sample, extraction, payload)
    payload["分流结果"] = flow_result
    payload["是否适合直接入库"] = flow_result == "直接入"

    qwen_runtime = resolve_qwen_runtime(
        enable_qwen=enable_qwen,
        qwen_api_key=qwen_api_key,
        qwen_base_url=qwen_base_url,
        qwen_model=qwen_model,
    )
    if not enable_qwen:
        print(f"[Pipeline] Qwen 未启用，{sample.sample_id} 走纯规则链路", flush=True)
    elif not qwen_runtime:
        print(f"[Pipeline] Qwen 已勾选但凭据不完整，{sample.sample_id} 回退纯规则链路", flush=True)
    if enable_qwen and qwen_runtime and not should_skip_qwen_for_sample(effective_sample, payload, file_type=file_type):
        try:
            qwen_updates = enrich_payload_with_qwen(
                effective_sample,
                extraction,
                payload,
                api_key=qwen_runtime["api_key"],
                base_url=qwen_runtime["base_url"],
                model=qwen_runtime["model"],
            )
            previous_category = payload.get("文档分类")
            previous_template = payload.get("推荐模板")
            merge_qwen_updates(payload, qwen_updates)
            template_changed = payload.get("推荐模板") != previous_template
            category_changed = payload.get("文档分类") != previous_category
            if template_changed or category_changed:
                effective_sample = build_effective_sample(sample, payload)
                refreshed_fields = extract_fields(effective_sample, extraction)
                if template_changed:
                    drop_stale_template_fields(payload, keep_keys=set(qwen_updates) | set(refreshed_fields))
                payload.update(refreshed_fields)
                if not payload.get("文件标题") and payload.get("标题"):
                    payload["文件标题"] = payload["标题"]
                flow_result = decide_flow_result(sample, extraction, payload)
                payload["分流结果"] = flow_result
                payload["是否适合直接入库"] = flow_result == "直接入"
        except Exception as exc:
            payload["抽取说明"] = f"{payload['抽取说明']} Qwen补强未生效：{exc}".strip()

    for field in contract.minimum_json_fields:
        payload.setdefault(field, "")
    return payload, extraction


def build_markdown(sample: SampleRecord, payload: dict[str, Any]) -> str:
    return render_structured_markdown(sample, payload)


def build_status_payload(sample: SampleRecord, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_id": sample.sample_id,
        "source_exists": Path(sample.source_path).exists(),
        "processing_route": payload["处理路径"],
        "status": payload["处理状态"],
        "decision": payload["分流结果"],
        "extractor": payload["抽取器"],
        "text_length": payload["文本长度"],
        "page_count": payload["页数"],
        "text_encoding": payload["文本编码"],
        "extraction_note": payload["抽取说明"],
        "generated_at": payload["生成时间"],
    }


def run_pipeline(
    sample: SampleRecord,
    contract: WorkflowContract,
    *,
    pdf_extractor: str = "local",
    mineru_token: str | None = None,
    enable_ocr: bool = False,
    enable_qwen: bool = False,
    qwen_api_key: str | None = None,
    qwen_base_url: str | None = None,
    qwen_model: str | None = None,
    output_root: Path | None = None,
    chunk_cache_dir: Path | None = None,
) -> PipelineResult:
    # 每个样例单独输出到固定目录，便于后续批量执行和人工复核回流。
    output_dir = (output_root or GENERATED_DIR) / sample.sample_id
    output_dir.mkdir(parents=True, exist_ok=True)

    payload, extraction = build_structured_payload(
        sample,
        contract,
        pdf_extractor=pdf_extractor,
        mineru_token=mineru_token,
        enable_ocr=enable_ocr,
        enable_qwen=enable_qwen,
        qwen_api_key=qwen_api_key,
        qwen_base_url=qwen_base_url,
        qwen_model=qwen_model,
        chunk_cache_dir=chunk_cache_dir,
    )
    markdown_content = build_markdown(sample, payload)
    status_payload = build_status_payload(sample, payload)

    structured_json_path = output_dir / "structured.json"
    structured_markdown_path = output_dir / "structured.md"
    status_path = output_dir / "status.json"
    extracted_text_path = output_dir / "extracted.txt"

    structured_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    structured_markdown_path.write_text(markdown_content, encoding="utf-8")
    status_path.write_text(json.dumps(status_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    extracted_text_path.write_text(extraction.extracted_text, encoding="utf-8")

    # 素材类图片：将原图另存为 jpg 到输出目录，便于后续归档与检索。
    if payload.get("处理路径") == "素材":
        src = Path(sample.source_path)
        if src.exists():
            dest = output_dir / (src.stem + ".jpg")
            if src.suffix.lower() in {".jpg", ".jpeg"}:
                shutil.copy2(src, dest)
            else:
                try:
                    from PIL import Image as _PILImage
                    with _PILImage.open(src) as img:
                        img.convert("RGB").save(dest, "JPEG", quality=90)
                except Exception:
                    shutil.copy2(src, output_dir / src.name)

    return PipelineResult(
        sample_id=sample.sample_id,
        output_dir=output_dir,
        structured_json_path=structured_json_path,
        structured_markdown_path=structured_markdown_path,
        status_path=status_path,
        extracted_text_path=extracted_text_path,
    )
