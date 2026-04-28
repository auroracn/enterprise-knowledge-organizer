from __future__ import annotations

import re
import os
from pathlib import Path
from typing import Any

from minimum_workflow.document_profiles import infer_document_profile, split_text_to_blocks
from minimum_workflow.extractors import is_document_like_image, run_mineru_batch
from minimum_workflow.runtime_config import get_runtime_setting, load_runtime_settings

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
DIRECTORY_PAGE_IMAGE_KEYWORDS = ("封面", "目录", "页", "page", "scan", "扫描")
DIRECTORY_SCREENSHOT_KEYWORDS = ("微信图片", "mmexport")
DIRECTORY_PHOTO_KEYWORDS = (
    "照片",
    "图片",
    "现场",
    "航拍",
    "实拍",
    "合影",
    "活动",
    "宣传图",
    "效果图",
    "配图",
    "img",
    "dji",
)


def resolve_mineru_token(cli_token: str | None) -> str | None:
    if cli_token:
        return cli_token

    env_token = os.getenv("MINERU_TOKEN")
    if env_token:
        return env_token

    settings = load_runtime_settings()
    return get_runtime_setting(
        "mineru_token",
        "mineru token",
        "mineru_vlm_key",
        "mineru vlm大模型 用于转换md格式key",
        settings=settings,
    )


# 目录型图片先按页码和封面排序，保证合并后的正文顺序稳定。
def sort_directory_image_key(path: Path) -> tuple[int, int, str]:
    stem = path.stem.lower()
    numbers = re.findall(r"\d+", stem)
    first_number = int(numbers[0]) if numbers else 10**9
    cover_bias = -1 if "封面" in path.stem else 0
    return first_number, cover_bias, path.name.lower()


# 收集目录里的分页图片，当前只接受常见图片格式。
def collect_directory_image_paths(source_dir: Path) -> list[Path]:
    return sorted(
        [path for path in source_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES],
        key=sort_directory_image_key,
    )


# 判断单张图片文件名是否更像分页扫描件，而不是现场照片素材。
def is_directory_page_image(path: Path) -> bool:
    stem = path.stem.lower()
    if any(keyword in stem for keyword in DIRECTORY_SCREENSHOT_KEYWORDS):
        return True
    if any(keyword in stem for keyword in DIRECTORY_PHOTO_KEYWORDS):
        return False
    if re.match(r"^\d{1,4}", stem):
        return True
    return any(keyword in stem for keyword in DIRECTORY_PAGE_IMAGE_KEYWORDS)


# 除分页命名外，再结合图像内容特征识别文档截图，避免把微信截图类扫描文档误判成纯照片。
def is_directory_document_image(path: Path) -> bool:
    if is_directory_page_image(path):
        return True
    return is_document_like_image(path)


# 目录级样本先做保守判断：满足分页命名特征或文档截图特征时才进入整目录 OCR，否则按纯照片目录拒绝处理。
def classify_image_directory(source_dir: Path) -> tuple[list[Path], str]:
    image_paths = collect_directory_image_paths(source_dir)
    if not image_paths:
        raise ValueError(f"目录内未找到可处理图片：{source_dir}")

    directory_name = source_dir.name.lower()
    directory_has_photo_keyword = any(keyword in directory_name for keyword in DIRECTORY_PHOTO_KEYWORDS)
    page_like_count = sum(1 for path in image_paths if is_directory_page_image(path))
    document_like_count = sum(1 for path in image_paths if is_directory_document_image(path))
    photo_like_count = sum(1 for path in image_paths if any(keyword in path.stem.lower() for keyword in DIRECTORY_PHOTO_KEYWORDS))
    total_count = len(image_paths)
    page_ratio = page_like_count / total_count
    document_ratio = document_like_count / total_count
    photo_ratio = photo_like_count / total_count
    reasons = [f"分页命名图片 {page_like_count}/{total_count}", f"文档型图片 {document_like_count}/{total_count}"]
    if any("封面" in path.stem for path in image_paths):
        reasons.append("命中封面页")
    if photo_like_count:
        reasons.append(f"照片类命名图片 {photo_like_count}/{total_count}")
    if directory_has_photo_keyword:
        reasons.append("目录名命中照片类关键词")

    if total_count >= 3 and page_ratio >= 0.6 and photo_ratio <= 0.2 and not directory_has_photo_keyword:
        return image_paths, "；".join(reasons)
    if total_count >= 2 and document_ratio >= 0.8:
        reasons.append("图像内容更像文档截图/扫描页")
        return image_paths, "；".join(reasons)

    raise RuntimeError(
        "当前目录更像纯照片目录，脚本已拒绝自动抽取：" + "；".join(reasons) + "。如确认属于扫描文档，请先补更明确的分页命名规则。"
    )


# 对分页扫描图片目录统一走整目录 OCR，并自动生成目录级元数据，避免人工逐张处理。
def extract_image_directory_content(
    source_dir: Path,
    mineru_token: str | None = None,
    *,
    token_resolver=resolve_mineru_token,
    batch_runner=run_mineru_batch,
) -> dict[str, Any]:
    image_paths, directory_reason = classify_image_directory(source_dir)
    mineru_token = mineru_token or token_resolver(None)
    if not mineru_token:
        raise RuntimeError("图片目录样本提取依赖 MinerU OCR，请先提供 MinerU token。")

    batch_result = batch_runner(image_paths, mineru_token, poll_interval_seconds=5, max_polls=120)
    state_counts: dict[str, int] = {}
    failed_pages: list[str] = []
    page_texts: list[str] = []
    for path, result in zip(image_paths, batch_result["results"]):
        state = result.get("state", "unknown")
        state_counts[state] = state_counts.get(state, 0) + 1
        markdown = result.get("markdown", "").strip()
        if markdown:
            page_texts.append(markdown)
        elif state != "done":
            failed_pages.append(path.name)

    extracted_text = "\n\n".join(page_texts).strip()
    if not extracted_text:
        raise RuntimeError("目录 OCR 未返回可用正文，当前无法生成样本 Markdown。")

    blocks = split_text_to_blocks(extracted_text)
    profile = infer_document_profile(source_dir.name, blocks)
    state_summary = "；".join(f"{key}={value}" for key, value in sorted(state_counts.items()))
    failed_summary = "、".join(failed_pages) if failed_pages else "无"
    extraction_note = f"分页扫描目录已按页序完成 OCR；{directory_reason}；批次号：{batch_result['batch_id']}。"
    selection_reason = f"该目录被判定为同一文档的分页扫描目录（{directory_reason}），已按页序统一 OCR 提取，不按纯照片目录跳过。"
    auto_metadata = [
        ("文档分类", profile["文档分类"]),
        ("模板归属", profile["模板归属"]),
        ("文件标题", profile["文件标题"]),
        (profile["主体字段名"], profile["主体名称"]),
        ("发布时间", profile["发布时间"]),
        ("资料层级", profile["资料层级"]),
        ("版本信息", profile["版本信息"]),
        ("来源形态", "分页扫描图片目录"),
        ("目录判定", "分页扫描文档目录"),
        ("判定依据", directory_reason),
        ("证据边界", profile["证据边界"]),
        ("转换状态", "图片目录按页序合并后经 MinerU OCR 提取"),
        ("解析备注", extraction_note),
        ("OCR页数", str(len(image_paths))),
        ("OCR结果概况", state_summary),
        ("OCR失败页", failed_summary),
        ("是否适合直接入Dify", profile["是否适合直接入Dify"]),
    ]
    auto_payload = {
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
        "来源形态": "分页扫描图片目录",
        "目录判定": "分页扫描文档目录",
        "判定依据": directory_reason,
        "OCR页数": str(len(image_paths)),
        "OCR结果概况": state_summary,
        "OCR失败页": failed_summary,
        "取舍说明": selection_reason,
        "分流结果": "直接入" if profile["是否适合直接入Dify"] == "是" else "待审核",
        "是否适合直接入库": profile["是否适合直接入Dify"] == "是",
    }
    if profile["主体字段名"] == "发布单位":
        auto_payload["发文单位"] = profile["主体名称"]
        auto_payload["单位名称"] = profile["主体名称"]
        auto_payload["成文日期"] = profile["发布时间"]
    else:
        auto_payload[profile["主体字段名"]] = profile["主体名称"]
        auto_payload["单位名称"] = profile["主体名称"]
    return {
        "blocks": blocks,
        "extracted_text": extracted_text,
        "is_heavy_pdf": False,
        "heavy_pdf_reason": "",
        "extraction_note": extraction_note,
        "auto_metadata": auto_metadata,
        "auto_payload": auto_payload,
        "selection_reason": selection_reason,
    }
