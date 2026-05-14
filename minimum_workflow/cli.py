from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from minimum_workflow.contracts import GENERATED_DIR, SampleRecord, get_sample_by_id, load_contract, load_samples
from minimum_workflow.detection_report_module import (
    build_classifier_json,
    process_with_details as process_detection_report,
)
from minimum_workflow.parameter_letter_module import (
    build_parameter_classifier_json,
    process_parameter_letter,
)
from minimum_workflow.directory_extractors import classify_image_directory
from minimum_workflow.extractors import should_skip_image_file
from minimum_workflow.pipeline import detect_file_type, run_pipeline
from minimum_workflow.ragflow_import_service import (
    RagflowApiError,
    RagflowClient,
    RagflowRuntime,
    batch_upload_to_ragflow,
    resolve_ragflow_runtime,
    upload_markdown_to_ragflow,
)
from minimum_workflow.runtime_config import get_runtime_setting, load_runtime_settings, resolve_llm_runtime


def _emit_detection_subreports(final_markdown_path: Path, source_path: Path) -> None:
    """读已产出的整份 MD，命中检测报告分类时额外写子报告 MD 及分类器明细 JSON。
    未命中时继续尝试参数确认函分类器（独立模块）。
    """
    markdown = final_markdown_path.read_text(encoding="utf-8", errors="ignore")
    source_meta = {
        "source_file": source_path.name,
        "source_path": str(source_path),
        "extract_time": datetime.now().isoformat(timespec="seconds"),
    }
    cls, outputs, subs = process_detection_report(markdown, source_meta)
    if outputs:
        sub_dir = final_markdown_path.parent / f"{final_markdown_path.stem}_子报告"
        sub_dir.mkdir(parents=True, exist_ok=True)
        for fname, body in outputs:
            (sub_dir / fname).write_text(body, encoding="utf-8")
        classifier_payload = build_classifier_json(cls, subs, source_meta)
        (sub_dir / "_classifier.json").write_text(
            json.dumps(classifier_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            f"[检测报告] 整篇 score={cls.score}/8 weighted={cls.weighted_score} "
            f"conf={cls.confidence} → 切出 {len(outputs)} 份子报告 → {sub_dir}",
            flush=True,
        )
        return

    # 检测报告未命中 → 尝试参数确认函
    pcls, poutputs, letters = process_parameter_letter(markdown, source_meta)
    if poutputs:
        letter_dir = final_markdown_path.parent / f"{final_markdown_path.stem}_参数确认函"
        letter_dir.mkdir(parents=True, exist_ok=True)
        for fname, body in poutputs:
            (letter_dir / fname).write_text(body, encoding="utf-8")
        payload = build_parameter_classifier_json(pcls, letters, source_meta)
        (letter_dir / "_classifier.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            f"[参数确认函] 整篇 score={pcls.score}/8 weighted={pcls.weighted_score} "
            f"conf={pcls.confidence} → 切出 {len(poutputs)} 份 → {letter_dir}",
            flush=True,
        )


def build_parser() -> argparse.ArgumentParser:
    # CLI 先提供列样例、单样例执行、全量首轮样例执行三种最小能力，并允许切换 PDF 抽取策略。
    parser = argparse.ArgumentParser(description="长风最小闭环处理骨架")
    parser.add_argument("--sample-id", help="指定要处理的样例 ID")
    parser.add_argument("--all", action="store_true", help="处理全部首轮样例")
    parser.add_argument("--list", action="store_true", help="列出全部样例")
    parser.add_argument("--source-dir", help="指定要扫描的源目录绝对路径")
    parser.add_argument("--output-dir", help="目录扫描输出根目录；默认写入 .omc/generated/directory_scan")
    parser.add_argument(
        "--internal-output-dir",
        help="目录扫描内部结构化产物输出目录；未传时默认写入 .omc/generated/directory_scan/<scan_id>",
    )
    parser.add_argument(
        "--pdf-extractor",
        choices=["local", "mineru"],
        default="mineru",
        help="指定 PDF 抽取策略：默认 mineru 优先；未配 token 或失败时回退本地解析，local 为仅走本地解析。",
    )
    parser.add_argument(
        "--mineru-token",
        help="MinerU token；未传时尝试读取环境变量 MINERU_TOKEN。",
    )
    parser.add_argument("--enable-ocr", action="store_true", help="对文档型图片和扫描型 PDF 启用真实 OCR fallback。")
    parser.add_argument("--enable-qwen", action="store_true", help="启用 Qwen 分类与字段补强。")
    parser.add_argument("--qwen-api-key", help="覆盖配置文件中的 Qwen API Key。")
    parser.add_argument("--qwen-base-url", help="覆盖配置文件中的 Qwen 兼容接口地址。")
    parser.add_argument("--qwen-model", help="覆盖配置文件中的 Qwen 模型名。")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="重跑模式：仅处理上轮 scan_report.json 中 status=failed 的源文件；"
             "大文件拆分链路复用 chunk cache 跳过已完成分片。",
    )
    parser.add_argument(
        "--upload-to-ragflow",
        action="store_true",
        help="处理完成后自动上传生成的 Markdown 到 RAGFlow 知识库。",
    )
    parser.add_argument(
        "--ragflow-api-url",
        help="RAGFlow API 地址；未传时尝试读取配置文件或环境变量 RAGFLOW_API_URL。",
    )
    parser.add_argument(
        "--ragflow-api-key",
        help="RAGFlow API Key；未传时尝试读取配置文件或环境变量 RAGFLOW_API_KEY。",
    )
    parser.add_argument(
        "--ragflow-dataset-id",
        help="指定 RAGFlow 目标知识库 ID；未传时使用配置文件中的默认知识库。",
    )
    return parser


def list_samples() -> int:
    for sample in load_samples():
        print(f"{sample.sample_id}\t{sample.recommended_template}\t{sample.source_path}")
    return 0


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


def resolve_qwen_runtime(
    *,
    enable_qwen: bool,
    cli_api_key: str | None,
    cli_base_url: str | None,
    cli_model: str | None,
) -> dict[str, str]:
    settings = load_runtime_settings()
    runtime = resolve_llm_runtime(
        provider="qwen",
        api_key=cli_api_key,
        base_url=cli_base_url,
        model=cli_model,
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


def resolve_ragflow_config(
    *,
    cli_api_url: str | None = None,
    cli_api_key: str | None = None,
    cli_dataset_id: str | None = None,
) -> dict[str, str] | None:
    """解析 RAGFlow 配置，返回配置字典或 None。"""
    settings = load_runtime_settings()
    runtime = resolve_ragflow_runtime(
        api_url=cli_api_url or "",
        api_key=cli_api_key or "",
        default_dataset_ids=cli_dataset_id or "",
    )
    if not runtime:
        return None
    result = {
        "api_url": runtime.api_url,
        "api_key": runtime.api_key,
        "verify_ssl": str(runtime.verify_ssl),
    }
    if cli_dataset_id:
        result["dataset_id"] = cli_dataset_id
    elif runtime.default_dataset_ids:
        result["dataset_id"] = runtime.default_dataset_ids[0]
    return result


def upload_to_ragflow(
    markdown_files: list[Path],
    ragflow_config: dict[str, str],
) -> dict[str, Any]:
    """上传 Markdown 文件到 RAGFlow 知识库。"""
    dataset_id = ragflow_config.get("dataset_id")
    if not dataset_id:
        return {"status": "error", "error": "未指定 RAGFlow 知识库 ID"}

    runtime = RagflowRuntime(
        api_url=ragflow_config["api_url"],
        api_key=ragflow_config["api_key"],
        default_dataset_ids=[dataset_id],
        verify_ssl=ragflow_config.get("verify_ssl", "true").lower() in {"true", "1", "yes"},
    )
    client = RagflowClient(runtime)

    def progress_callback(payload: dict[str, Any]) -> None:
        print(f"[RAGFlow] {payload.get('message', '')}", flush=True)

    results = batch_upload_to_ragflow(
        client,
        dataset_id,
        markdown_files,
        progress_callback=progress_callback,
    )

    success_count = sum(1 for r in results if r["status"] == "success")
    failed_count = sum(1 for r in results if r["status"] == "failed")

    return {
        "status": "completed",
        "dataset_id": dataset_id,
        "total": len(markdown_files),
        "success": success_count,
        "failed": failed_count,
        "results": results,
    }


def run_one(
    sample_id: str,
    *,
    pdf_extractor: str,
    mineru_token: str | None,
    enable_ocr: bool,
    enable_qwen: bool,
    qwen_runtime: dict[str, str],
) -> int:
    contract = load_contract()
    sample = get_sample_by_id(sample_id)
    result = run_pipeline(
        sample,
        contract,
        pdf_extractor=pdf_extractor,
        mineru_token=mineru_token,
        enable_ocr=enable_ocr,
        enable_qwen=enable_qwen,
        qwen_api_key=qwen_runtime.get("api_key"),
        qwen_base_url=qwen_runtime.get("base_url"),
        qwen_model=qwen_runtime.get("model"),
    )
    print(f"已生成: {result.sample_id} -> {result.output_dir}")
    return 0



def run_all(
    *,
    pdf_extractor: str,
    mineru_token: str | None,
    enable_ocr: bool,
    enable_qwen: bool,
    qwen_runtime: dict[str, str],
) -> int:
    contract = load_contract()
    for sample in load_samples():
        result = run_pipeline(
            sample,
            contract,
            pdf_extractor=pdf_extractor,
            mineru_token=mineru_token,
            enable_ocr=enable_ocr,
            enable_qwen=enable_qwen,
            qwen_api_key=qwen_runtime.get("api_key"),
            qwen_base_url=qwen_runtime.get("base_url"),
            qwen_model=qwen_runtime.get("model"),
        )
        print(f"已生成: {result.sample_id} -> {result.output_dir}")
    return 0


SCAN_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


# 仅当目录直接文件里基本都是分页图片时，才把它视为整目录 OCR 候选；混合了 PDF/Word 的资料目录仍按单文件处理。
def is_image_directory_candidate(path: Path) -> bool:
    direct_images = [child for child in path.iterdir() if child.is_file() and child.suffix.lower() in SCAN_IMAGE_SUFFIXES]
    if len(direct_images) < 2:
        return False

    direct_non_image_files = []
    for child in path.iterdir():
        if not child.is_file() or child.suffix.lower() in SCAN_IMAGE_SUFFIXES:
            continue
        if child.name in PROCESS_ARTIFACT_SKIP_RULES:
            continue
        if detect_file_type(child) == "unknown":
            continue
        direct_non_image_files.append(child)
    return not direct_non_image_files


# 目录扫描时把相对路径稳定转成 sample_id，避免覆盖不同子目录同名文件。
def build_scan_sample_id(relative_path: Path) -> str:
    raw = relative_path.as_posix()
    if relative_path.suffix:
        raw = raw[: -len(relative_path.suffix)]
    normalized = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", raw, flags=re.UNICODE).strip("_")
    return f"scan_{normalized or 'item'}"


# 同一目录下若存在同名不同后缀文件，补一个后缀标识，避免目录扫描产物互相覆盖。
def collect_duplicate_scan_sample_ids(scan_sources: list[Path], source_dir: Path) -> set[str]:
    counts: dict[str, int] = {}
    for source_path in scan_sources:
        relative_path = source_path.relative_to(source_dir)
        sample_id = build_scan_sample_id(relative_path)
        counts[sample_id] = counts.get(sample_id, 0) + 1
    return {sample_id for sample_id, count in counts.items() if count > 1}




# 同目录同名近似稿默认优先保留可直接抽取的源文件版本，避免让用户在 doc/pdf 成对稿之间重复核对。
SCAN_SOURCE_SUFFIX_PRIORITY = {
    ".docx": 0,
    ".doc": 1,
    ".xlsx": 2,
    ".xls": 3,
    ".pptx": 4,
    ".ppt": 5,
    ".pdf": 10,
}


def select_preferred_scan_sources(source_dir: Path, scan_sources: list[Path]) -> tuple[list[Path], list[dict[str, str]]]:
    grouped_sources: dict[tuple[str, str], list[Path]] = {}
    for source_path in scan_sources:
        if not source_path.is_file():
            grouped_sources[(str(source_path), source_path.name)] = [source_path]
            continue
        try:
            relative_parent = str(source_path.parent.relative_to(source_dir)).replace("\\", "/")
        except ValueError:
            relative_parent = str(source_path.parent).replace("\\", "/")
        grouped_sources.setdefault((relative_parent, source_path.stem), []).append(source_path)

    selected_sources: list[Path] = []
    skipped_items: list[dict[str, str]] = []
    for grouped_paths in grouped_sources.values():
        if len(grouped_paths) == 1:
            selected_sources.extend(grouped_paths)
            continue

        preferred_source = min(
            grouped_paths,
            key=lambda path: (
                SCAN_SOURCE_SUFFIX_PRIORITY.get(path.suffix.lower(), 100),
                len(path.name),
                path.name.lower(),
            ),
        )
        selected_sources.append(preferred_source)
        for skipped_source in grouped_paths:
            if skipped_source == preferred_source:
                continue
            skipped_items.append(
                {
                    "status": "skipped_duplicate",
                    "source_path": str(skipped_source),
                    "preferred_source_path": str(preferred_source),
                    "reason": "同目录同名近似稿，按优先级 docx>doc>xlsx>xls>pptx>ppt>pdf 保留最高优先级版本，其余跳过。",
                }
            )

    return sorted(selected_sources, key=lambda item: str(item)), sorted(
        skipped_items,
        key=lambda item: (item["preferred_source_path"], item["source_path"]),
    )


SKIP_ADMIN_KEYWORDS = (
    "劳动合同",
    "_保单_",
    "保单",
)
PROCESS_ARTIFACT_SKIP_RULES = {
    "链路说明.md": "链路说明.md 为过程说明文件，不纳入终稿抽取。",
    "skipped_files.csv": "skipped_files.csv 为过程记录文件，不纳入终稿抽取。",
}


def _is_admin_credential_file(source_path: Path) -> bool:
    # 劳动合同与保单属于内部行政凭证，不纳入知识库提取。
    name = source_path.name
    return any(kw in name for kw in SKIP_ADMIN_KEYWORDS)


def should_skip_scan_source(source_path: Path, *, enable_ocr: bool = False) -> tuple[bool, str]:
    process_artifact_reason = PROCESS_ARTIFACT_SKIP_RULES.get(source_path.name)
    if process_artifact_reason:
        return True, process_artifact_reason
    if _is_admin_credential_file(source_path):
        return True, f"{source_path.name} 属于内部行政凭证（劳动合同/保单），不纳入知识库提取。"
    file_type = detect_file_type(source_path)
    if file_type == "image" and should_skip_image_file(source_path):
        return True, f"图片文件{source_path.name}当前按纯照片处理，直接跳过，不进入 OCR。"
    return False, ""


# 目录扫描时递归收集可处理来源；纯照片默认跳过并写入扫描报告，分页图片目录整体作为一个来源，其余按单文件处理。
def collect_scan_sources_with_skips(source_dir: Path, *, enable_ocr: bool = False) -> tuple[list[Path], list[dict[str, str]]]:
    skipped_items: list[dict[str, str]] = []
    if is_image_directory_candidate(source_dir):
        try:
            classify_image_directory(source_dir)
        except RuntimeError as exc:
            skipped_items.append(
                {
                    "status": "skipped_photo",
                    "source_path": str(source_dir),
                    "reason": str(exc),
                }
            )
            return [], skipped_items
        return [source_dir], skipped_items

    scan_sources: list[Path] = []
    for child in sorted(source_dir.rglob("*"), key=lambda item: str(item)):
        if not child.is_file():
            continue
        file_type = detect_file_type(child)
        if file_type == "unknown":
            continue
        should_skip, reason = should_skip_scan_source(child, enable_ocr=enable_ocr)
        if should_skip:
            skipped_items.append(
                {
                    "status": "skipped_photo" if file_type == "image" else "skipped_non_source",
                    "source_path": str(child),
                    "reason": reason,
                }
            )
            continue
        scan_sources.append(child)
    return scan_sources, skipped_items


# 兼容既有调用：默认只返回可处理来源列表。
def collect_scan_sources(source_dir: Path, *, enable_ocr: bool = False) -> list[Path]:
    scan_sources, _ = collect_scan_sources_with_skips(source_dir, enable_ocr=enable_ocr)
    return scan_sources


# 目录扫描来源转成临时样本记录，供统一主链路继续处理。
def build_scanned_sample(
    source_path: Path,
    source_dir: Path,
    *,
    duplicate_sample_ids: set[str] | None = None,
) -> SampleRecord:
    relative_path = source_path.relative_to(source_dir)
    sample_id = build_scan_sample_id(relative_path)
    if duplicate_sample_ids and sample_id in duplicate_sample_ids and source_path.is_file() and source_path.suffix:
        suffix_token = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", source_path.suffix.lower().lstrip("."), flags=re.UNICODE).strip("_")
        if suffix_token:
            sample_id = f"{sample_id}_{suffix_token}"
    title_hint = source_path.stem if source_path.is_file() else source_path.name
    return SampleRecord(
        sample_id=sample_id,
        source_path=str(source_path),
        document_category="待判定资料",
        recommended_template="待人工补规则",
        title_hint=title_hint,
        subject_name_hint="",
        product_name_hint="",
        unit_name_hint="",
        tags=["目录扫描", "自动判型"],
        risks=["目录扫描自动生成样本，模板归属与字段需结合原文复核。"],
        notes=["由目录扫描入口自动生成。"],
        evidence_level="L3",
        fallback_decision="待审核",
        split_required=False,
        split_note="",
        relative_path_hint=str(relative_path).replace("\\", "/"),
    )


WEBPAGE_FILENAME_FRAGMENT_RE = re.compile(
    r"^(?:查看全文|阅读全文|点击查看(?:全文)?|点击阅读全文|更多详情|详情(?:页)?|正文)$"
)



def sanitize_review_markdown_stem(stem: str, fallback_stem: str = "") -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "_", stem).strip()
    cleaned = cleaned.strip("[]【】_- ")
    if WEBPAGE_FILENAME_FRAGMENT_RE.fullmatch(cleaned):
        cleaned = ""
    if cleaned:
        return cleaned
    fallback = re.sub(r"[\\/:*?\"<>|]+", "_", fallback_stem).strip()
    fallback = fallback.strip("[]【】_- ")
    return fallback or "未命名文档"



def build_review_markdown_name(
    source_path: Path,
    source_dir: Path | None = None,
    duplicate_relative_stems: set[str] | None = None,
    *,
    inferred_title: str | None = None,
) -> str:
    fallback_stem = source_path.parent.name if source_path.parent != source_dir else ""
    cleaned_stem = sanitize_review_markdown_stem(source_path.stem, fallback_stem)

    # 如果推断出的标题更有语义，且当前文件名是弱语义占位名，优先用推断标题
    if inferred_title and cleaned_stem in {"未命名文档", fallback_stem}:
        title_stem = re.sub(r"[\\/:*?\"<>|]+", "_", inferred_title).strip()
        title_stem = title_stem.strip("[]【】_- ")[:100]  # 限制长度避免文件名过长
        if title_stem and len(title_stem) > 3:
            cleaned_stem = title_stem

    if source_dir and duplicate_relative_stems:
        try:
            relative_path = source_path.relative_to(source_dir)
        except ValueError:
            relative_path = source_path
        relative_parent = str(relative_path.parent).replace("\\", "/")
        relative_stem = cleaned_stem if relative_parent in {"", "."} else f"{relative_parent}/{cleaned_stem}"
        if relative_stem in duplicate_relative_stems:
            safe_relative_stem = relative_stem.replace("/", "__")
            return f"{safe_relative_stem}.md"
    return f"{cleaned_stem}.md"


def iter_review_markdown_cleanup_paths(
    review_output_root: Path,
    source_path: Path,
    source_dir: Path,
    duplicate_relative_stems: set[str],
) -> list[Path]:
    cleanup_paths: list[Path] = []
    final_markdown_path = review_output_root / build_review_markdown_name(
        source_path,
        source_dir,
        duplicate_relative_stems,
    )
    cleanup_paths.append(final_markdown_path)
    legacy_markdown_path = review_output_root / f"{source_path.stem}.md"
    if legacy_markdown_path not in cleanup_paths:
        cleanup_paths.append(legacy_markdown_path)
    return cleanup_paths



def cleanup_review_outputs(
    review_output_root: Path,
    source_dir: Path,
    skipped_items: list[dict[str, str]],
    duplicate_relative_stems: set[str],
) -> None:
    for item in skipped_items:
        source_path_raw = item.get("source_path")
        if not source_path_raw:
            continue
        source_path = Path(source_path_raw)
        if not source_path.exists() and not str(source_path).startswith(str(source_dir)):
            continue
        for cleanup_path in iter_review_markdown_cleanup_paths(
            review_output_root,
            source_path,
            source_dir,
            duplicate_relative_stems,
        ):
            if cleanup_path.exists():
                cleanup_path.unlink()


# ---------------------------------------------------------------------------
# F 类：断点续跑 / 失败重试
# ---------------------------------------------------------------------------

def load_previous_failed_sources(internal_output_root: Path) -> set[str]:
    """读上一次 scan_report.json 中 status=failed 的 source_path 集合。

    返回空集合意味着：文件不存在、解析失败，或上轮没有失败项。
    """
    report_path = internal_output_root / "scan_report.json"
    if not report_path.exists():
        return set()
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    items = payload.get("items") or []
    return {
        str(item.get("source_path") or "")
        for item in items
        if isinstance(item, dict) and item.get("status") == "failed" and item.get("source_path")
    }


def write_failed_to_retry_csv(
    internal_output_root: Path,
    failed_items: list[dict[str, str]],
) -> Path | None:
    """把本轮 status=failed 的条目写成 `failed_to_retry.csv`，供下一轮 `--resume` 读取。

    空列表时不产出文件（避免遗留误导）。
    """
    if not failed_items:
        # 清理遗留文件
        stale = internal_output_root / "failed_to_retry.csv"
        if stale.exists():
            stale.unlink()
        return None
    csv_path = internal_output_root / "failed_to_retry.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=["sample_id", "source_path", "error"])
        writer.writeheader()
        for item in failed_items:
            writer.writerow({
                "sample_id": item.get("sample_id", ""),
                "source_path": item.get("source_path", ""),
                "error": (item.get("error") or "")[:500],  # 截断超长 traceback
            })
    return csv_path


def chunk_cache_dir_for_sample(internal_output_root: Path, sample_id: str) -> Path:
    """大文件拆分链路的 chunk cache 路径：按样本 id 分桶，跨轮复用。"""
    safe_id = re.sub(r"[^\w一-鿿-]+", "_", sample_id, flags=re.UNICODE).strip("_") or "sample"
    return internal_output_root / "chunk_cache" / safe_id


NON_FINAL_EXTRACTION_STATUSES = {"待OCR", "待人工复核", "源文件不存在"}


def should_publish_review_markdown(structured_json_path: Path) -> tuple[bool, str]:
    if not structured_json_path.exists():
        return True, ""
    try:
        payload = json.loads(structured_json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"结构化结果读取失败：{exc}"

    extraction_status = str(payload.get("抽取状态") or payload.get("处理状态") or "").strip()
    if extraction_status in NON_FINAL_EXTRACTION_STATUSES:
        return False, f"抽取状态为{extraction_status}，当前仅保留内部结构化产物，不发布 Claude输出 终稿。"

    return True, ""



def run_source_dir(
    source_dir: Path,
    *,
    output_dir: Path | None,
    internal_output_dir: Path | None = None,
    pdf_extractor: str,
    mineru_token: str | None,
    enable_ocr: bool,
    enable_qwen: bool,
    qwen_runtime: dict[str, str],
    resume: bool = False,
    ragflow_config: dict[str, str] | None = None,
) -> int:
    contract = load_contract()
    qwen_banner = "启用" if enable_qwen and qwen_runtime else ("勾选但凭据不全，跳过" if enable_qwen else "未启用")
    print(
        f"[CLI] 目录扫描启动 | PDF 策略={pdf_extractor} | OCR={'启用' if enable_ocr else '未启用'} "
        f"| Qwen={qwen_banner} | resume={'on' if resume else 'off'} | 来源={source_dir}",
        flush=True,
    )
    review_output_root = output_dir or (GENERATED_DIR / "directory_review_markdown")
    internal_output_root = internal_output_dir or (GENERATED_DIR / "directory_scan" / build_scan_sample_id(source_dir))
    try:
        source_root = source_dir.resolve()
        review_root_resolved = review_output_root.resolve(strict=False)
        internal_root_resolved = internal_output_root.resolve(strict=False)
    except OSError as exc:
        raise RuntimeError(f"目录路径解析失败: {exc}") from exc
    if review_root_resolved == source_root or source_root in review_root_resolved.parents:
        raise ValueError(f"输出目录不能位于源目录内部: {review_output_root}")
    if internal_root_resolved == source_root or source_root in internal_root_resolved.parents:
        raise ValueError(f"内部输出目录不能位于源目录内部: {internal_output_root}")
    review_output_root.mkdir(parents=True, exist_ok=True)
    internal_output_root.mkdir(parents=True, exist_ok=True)

    # resume：读上一轮 scan_report.json，只处理 status=failed 的源文件
    previously_failed: set[str] = set()
    if resume:
        previously_failed = load_previous_failed_sources(internal_output_root)
        if not previously_failed:
            print(
                f"[CLI] --resume 模式但未找到上轮失败条目（{internal_output_root}\\scan_report.json），退出。",
                flush=True,
            )
            return 0
        print(f"[CLI] --resume：上轮失败 {len(previously_failed)} 个，仅重跑这些源文件。", flush=True)

    scan_sources, all_skipped_items = collect_scan_sources_with_skips(source_dir, enable_ocr=enable_ocr)
    if not scan_sources and not all_skipped_items:
        print(f"未发现可处理文件: {source_dir}")
        return 1
    skipped_photo_items = [item for item in all_skipped_items if item.get("status") == "skipped_photo"]
    skipped_non_source_items = [item for item in all_skipped_items if item.get("status") == "skipped_non_source"]
    selected_scan_sources, skipped_duplicate_items = select_preferred_scan_sources(source_dir, scan_sources)

    # resume：去重后按上轮失败 source_path 过滤
    if resume:
        selected_scan_sources = [p for p in selected_scan_sources if str(p) in previously_failed]
        if not selected_scan_sources:
            print("[CLI] --resume：上轮失败条目与当前源目录无交集，退出。", flush=True)
            return 0

    duplicate_sample_ids = collect_duplicate_scan_sample_ids(selected_scan_sources, source_dir)
    relative_stem_counts: dict[str, int] = {}
    for source_path in selected_scan_sources:
        try:
            relative_stem = str(source_path.relative_to(source_dir).with_suffix("")).replace("\\", "/")
        except ValueError:
            relative_stem = str(source_path.with_suffix("")).replace("\\", "/")
        stem_only = source_path.stem
        relative_stem_counts[stem_only] = relative_stem_counts.get(stem_only, 0) + 1
    duplicate_relative_stems: set[str] = set()
    for source_path in selected_scan_sources:
        if relative_stem_counts.get(source_path.stem, 0) <= 1:
            continue
        try:
            relative_stem = str(source_path.relative_to(source_dir).with_suffix("")).replace("\\", "/")
        except ValueError:
            relative_stem = str(source_path.with_suffix("")).replace("\\", "/")
        duplicate_relative_stems.add(relative_stem)

    report_items: list[dict[str, str]] = [*skipped_photo_items, *skipped_non_source_items, *skipped_duplicate_items]
    cleanup_review_outputs(review_output_root, source_dir, report_items, duplicate_relative_stems)
    success_count = 0
    failed_count = 0
    skipped_duplicate_count = len(skipped_duplicate_items)
    skipped_photo_count = len(skipped_photo_items)
    skipped_non_source_count = len(skipped_non_source_items)
    for source_path in selected_scan_sources:
        sample = build_scanned_sample(source_path, source_dir, duplicate_sample_ids=duplicate_sample_ids)
        try:
            result = run_pipeline(
                sample,
                contract,
                pdf_extractor=pdf_extractor,
                mineru_token=mineru_token,
                enable_ocr=enable_ocr,
                enable_qwen=enable_qwen,
                qwen_api_key=qwen_runtime.get("api_key"),
                qwen_base_url=qwen_runtime.get("base_url"),
                qwen_model=qwen_runtime.get("model"),
                output_root=internal_output_root,
                chunk_cache_dir=chunk_cache_dir_for_sample(internal_output_root, sample.sample_id),
            )

            # 尝试从 structured.json 读取推断的文件标题，用于改善弱语义文件名
            inferred_title = None
            try:
                if result.structured_json_path.exists():
                    payload = json.loads(result.structured_json_path.read_text(encoding="utf-8"))
                    inferred_title = payload.get("文件标题") or payload.get("标题")
            except (OSError, json.JSONDecodeError):
                pass

            final_markdown_path = review_output_root / build_review_markdown_name(
                source_path,
                source_dir,
                duplicate_relative_stems,
                inferred_title=inferred_title,
            )
            should_publish, publish_note = should_publish_review_markdown(result.structured_json_path)
            if not should_publish:
                for cleanup_path in iter_review_markdown_cleanup_paths(
                    review_output_root,
                    source_path,
                    source_dir,
                    duplicate_relative_stems,
                ):
                    if cleanup_path.exists():
                        cleanup_path.unlink()
                failed_count += 1
                report_items.append(
                    {
                        "status": "failed",
                        "sample_id": result.sample_id,
                        "source_path": str(source_path),
                        "error": publish_note,
                    }
                )
                print(f"未发布终稿MD: {source_path.name} | {publish_note}")
                continue

            for cleanup_path in iter_review_markdown_cleanup_paths(
                review_output_root,
                source_path,
                source_dir,
                duplicate_relative_stems,
            ):
                if cleanup_path != final_markdown_path and cleanup_path.exists():
                    cleanup_path.unlink()
            shutil.copy2(result.structured_markdown_path, final_markdown_path)
            success_count += 1
            report_items.append(
                {
                    "status": "success",
                    "sample_id": result.sample_id,
                    "source_path": str(source_path),
                    "structured_markdown_path": str(final_markdown_path),
                }
            )
            print(f"已生成终稿MD: {source_path.name} -> {final_markdown_path}")

            # 检测报告独立模块：整份 MD 命中后额外产出子报告 MD。
            # 不破坏主 MD 产出，只做增量；子报告放 `<主MD文件名>_子报告/` 同级子目录。
            try:
                _emit_detection_subreports(final_markdown_path, source_path)
            except Exception as exc:
                print(f"[检测报告子报告切分] 失败（不影响主 MD）：{source_path.name} | {exc}", flush=True)
        except Exception as exc:
            failed_count += 1
            report_items.append(
                {
                    "status": "failed",
                    "sample_id": sample.sample_id,
                    "source_path": str(source_path),
                    "error": str(exc),
                }
            )
            print(f"处理失败: {sample.sample_id} -> {source_path} | {exc}")

    report_path = internal_output_root / "scan_report.json"
    report_payload = {
        "source_dir": str(source_dir),
        "review_output_dir": str(review_output_root),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_count": len(scan_sources) + skipped_photo_count + skipped_non_source_count,
        "selected_count": len(selected_scan_sources),
        "success_count": success_count,
        "failed_count": failed_count,
        "skipped_duplicate_count": skipped_duplicate_count,
        "skipped_photo_count": skipped_photo_count,
        "skipped_non_source_count": skipped_non_source_count,
        "items": report_items,
    }
    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # failed_to_retry.csv：只列本轮 status=failed，供下一轮 `--resume` 快速核对
    failed_items = [item for item in report_items if item.get("status") == "failed"]
    csv_path = write_failed_to_retry_csv(internal_output_root, failed_items)
    if csv_path:
        print(f"失败重试清单: {csv_path}")
    print(f"目录扫描完成: {source_dir} -> {report_path}")

    # RAGFlow 上传：处理完成后将成功的 Markdown 文件上传到 RAGFlow 知识库
    if ragflow_config and success_count > 0:
        print(f"\n[RAGFlow] 开始上传 {success_count} 个 Markdown 文件到 RAGFlow...", flush=True)
        successful_markdown_files = []
        for item in report_items:
            if item.get("status") == "success" and item.get("structured_markdown_path"):
                md_path = Path(item["structured_markdown_path"])
                if md_path.exists():
                    successful_markdown_files.append(md_path)

        if successful_markdown_files:
            try:
                ragflow_result = upload_to_ragflow(successful_markdown_files, ragflow_config)
                print(f"[RAGFlow] 上传完成: 成功 {ragflow_result['success']}/{ragflow_result['total']}", flush=True)
                if ragflow_result.get("failed", 0) > 0:
                    print(f"[RAGFlow] 警告: {ragflow_result['failed']} 个文件上传失败", flush=True)
            except Exception as exc:
                print(f"[RAGFlow] 上传过程出错: {exc}", flush=True)
        else:
            print("[RAGFlow] 没有找到需要上传的 Markdown 文件", flush=True)

    return 0 if failed_count == 0 else 1


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    mineru_token = resolve_mineru_token(args.mineru_token)
    qwen_runtime = resolve_qwen_runtime(
        enable_qwen=args.enable_qwen,
        cli_api_key=args.qwen_api_key,
        cli_base_url=args.qwen_base_url,
        cli_model=args.qwen_model,
    )
    ragflow_config = resolve_ragflow_config(
        cli_api_url=args.ragflow_api_url,
        cli_api_key=args.ragflow_api_key,
        cli_dataset_id=args.ragflow_dataset_id,
    )

    if (args.output_dir or args.internal_output_dir) and not args.source_dir:
        parser.error("--output-dir 和 --internal-output-dir 仅可与 --source-dir 一起使用。")
    if args.source_dir and (args.list or args.all or args.sample_id):
        parser.error("--source-dir 不能与 --list、--all 或 --sample-id 同时使用。")
    if args.enable_ocr and not mineru_token:
        parser.error("启用 --enable-ocr 时，必须通过 --mineru-token 或环境变量 MINERU_TOKEN 提供 token。")
    if args.enable_qwen and not qwen_runtime:
        parser.error("启用 --enable-qwen 时，必须在配置文件.txt或命令行中提供 Qwen 的 api key、base url、model。")
    if args.upload_to_ragflow and not ragflow_config:
        parser.error("启用 --upload-to-ragflow 时，必须通过命令行或配置文件提供 RAGFlow 的 api url 和 api key。")

    if args.list:
        return list_samples()
    if args.all:
        return run_all(
            pdf_extractor=args.pdf_extractor,
            mineru_token=mineru_token,
            enable_ocr=args.enable_ocr,
            enable_qwen=args.enable_qwen,
            qwen_runtime=qwen_runtime,
        )
    if args.sample_id:
        return run_one(
            args.sample_id,
            pdf_extractor=args.pdf_extractor,
            mineru_token=mineru_token,
            enable_ocr=args.enable_ocr,
            enable_qwen=args.enable_qwen,
            qwen_runtime=qwen_runtime,
        )
    if args.source_dir:
        source_dir = Path(args.source_dir).expanduser()
        if not source_dir.exists():
            parser.error(f"--source-dir 不存在: {source_dir}")
        if not source_dir.is_dir():
            parser.error(f"--source-dir 不是目录: {source_dir}")

        output_dir = Path(args.output_dir).expanduser() if args.output_dir else None
        internal_output_dir = Path(args.internal_output_dir).expanduser() if args.internal_output_dir else None
        run_source_kwargs = {
            "output_dir": output_dir,
            "pdf_extractor": args.pdf_extractor,
            "mineru_token": mineru_token,
            "enable_ocr": args.enable_ocr,
            "enable_qwen": args.enable_qwen,
            "qwen_runtime": qwen_runtime,
            "resume": args.resume,
        }
        if internal_output_dir is not None:
            run_source_kwargs["internal_output_dir"] = internal_output_dir
        if args.upload_to_ragflow and ragflow_config:
            run_source_kwargs["ragflow_config"] = ragflow_config
        return run_source_dir(source_dir, **run_source_kwargs)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
