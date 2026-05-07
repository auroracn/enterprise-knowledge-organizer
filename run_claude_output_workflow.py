from __future__ import annotations

import argparse
import csv
import json
import random
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from minimum_workflow.cli import build_scan_sample_id, resolve_mineru_token, resolve_qwen_runtime, run_source_dir
from minimum_workflow.contracts import GENERATED_DIR

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "Claude输出"
SKIPPED_FILE_NAME = "skipped_files.csv"
TRACE_FILE_NAME = "链路说明.md"


@dataclass(slots=True)
class AcceptanceCheckResult:
    source_path: str
    markdown_path: str
    sample_id: str
    checked_count: int
    passed_count: int
    passed: bool
    snippets: list[str]
    missing_snippets: list[str]
    note: str = ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="长风规范兼容包装脚本")
    parser.add_argument("source_dir", help="待处理目录绝对路径")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="Claude输出根目录")
    parser.add_argument("--pdf-extractor", choices=["local", "mineru"], default="mineru")
    parser.add_argument("--mineru-token")
    parser.add_argument("--enable-ocr", action="store_true")
    parser.add_argument("--enable-qwen", action="store_true")
    parser.add_argument("--qwen-api-key")
    parser.add_argument("--qwen-base-url")
    parser.add_argument("--qwen-model")
    return parser


def sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "_", value).strip()
    return cleaned or "未命名目录"


def build_review_output_dir(source_dir: Path, output_root: Path) -> Path:
    drive = source_dir.drive.rstrip(":") if source_dir.drive else "root"
    return output_root / f"{sanitize_name(drive)}_{sanitize_name(source_dir.name)}"


def build_internal_output_root(source_dir: Path) -> Path:
    return GENERATED_DIR / "directory_scan" / build_scan_sample_id(source_dir)


def load_report(report_path: Path) -> dict:
    return json.loads(report_path.read_text(encoding="utf-8"))


def write_skipped_files_csv(source_dir: Path, report: dict) -> Path:
    csv_path = source_dir / SKIPPED_FILE_NAME
    skipped_items = [
        item
        for item in report.get("items", [])
        if item.get("status") in {"skipped_duplicate", "skipped_non_source", "skipped_photo", "failed"}
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["status", "source_path", "preferred_source_path", "reason", "error"],
        )
        writer.writeheader()
        for item in skipped_items:
            writer.writerow(
                {
                    "status": item.get("status", ""),
                    "source_path": item.get("source_path", ""),
                    "preferred_source_path": item.get("preferred_source_path", ""),
                    "reason": item.get("reason", ""),
                    "error": item.get("error", ""),
                }
            )
    return csv_path


def normalize_candidate_line(raw_line: str) -> str:
    line = re.sub(r"\s+", " ", raw_line).strip()
    line = re.sub(r"^[#>*\s]+", "", line)
    line = re.sub(r"^(?:[-+•·●○■□▪▸▶►◆◇※]|[0-9]+[.、)]|[（(][0-9一二三四五六七八九十]+[)）]|[一二三四五六七八九十]+[、.])\s*", "", line)
    return line.strip()


ATTACHMENT_HEADING_RE = re.compile(r"^(?:附(?:件|录)|附表|附图|附件清单|目录)\s*[一二三四五六七八九十0-9]*[、:：\-—.]?.*")


def is_attachment_heading(line: str) -> bool:
    if not line:
        return False
    if ATTACHMENT_HEADING_RE.fullmatch(line):
        return True
    return bool(re.fullmatch(r"附件\s*[一二三四五六七八九十0-9]+", line))


def is_metadata_like_line(line: str) -> bool:
    if line.startswith(("原始", "文件", "文档分类", "发布时间", "提取时间", "源文件名", "源文件相对路径", "文档类别", "提取时间戳")):
        return True
    if "：" in line and len(line) <= 24:
        return True
    if re.fullmatch(r"[0-9一二三四五六七八九十、.()（）\- ]+", line):
        return True
    return False


def build_candidate_fragments(line: str) -> list[str]:
    fragments: list[str] = []
    for part in re.split(r"[。；!！?？]", line):
        part = part.strip().rstrip("，,;；。.!！?？")
        if 12 <= len(part) <= 40:
            fragments.append(part)
    if fragments:
        return fragments
    compact = line.rstrip("，,;；。.!！?？")
    if 12 <= len(compact) <= 40:
        return [compact]
    if len(compact) > 40:
        comma_parts = [part.strip() for part in re.split(r"[，,；;]", compact) if part.strip()]
        stable_parts = [part.rstrip("，,;；。.!！?？") for part in comma_parts if 14 <= len(part) <= 40]
        if stable_parts:
            return stable_parts
        return [compact[:40].rstrip("，,;；。.!！?？")]
    return []


def candidate_excerpt_lines(text: str) -> list[str]:
    primary_candidates: list[str] = []
    fallback_candidates: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = normalize_candidate_line(raw_line)
        if not line or line.startswith("|"):
            continue
        if is_metadata_like_line(line) or is_attachment_heading(line):
            continue
        fragments = build_candidate_fragments(line)
        if not fragments and 8 <= len(line) <= 60 and re.search(r"[一-鿿]", line):
            fragments = [line.rstrip("，,;；。.!！?？")]
        for fragment in fragments:
            if fragment in seen:
                continue
            seen.add(fragment)
            target = primary_candidates if len(fragment) >= 12 else fallback_candidates
            target.append(fragment)
    return primary_candidates + fallback_candidates


def pick_acceptance_snippets(text: str, *, seed: str, count: int = 3) -> list[str]:
    candidates = candidate_excerpt_lines(text)
    if not candidates:
        return []
    rng = random.Random(seed)
    if len(candidates) <= count:
        return candidates
    primary = [item for item in candidates if len(item) >= 12]
    fallback = [item for item in candidates if len(item) < 12]
    selected: list[str] = []
    if len(primary) >= count:
        return rng.sample(primary, count)
    if primary:
        selected.extend(rng.sample(primary, len(primary)))
    remaining = count - len(selected)
    if remaining > 0 and fallback:
        selected.extend(rng.sample(fallback, min(remaining, len(fallback))))
    return selected


def normalize_acceptance_text(text: str) -> str:
    return re.sub(r"[\s|｜/\\\-–—_:：,，;；。.!！?？()（）\[\]{}•·●○■□▪▸▶►◆◇※]+", "", text)


def is_table_heavy_markdown(text: str) -> bool:
    table_lines = [line for line in text.splitlines() if line.lstrip().startswith("|")]
    return len(table_lines) >= 3


def matches_normalized_snippet(snippet: str, markdown_text: str) -> bool:
    normalized_markdown = normalize_acceptance_text(markdown_text)
    normalized_snippet = normalize_acceptance_text(snippet)
    return bool(normalized_snippet) and normalized_snippet in normalized_markdown


def matches_restructured_table_snippet(snippet: str, markdown_text: str) -> bool:
    if matches_normalized_snippet(snippet, markdown_text):
        return True
    normalized_markdown = normalize_acceptance_text(markdown_text)
    parts = [normalize_acceptance_text(part) for part in re.split(r"[\s:：,，;；。.!！?？()（）、]+|(?<=[一-鿿])(?:为|是)(?=[一-鿿])", snippet)]
    parts = [part for part in parts if len(part) >= 2]
    return len(parts) >= 2 and all(part in normalized_markdown for part in parts)


def run_acceptance_for_item(item: dict, internal_output_root: Path) -> AcceptanceCheckResult:
    sample_id = item.get("sample_id", "")
    source_path = item.get("source_path", "")
    markdown_path = item.get("structured_markdown_path", "")
    extracted_text_path = internal_output_root / sample_id / "extracted.txt"
    markdown_file = Path(markdown_path)

    if not sample_id or not extracted_text_path.exists() or not markdown_file.exists():
        return AcceptanceCheckResult(
            source_path=source_path,
            markdown_path=markdown_path,
            sample_id=sample_id,
            checked_count=0,
            passed_count=0,
            passed=False,
            snippets=[],
            missing_snippets=[],
            note="缺少 extracted.txt 或终稿 Markdown，无法执行抽查。",
        )

    extracted_text = extracted_text_path.read_text(encoding="utf-8")
    markdown_text = markdown_file.read_text(encoding="utf-8")
    snippets = pick_acceptance_snippets(extracted_text, seed=f"{sample_id}|{source_path}")
    if not snippets:
        return AcceptanceCheckResult(
            source_path=source_path,
            markdown_path=markdown_path,
            sample_id=sample_id,
            checked_count=0,
            passed_count=0,
            passed=False,
            snippets=[],
            missing_snippets=[],
            note="抽取正文中未找到可用于抽查的短句。",
        )

    missing = [snippet for snippet in snippets if snippet not in markdown_text]
    note = ""
    if missing:
        normalized_missing = [snippet for snippet in missing if not matches_normalized_snippet(snippet, markdown_text)]
        if len(normalized_missing) != len(missing):
            note = "终稿存在折行或符号重组，抽查按归一化匹配通过部分短句。"
        missing = normalized_missing
    if missing and is_table_heavy_markdown(markdown_text):
        missing = [snippet for snippet in missing if not matches_restructured_table_snippet(snippet, markdown_text)]
        if not missing:
            note = "终稿以结构化表格重组正文，抽查按归一化匹配通过。"
        else:
            note = "终稿含大量结构化表格，未命中短句已按归一化规则复核。"
    passed_count = len(snippets) - len(missing)
    return AcceptanceCheckResult(
        source_path=source_path,
        markdown_path=markdown_path,
        sample_id=sample_id,
        checked_count=len(snippets),
        passed_count=passed_count,
        passed=not missing and len(snippets) == min(3, len(snippets)),
        snippets=snippets,
        missing_snippets=missing,
        note=note,
    )


def run_acceptance(report: dict, internal_output_root: Path) -> list[AcceptanceCheckResult]:
    results: list[AcceptanceCheckResult] = []
    for item in report.get("items", []):
        if item.get("status") != "success":
            continue
        results.append(run_acceptance_for_item(item, internal_output_root))
    return results


def write_trace_markdown(
    source_dir: Path,
    review_output_dir: Path,
    report_path: Path,
    skipped_csv_path: Path,
    report: dict,
    acceptance_results: list[AcceptanceCheckResult],
) -> Path:
    trace_path = source_dir / TRACE_FILE_NAME
    passed_count = sum(1 for item in acceptance_results if item.passed)
    failed_items = [item for item in acceptance_results if not item.passed]
    lines = [
        "# 链路说明",
        "",
        "## 执行链路",
        "- 输入目录 -> 唯一类别判定 -> MinerU优先转换/本地回退 -> 全文保留 -> 模板补字段 -> 随机抽查搜索验收 -> 输出至 Claude输出。",
        "",
        "## 本次处理信息",
        f"- 输入目录：{source_dir}",
        f"- 终稿输出目录：{review_output_dir}",
        f"- 内部扫描报告：{report_path}",
        f"- 跳过记录：{skipped_csv_path}",
        f"- 总文件数：{report.get('total_count', 0)}",
        f"- 进入主链路数：{report.get('selected_count', 0)}",
        f"- 终稿生成成功数：{report.get('success_count', 0)}",
        f"- 处理失败数：{report.get('failed_count', 0)}",
        f"- 低优先级近似稿跳过数：{report.get('skipped_duplicate_count', 0)}",
        f"- 纯照片跳过数：{report.get('skipped_photo_count', 0)}",
        f"- 非源文件跳过数：{report.get('skipped_non_source_count', 0)}",
        "",
        "## 验收抽查结果",
        f"- 抽查文件数：{len(acceptance_results)}",
        f"- 抽查通过数：{passed_count}",
        f"- 抽查未通过数：{len(failed_items)}",
        "",
    ]

    if acceptance_results:
        lines.append("## 抽查明细")
        lines.append("")
        for item in acceptance_results:
            lines.extend(
                [
                    f"### {Path(item.source_path).name if item.source_path else item.sample_id}",
                    f"- 样本ID：{item.sample_id}",
                    f"- 终稿文件：{item.markdown_path}",
                    f"- 抽查结果：{'通过' if item.passed else '未通过'}",
                    f"- 命中数：{item.passed_count}/{item.checked_count}",
                ]
            )
            if item.snippets:
                lines.append("- 抽查短句：")
                lines.extend([f"  - {snippet}" for snippet in item.snippets])
            if item.missing_snippets:
                lines.append("- 未命中短句：")
                lines.extend([f"  - {snippet}" for snippet in item.missing_snippets])
            if item.note:
                lines.append(f"- 备注：{item.note}")
            lines.append("")

    output_note = "- 本次未生成终稿 Markdown。" if report.get('success_count', 0) == 0 else "- 终稿 Markdown 已落在 Claude输出 子目录中。"
    lines.extend([
        "## 输出说明",
        output_note,
        "- skipped_files.csv 记录低优先级近似稿、纯照片、非源文件和失败项。",
        "- 若抽查未通过，应回退至抽取或清洗环节修正后重新执行。",
        "",
    ])
    trace_path.write_text("\n".join(lines), encoding="utf-8")
    return trace_path


def run_directory(
    source_dir: Path,
    *,
    output_root: Path,
    pdf_extractor: str,
    mineru_token: str | None,
    enable_ocr: bool,
    enable_qwen: bool,
    qwen_runtime: dict[str, str],
) -> int:
    review_output_dir = build_review_output_dir(source_dir, output_root)
    review_output_dir.mkdir(parents=True, exist_ok=True)

    result = run_source_dir(
        source_dir,
        output_dir=review_output_dir,
        pdf_extractor=pdf_extractor,
        mineru_token=mineru_token,
        enable_ocr=enable_ocr,
        enable_qwen=enable_qwen,
        qwen_runtime=qwen_runtime,
    )

    internal_output_root = build_internal_output_root(source_dir)
    report_path = internal_output_root / "scan_report.json"
    missing_report_created = False
    if not report_path.exists():
        missing_report_created = True
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(
                {
                    "source_dir": str(source_dir),
                    "review_output_dir": str(review_output_dir),
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "total_count": 0,
                    "selected_count": 0,
                    "success_count": 0,
                    "failed_count": 1,
                    "skipped_duplicate_count": 0,
                    "skipped_photo_count": 0,
                    "skipped_non_source_count": 0,
                    "items": [
                        {
                            "status": "failed",
                            "source_path": str(source_dir),
                            "error": "目录扫描未生成 scan_report.json，通常表示未发现可处理文件。",
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    report = load_report(report_path)
    skipped_csv_path = write_skipped_files_csv(source_dir, report)
    acceptance_results = run_acceptance(report, internal_output_root)
    write_trace_markdown(source_dir, review_output_dir, report_path, skipped_csv_path, report, acceptance_results)

    if result != 0:
        return result
    if missing_report_created:
        return 1
    if any(not item.passed for item in acceptance_results):
        return 1
    return 0


def main() -> int:
    args = build_parser().parse_args()
    source_dir = Path(args.source_dir).expanduser()
    output_root = Path(args.output_root).expanduser()
    mineru_token = resolve_mineru_token(args.mineru_token)
    qwen_runtime = resolve_qwen_runtime(
        enable_qwen=args.enable_qwen,
        cli_api_key=args.qwen_api_key,
        cli_base_url=args.qwen_base_url,
        cli_model=args.qwen_model,
    )
    if args.enable_ocr and not mineru_token:
        raise SystemExit("启用 --enable-ocr 时，必须通过 --mineru-token 或环境变量 MINERU_TOKEN 提供 token。")
    if args.enable_qwen and not qwen_runtime:
        raise SystemExit("启用 --enable-qwen 时，必须提供 Qwen 的 api key、base url、model。")
    return run_directory(
        source_dir,
        output_root=output_root,
        pdf_extractor=args.pdf_extractor,
        mineru_token=mineru_token,
        enable_ocr=args.enable_ocr,
        enable_qwen=args.enable_qwen,
        qwen_runtime=qwen_runtime,
    )


if __name__ == "__main__":
    raise SystemExit(main())
