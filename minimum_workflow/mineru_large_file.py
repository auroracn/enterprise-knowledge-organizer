"""
MinerU 大文件拆分链路：

MinerU 公开批量接口对单文件有 200 页上限。检测报告类 docx / PDF 经常超过这个上限，
本模块负责：
1. 判断是否需要拆分（文件 >100MB 或页数 >100）
2. docx 先用 Word COM 转 PDF
3. PDF 按固定页数切片（每片 180 页，留 20 页 buffer）
4. 多片一次性送 MinerU 批量接口（MinerU 自身并行处理）
5. 结果按原顺序拼接为单份 Markdown，失败片只影响对应片段

保持"最小破坏性"：不在语义层切分，只按页数切；片之间加 HTML 注释标记便于溯源。
"""

from __future__ import annotations

import math
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from minimum_workflow.contracts import ExtractionResult

try:
    import pythoncom  # type: ignore
    from win32com import client as win32_client  # type: ignore
except ImportError:
    pythoncom = None  # type: ignore
    win32_client = None  # type: ignore


# MinerU 公开接口单文件页数硬上限（实测错误文案："number of pages exceeds limit (200 pages)"）。
MINERU_MAX_PAGES_PER_FILE = 200
# 每片预留 20 页 buffer，避免边界情况触发 200 页红线。
SPLIT_PAGES_PER_CHUNK = 180
# 触发拆分的门槛（由 pipeline 层调用 should_use_split_strategy 判定）。
LARGE_FILE_SIZE_THRESHOLD_BYTES = 100 * 1024 * 1024
LARGE_FILE_PAGE_THRESHOLD = 100

# 轮询预算（与 extractors._size_aware_max_polls 对齐）
POLL_BASE = 60
POLL_UPPER = 900


def _page_aware_max_polls(total_pages: int, poll_interval_seconds: int = 5) -> int:
    """按页数估算轮询预算。

    经验公式：base 60 + 每 10 页 +12 次（约 1 分钟）；上限 900 次（约 75 分钟）。
    与大小公式不同：扫描型 PDF 可能很大但页数少，或反之；页数更贴近 MinerU 实际耗时。
    """
    if total_pages <= 0:
        return POLL_BASE
    extra = (total_pages // 10) * 12
    return min(max(POLL_BASE, POLL_BASE + extra), POLL_UPPER)


def _size_aware_max_polls_fallback(path: Path, poll_interval_seconds: int = 5) -> int:
    """当页数未知时按 MB 估算。与 extractors._size_aware_max_polls 同公式。"""
    try:
        size_mb = path.stat().st_size / (1024 * 1024)
    except OSError:
        size_mb = 0.0
    extra = int((size_mb / 5.0) * 12)
    return min(max(POLL_BASE, POLL_BASE + extra), POLL_UPPER)


def _heartbeat(message: str) -> None:
    print(f"[MinerU-Split] {message}", flush=True)


_MINERU_PAGE_LIMIT_ERROR_PATTERN = re.compile(r"(pages\s*exceeds\s*limit|exceeds\s*limit\s*\(200\s*pages\))", re.IGNORECASE)


def is_mineru_page_limit_error(text: str | None) -> bool:
    """判断 MinerU 返回的错误/日志文本是否为"超过 200 页上限"。用于后置失败回退到拆分链路。"""
    if not text:
        return False
    return bool(_MINERU_PAGE_LIMIT_ERROR_PATTERN.search(text))


def count_pdf_pages(pdf_path: Path) -> int | None:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(str(pdf_path))
        return len(reader.pages)
    except Exception:
        return None


_APP_XML_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}"
_DOC_XML_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def count_docx_pages_estimate(docx_path: Path) -> int | None:
    """估算 docx 页数。优先读 docProps/app.xml 的 <Pages>（Word 保存时写入），
    失败回退为 document.xml 中 w:br type="page" 硬分页数 + 1。
    两种都拿不到时返回 None。"""
    try:
        with zipfile.ZipFile(docx_path) as zf:
            try:
                with zf.open("docProps/app.xml") as fp:
                    tree = ET.parse(fp)
                pages_el = tree.getroot().find(f"{_APP_XML_NS}Pages")
                if pages_el is not None and (pages_el.text or "").strip().isdigit():
                    value = int(pages_el.text.strip())
                    if value > 0:
                        return value
            except KeyError:
                pass
            except Exception:
                pass
            try:
                with zf.open("word/document.xml") as fp:
                    body = fp.read().decode("utf-8", errors="ignore")
            except KeyError:
                return None
    except (zipfile.BadZipFile, OSError):
        return None
    # 回退：统计硬分页符 + 首页。保守估计，低估了自动分页。
    hard_breaks = len(re.findall(rf'<w:br\b[^>]*w:type="page"', body))
    if hard_breaks > 0:
        return hard_breaks + 1
    return None


def should_use_split_strategy(source_path: Path, file_type: str) -> bool:
    """大文件拆分的触发判断。只处理 pdf / word 两类。
    触发条件：
    - 文件大小 > 100 MB；或
    - PDF 页数 > 100；或
    - docx 估算页数 > 200（接近 MinerU 单文件硬上限直接走拆分，避免先上传再失败）。
    """
    if file_type not in {"pdf", "word"}:
        return False
    try:
        size_bytes = source_path.stat().st_size
    except OSError:
        return False
    if size_bytes > LARGE_FILE_SIZE_THRESHOLD_BYTES:
        return True
    if file_type == "pdf":
        pages = count_pdf_pages(source_path)
        if pages is not None and pages > LARGE_FILE_PAGE_THRESHOLD:
            return True
    elif file_type == "word":
        pages = count_docx_pages_estimate(source_path)
        # 阈值按 MinerU 硬上限 200 判定：估计页数 > 200 直接拆；估不准返回 None 时走后置 fallback。
        if pages is not None and pages > MINERU_MAX_PAGES_PER_FILE:
            return True
    return False


def convert_docx_to_pdf(docx_path: Path, output_dir: Path) -> Path:
    """用 Word COM 把 docx 另存为 PDF，保留原版面。依赖本机 Microsoft Word。"""
    if pythoncom is None or win32_client is None:
        raise RuntimeError("当前环境缺少 Windows Word COM 依赖，无法将 docx 转 PDF。")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{docx_path.stem}.pdf"
    pythoncom.CoInitialize()
    word = None
    doc = None
    try:
        word = win32_client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(str(docx_path.resolve()), ReadOnly=True)
        # wdExportFormatPDF = 17
        doc.ExportAsFixedFormat(str(output_path), 17)
    except Exception as exc:
        raise RuntimeError(f"Word COM 转 PDF 失败：{exc}") from exc
    finally:
        if doc is not None:
            try:
                doc.Close(False)
            except Exception:
                pass
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()
    if not output_path.exists():
        raise RuntimeError("Word COM 转 PDF 未生成输出文件。")
    return output_path


def split_pdf_by_pages(
    pdf_path: Path,
    output_dir: Path,
    pages_per_chunk: int = SPLIT_PAGES_PER_CHUNK,
) -> list[Path]:
    """按固定页数切分 PDF；若总页数 ≤ 单片上限则返回原文件列表。"""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    if total_pages <= pages_per_chunk:
        return [pdf_path]

    output_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[Path] = []
    num_chunks = math.ceil(total_pages / pages_per_chunk)
    digits = max(2, len(str(num_chunks)))
    for index in range(num_chunks):
        writer = PdfWriter()
        start = index * pages_per_chunk
        end = min(start + pages_per_chunk, total_pages)
        for page_idx in range(start, end):
            writer.add_page(reader.pages[page_idx])
        chunk_path = output_dir / f"{pdf_path.stem}_part{index + 1:0{digits}d}.pdf"
        with chunk_path.open("wb") as file_obj:
            writer.write(file_obj)
        chunks.append(chunk_path)
    return chunks


def extract_large_file_via_split(
    source_path: Path,
    file_type: str,
    token: str,
    *,
    poll_interval_seconds: int = 5,
    cache_dir: Path | None = None,
    max_retries: int = 1,
) -> ExtractionResult:
    """大文件拆分主链路：docx→PDF→切片→MinerU 批量→（失败分片重试）→按序拼接。

    参数：
    - cache_dir：若传入（绝对路径），每个 chunk 完成后落盘 `partNN.md`，下次跑若命中
      则跳过该 chunk；None 保持原行为（临时目录，不落盘）
    - max_retries：单批失败后，对失败 chunk 再发起批次的次数。1 表示首跑失败后再重试一次。
    """
    # 延迟导入避免循环依赖
    from minimum_workflow.extractors import (
        clean_mineru_markdown,
        has_meaningful_text,
        normalize_preview,
        run_mineru_batch,
    )

    work_dir = Path(tempfile.mkdtemp(prefix="mineru_large_"))
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        if file_type == "word":
            _heartbeat(f"大文件 {source_path.name}，启动 Word COM 转 PDF...")
            pdf_path = convert_docx_to_pdf(source_path, work_dir)
            pdf_size_mb = pdf_path.stat().st_size / (1024 * 1024)
            _heartbeat(f"docx → PDF 完成：{pdf_path.name}（{pdf_size_mb:.1f} MB）")
        else:
            pdf_path = source_path

        total_pages = count_pdf_pages(pdf_path) or 0
        _heartbeat(f"PDF 总页数：{total_pages}")

        if total_pages > SPLIT_PAGES_PER_CHUNK:
            _heartbeat(f"按每 {SPLIT_PAGES_PER_CHUNK} 页切分...")
            chunks = split_pdf_by_pages(pdf_path, work_dir)
        else:
            chunks = [pdf_path]
        _heartbeat(f"共 {len(chunks)} 份分片待送 MinerU")

        # 轮询预算按页数估（优于按 MB 估，因为 MinerU 耗时与页数线性相关）
        if total_pages > 0:
            per_chunk_pages = min(total_pages, SPLIT_PAGES_PER_CHUNK)
            max_polls = _page_aware_max_polls(per_chunk_pages, poll_interval_seconds)
            budget_reason = f"按页数估（每片最多 {per_chunk_pages} 页）"
        else:
            # 页数未知：回退按 chunk 最大 MB
            max_polls = max(
                _size_aware_max_polls_fallback(c, poll_interval_seconds) for c in chunks
            )
            budget_reason = "按分片大小估（页数未知回退）"
        _heartbeat(
            f"预留 {max_polls} 次轮询（约 {max_polls * poll_interval_seconds // 60} 分钟，{budget_reason}）"
        )

        # 断点续跑：cache 命中的 chunk 不再送 MinerU
        chunk_results: dict[int, str] = {}  # chunk_idx -> cleaned markdown
        chunks_to_send: list[tuple[int, Path]] = []
        for idx, chunk in enumerate(chunks):
            cached = _load_chunk_cache(cache_dir, idx) if cache_dir else None
            if cached is not None:
                _heartbeat(f"[cache 命中] 分片 {chunk.name} 跳过上传")
                chunk_results[idx] = cached
            else:
                chunks_to_send.append((idx, chunk))

        failed_idx: list[tuple[int, Path, str]] = []  # (idx, path, reason)
        batch_ids: list[str] = []

        def _run_batch_and_collect(pairs: list[tuple[int, Path]]) -> None:
            if not pairs:
                return
            paths = [p for _, p in pairs]
            batch_result = run_mineru_batch(
                paths,
                token,
                poll_interval_seconds=poll_interval_seconds,
                max_polls=max_polls,
            )
            batch_ids.append(batch_result.get("batch_id", ""))
            for (idx, chunk_path), result in zip(pairs, batch_result["results"]):
                state = result.get("state")
                if state == "done":
                    md = clean_mineru_markdown(result.get("markdown", ""))
                    if md.strip():
                        chunk_results[idx] = md
                        if cache_dir:
                            _save_chunk_cache(cache_dir, idx, md)
                    else:
                        failed_idx.append((idx, chunk_path, "空"))
                else:
                    failed_idx.append((idx, chunk_path, state or "未知"))

        # 首跑
        _run_batch_and_collect(chunks_to_send)

        # 分块级重试：对失败的子集再独立发起一个批次
        retry_count = 0
        while failed_idx and retry_count < max_retries:
            retry_count += 1
            retry_pairs = [(idx, p) for idx, p, _ in failed_idx]
            _heartbeat(
                f"[重试 {retry_count}/{max_retries}] 失败分片 {len(retry_pairs)} 份再送 MinerU："
                + "、".join(p.name for _, p in retry_pairs)
            )
            failed_idx = []
            _run_batch_and_collect(retry_pairs)

        # 按 chunk 顺序拼接
        parts: list[str] = []
        for idx, chunk in enumerate(chunks):
            md = chunk_results.get(idx)
            if md:
                parts.append(f"<!-- 分片：{chunk.name} -->\n\n{md}")

        combined = "\n\n".join(parts).strip()
        preview = normalize_preview(combined)

        note_parts = [f"大文件拆分链路：{len(chunks)} 片并行处理。"]
        if batch_ids:
            note_parts.append(f"批次号：{'、'.join(b for b in batch_ids if b)}。")
        if retry_count:
            note_parts.append(f"失败分片重试 {retry_count} 次。")
        if failed_idx:
            failed_names = [f"{p.name}({r})" for _, p, r in failed_idx]
            note_parts.append(f"最终失败 {len(failed_idx)}/{len(chunks)}：{'、'.join(failed_names[:5])}")

        if has_meaningful_text(combined):
            status = "已提取文本"
        elif combined:
            status = "待审核"
        else:
            status = "待人工复核"

        return ExtractionResult(
            extractor_name=f"mineru:split:{file_type}",
            extraction_status=status,
            extracted_text=combined,
            preview_text=preview,
            text_length=len(combined),
            page_count=total_pages or None,
            source_encoding="utf-8",
            note=" ".join(note_parts),
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# chunk cache 辅助（断点续跑内部 API，默认不启用；F 类 CLI 会通过 cache_dir 挂接）
# ---------------------------------------------------------------------------

def _chunk_cache_path(cache_dir: Path, idx: int) -> Path:
    return cache_dir / f"part{idx + 1:03d}.md"


def _load_chunk_cache(cache_dir: Path | None, idx: int) -> str | None:
    if cache_dir is None:
        return None
    cached = _chunk_cache_path(cache_dir, idx)
    if cached.exists() and cached.stat().st_size > 0:
        return cached.read_text(encoding="utf-8", errors="ignore")
    return None


def _save_chunk_cache(cache_dir: Path, idx: int, markdown: str) -> None:
    _chunk_cache_path(cache_dir, idx).write_text(markdown, encoding="utf-8")
