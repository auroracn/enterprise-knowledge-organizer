from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from minimum_workflow.contracts import SampleRecord
from minimum_workflow.pipeline import build_markdown as render_structured_markdown


REVIEW_FILE_NAME = "structured.review.json"
IMPORT_MARKDOWN_FILE_NAME = "structured.import.md"
MERGED_JSON_FILE_NAME = "structured.merged.json"
MERGED_MARKDOWN_FILE_NAME = "structured.merged.md"
STRUCTURED_JSON_FILE_NAME = "structured.json"

REVIEW_FIELD_NAMES = (
    "知识库分类",
    "分类来源",
    "人工审核状态",
    "人工审核时间",
    "目标知识库ID列表",
    "导入状态",
    "导入批次号",
)


def _read_json(file_path: Path) -> dict[str, Any]:
    if not file_path.exists():
        return {}
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(file_path: Path, payload: dict[str, Any]) -> None:
    file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_dataset_ids(dataset_ids: list[str] | tuple[str, ...] | str | None) -> list[str]:
    if dataset_ids is None:
        return []
    if isinstance(dataset_ids, str):
        raw_items = [item.strip() for item in dataset_ids.split(",")]
    else:
        raw_items = [str(item).strip() for item in dataset_ids]

    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def get_review_overlay_path(structured_json_path: Path | str) -> Path:
    target = Path(structured_json_path)
    if target.name != STRUCTURED_JSON_FILE_NAME:
        target = target / STRUCTURED_JSON_FILE_NAME
    return target.with_name(REVIEW_FILE_NAME)


def get_import_markdown_path(structured_json_path: Path | str) -> Path:
    target = Path(structured_json_path)
    if target.name != STRUCTURED_JSON_FILE_NAME:
        target = target / STRUCTURED_JSON_FILE_NAME
    return target.with_name(IMPORT_MARKDOWN_FILE_NAME)


def get_merged_json_path(structured_json_path: Path | str) -> Path:
    target = Path(structured_json_path)
    if target.name != STRUCTURED_JSON_FILE_NAME:
        target = target / STRUCTURED_JSON_FILE_NAME
    return target.with_name(MERGED_JSON_FILE_NAME)


def get_merged_markdown_path(structured_json_path: Path | str) -> Path:
    target = Path(structured_json_path)
    if target.name != STRUCTURED_JSON_FILE_NAME:
        target = target / STRUCTURED_JSON_FILE_NAME
    return target.with_name(MERGED_MARKDOWN_FILE_NAME)


def load_structured_payload(structured_json_path: Path | str) -> dict[str, Any]:
    return _read_json(Path(structured_json_path))


def load_review_overlay(structured_json_path: Path | str) -> dict[str, Any]:
    review_path = get_review_overlay_path(structured_json_path)
    review_payload = _read_json(review_path)
    normalized = {field_name: review_payload.get(field_name, "") for field_name in REVIEW_FIELD_NAMES}
    normalized["目标知识库ID列表"] = _normalize_dataset_ids(review_payload.get("目标知识库ID列表"))
    return normalized


def infer_auto_category(payload: dict[str, Any]) -> str:
    for key in ("二级分类", "一级分类", "文档分类", "推荐模板"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return "待分类"


def build_effective_payload(structured_json_path: Path | str) -> dict[str, Any]:
    base_payload = load_structured_payload(structured_json_path)
    review_payload = load_review_overlay(structured_json_path)
    effective_payload = deepcopy(base_payload)

    auto_category = infer_auto_category(base_payload)
    effective_payload["知识库分类"] = str(review_payload.get("知识库分类") or effective_payload.get("知识库分类") or auto_category)
    effective_payload["分类来源"] = str(review_payload.get("分类来源") or effective_payload.get("分类来源") or "自动推断")
    effective_payload["人工审核状态"] = str(review_payload.get("人工审核状态") or effective_payload.get("人工审核状态") or "")
    effective_payload["人工审核时间"] = str(review_payload.get("人工审核时间") or effective_payload.get("人工审核时间") or "")
    effective_payload["目标知识库ID列表"] = _normalize_dataset_ids(
        review_payload.get("目标知识库ID列表") or effective_payload.get("目标知识库ID列表")
    )
    effective_payload["导入状态"] = str(review_payload.get("导入状态") or effective_payload.get("导入状态") or "")
    effective_payload["导入批次号"] = str(review_payload.get("导入批次号") or effective_payload.get("导入批次号") or "")
    return effective_payload


def build_sample_record_from_payload(structured_json_path: Path | str, payload: dict[str, Any]) -> SampleRecord:
    source_path = str(payload.get("原始路径") or Path(structured_json_path).with_name("unknown"))
    title_hint = str(payload.get("标题") or payload.get("文件标题") or Path(source_path).stem)
    return SampleRecord(
        sample_id=Path(structured_json_path).parent.name,
        source_path=source_path,
        document_category=str(payload.get("文档分类") or "待判定资料"),
        recommended_template=str(payload.get("推荐模板") or "待人工补规则"),
        title_hint=title_hint,
        subject_name_hint=str(payload.get("主体名称") or ""),
        product_name_hint=str(payload.get("产品名称") or ""),
        unit_name_hint=str(payload.get("单位名称") or ""),
        tags=[str(item) for item in (payload.get("内容主题标签") or []) if str(item).strip()],
        risks=[str(item) for item in (payload.get("风险说明") or []) if str(item).strip()],
        notes=[str(item) for item in (payload.get("备注") or []) if str(item).strip()],
        evidence_level=str(payload.get("证据等级") or "L3"),
        fallback_decision=str(payload.get("分流结果") or "待审核"),
        split_required=bool(payload.get("是否需要拆分")),
        split_note=str(payload.get("拆分说明") or ""),
        relative_path_hint=str(payload.get("源文件相对路径") or ""),
    )


def render_import_markdown(structured_json_path: Path | str) -> Path:
    structured_path = Path(structured_json_path)
    effective_payload = build_effective_payload(structured_path)
    sample = build_sample_record_from_payload(structured_path, effective_payload)
    markdown_content = render_structured_markdown(sample, effective_payload)
    import_path = get_import_markdown_path(structured_path)
    import_path.write_text(markdown_content, encoding="utf-8")
    return import_path


def save_review_overlay(
    structured_json_path: Path | str,
    *,
    category: str,
    dataset_ids: list[str] | tuple[str, ...] | str,
    review_status: str = "已审核",
    classification_source: str = "人工审核",
) -> Path:
    structured_path = Path(structured_json_path)
    existing_overlay = load_review_overlay(structured_path)
    normalized_category = str(category or "").strip()
    if not normalized_category:
        raise ValueError("人工审核时必须提供知识库分类。")

    overlay_payload = {
        **existing_overlay,
        "知识库分类": normalized_category,
        "分类来源": classification_source,
        "人工审核状态": review_status,
        "人工审核时间": datetime.now().isoformat(timespec="seconds"),
        "目标知识库ID列表": _normalize_dataset_ids(dataset_ids),
        "导入状态": str(existing_overlay.get("导入状态") or ""),
        "导入批次号": str(existing_overlay.get("导入批次号") or ""),
    }
    review_path = get_review_overlay_path(structured_path)
    _write_json(review_path, overlay_payload)
    return review_path


def update_import_overlay(
    structured_json_path: Path | str,
    *,
    import_status: str,
    import_batch_id: str = "",
    dataset_ids: list[str] | tuple[str, ...] | str | None = None,
    category: str | None = None,
    classification_source: str | None = None,
) -> Path:
    structured_path = Path(structured_json_path)
    base_payload = load_structured_payload(structured_path)
    existing_overlay = load_review_overlay(structured_path)
    overlay_payload = {
        **existing_overlay,
        "知识库分类": str(category or existing_overlay.get("知识库分类") or infer_auto_category(base_payload)),
        "分类来源": str(classification_source or existing_overlay.get("分类来源") or "自动推断"),
        "人工审核状态": str(existing_overlay.get("人工审核状态") or ""),
        "人工审核时间": str(existing_overlay.get("人工审核时间") or ""),
        "目标知识库ID列表": _normalize_dataset_ids(dataset_ids or existing_overlay.get("目标知识库ID列表")),
        "导入状态": import_status,
        "导入批次号": import_batch_id,
    }
    review_path = get_review_overlay_path(structured_path)
    _write_json(review_path, overlay_payload)
    return review_path


def review_is_ready(structured_json_path: Path | str) -> bool:
    review_payload = load_review_overlay(structured_json_path)
    return bool(
        str(review_payload.get("人工审核状态") or "").strip() == "已审核"
        and str(review_payload.get("知识库分类") or "").strip()
        and _normalize_dataset_ids(review_payload.get("目标知识库ID列表"))
    )


def merge_review_outputs(structured_json_path: Path | str) -> tuple[Path, Path]:
    structured_path = Path(structured_json_path)
    effective_payload = build_effective_payload(structured_path)
    sample = build_sample_record_from_payload(structured_path, effective_payload)
    merged_json_path = get_merged_json_path(structured_path)
    merged_markdown_path = get_merged_markdown_path(structured_path)
    _write_json(merged_json_path, effective_payload)
    merged_markdown_path.write_text(render_structured_markdown(sample, effective_payload), encoding="utf-8")
    return merged_json_path, merged_markdown_path
