"""
长风知识整理助手 - 模块9 Web 界面
运行方式: python 知识整理助手.py
"""
from __future__ import annotations

import atexit
import ipaddress
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from uuid import uuid4

import gradio as gr
import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as html_to_markdown
from minimum_workflow.dify_import_service import (
    BATCH_STATE_FILE_NAME,
    DifyClient,
    DifyRuntime,
    build_batch_choices,
    collect_batch_snapshot,
    ensure_ui_batches_dir,
    import_ready_documents,
    merge_reviewed_documents,
    resolve_dify_runtime,
    save_manual_review,
    write_batch_state,
)
from minimum_workflow.ragflow_import_service import (
    RagflowClient,
    RagflowRuntime,
    batch_upload_to_ragflow,
    resolve_ragflow_runtime,
    upload_markdown_to_ragflow,
)
from minimum_workflow.cli import upload_to_ragflow

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = str(PROJECT_ROOT / "Claude输出")
_DOWNLOAD_ARCHIVES: set[Path] = set()

# ── 企业 Profile（多公司隔离） ─────────────────────────────────────────────────
PROFILES: list[tuple[str, str]] = [
    ("长风低空", "chanfengdikongzl"),
    ("新维度", "xinweiduzl"),
]
DEFAULT_PROFILE = PROFILES[0][1]
PROFILE_LABELS = dict(PROFILES)
PROFILE_VALUES = {value for _, value in PROFILES}


def _resolve_profile(profile: str | None) -> str:
    if profile and profile in PROFILE_VALUES:
        return profile
    return DEFAULT_PROFILE


def _config_path_for(profile: str) -> Path:
    return PROJECT_ROOT / f"配置文件.{profile}.json"


# 配置在磁盘上是分段 JSON（qwen / deepseek / mineru / dify），
# 但历史代码都按扁平小写键读取，这里保留一层映射方便兼容。
_CONFIG_FIELD_MAP: list[tuple[str, str, tuple[str, ...]]] = [
    ("qwen", "api_key", ("qwen_api_key", "qwen-key", "qwen api key")),
    ("qwen", "base_url", ("qwen api连接", "qwen_api_base", "qwen_base_url")),
    ("qwen", "model", ("qwen模型", "qwen_model", "qwen model")),
    ("deepseek", "api_key", ("deepseek_api_key", "deepseek-key", "deepseek api key")),
    ("deepseek", "base_url", ("deepseek api连接", "deepseek_api_base", "deepseek_base_url")),
    ("deepseek", "model", ("deepseek模型", "deepseek_model", "deepseek model")),
    ("mineru", "token", ("mineru vlm大模型 用于转换md格式key", "mineru_token", "mineru token")),
    ("dify", "api_url", ("dify_api_url", "dify api url")),
    ("dify", "api_key", ("dify_api_key", "dify api key")),
    ("dify", "default_dataset_ids", ("dify_default_dataset_ids", "dify default dataset ids")),
    ("dify", "verify_ssl", ("dify_verify_ssl", "dify verify ssl")),
    ("ragflow", "api_url", ("ragflow_api_url", "ragflow api url")),
    ("ragflow", "api_key", ("ragflow_api_key", "ragflow api key")),
    ("ragflow", "default_dataset_ids", ("ragflow_default_dataset_ids", "ragflow default dataset ids")),
    ("ragflow", "verify_ssl", ("ragflow_verify_ssl", "ragflow verify ssl")),
]


def _flatten_config(data: dict) -> dict[str, str]:
    flat: dict[str, str] = {}
    for section, field, aliases in _CONFIG_FIELD_MAP:
        value = str((data.get(section) or {}).get(field, "") or "").strip()
        if not value:
            continue
        for alias in aliases:
            flat[alias.lower()] = value
    return flat


def _nest_config(flat_input: dict[str, str], base: dict | None = None) -> dict:
    result = {
        "qwen": dict((base or {}).get("qwen", {})),
        "deepseek": dict((base or {}).get("deepseek", {})),
        "mineru": dict((base or {}).get("mineru", {})),
        "dify": dict((base or {}).get("dify", {})),
        "ragflow": dict((base or {}).get("ragflow", {})),
    }
    lower_flat = {k.lower(): v for k, v in flat_input.items()}
    for section, field, aliases in _CONFIG_FIELD_MAP:
        for alias in aliases:
            value = lower_flat.get(alias.lower())
            if value:
                result[section][field] = value.strip()
                break
    return result


def _read_config_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _cleanup_download_archives() -> None:
    for archive_path in tuple(_DOWNLOAD_ARCHIVES):
        try:
            archive_path.unlink(missing_ok=True)
        except OSError:
            continue


atexit.register(_cleanup_download_archives)

# ── 样式：高级商务 UI / UX ─ (基于 ui-ux-pro-max 指导) ──────────────────────────
STYLE = """
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800&family=Open+Sans:wght@400;500;600;700&display=swap');

:root {
    --primary: #16a34a;
    --primary-hover: #15803d;
    --bg-page: #f8fafc;
    --bg-card: #ffffff;
    --text-main: #000000;
    --text-secondary: #0f172a;
    --border-color: #e2e8f0;
    --accent-light: #f0fdf4;
    --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
    --shadow-md: 0 10px 15px -3px rgb(0 0 0 / 0.1);
    --radius: 12px;
}

/* 强制明亮模式基础 */
body, .gradio-container {
    background-color: var(--bg-page) !important;
    color: var(--text-main) !important;
}

/* 仅清除布局容器的边框与阴影，保留 padding 与 gap 以维持交互区域 */
.gradio-container .row, 
.gradio-container .column,
.gradio-container .block,
.gradio-container .form,
.gradio-container .box,
.gradio-container .group,
.gradio-container .wrap {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}

/* 顶部品牌区域 */
#g-header {
    background: var(--bg-card);
    border-bottom: 2px solid var(--border-color);
    padding: 24px 48px;
    display: flex;
    align-items: center;
    box-shadow: var(--shadow-sm);
}
#g-header-left { display: flex; align-items: center; gap: 16px; }
#g-logo {
    width: 48px; height: 48px;
    background: linear-gradient(135deg, #4ade80, #16a34a);
    border-radius: 12px;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.6em;
}
#g-title {
    font-family: 'Poppins', sans-serif;
    font-size: 1.4em;
    font-weight: 800;
    background: linear-gradient(to right, #16a34a, #15803d);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
#g-subtitle { color: #475569; font-size: 0.9em; font-weight: 700; margin-top: 2px; }

/* 强制 label 标签文字为纯黑色，确保极致清晰度 */
.gradio-container label, 
.gradio-container label span,
.gradio-container .label-wrap span,
.gradio-container legend,
label, label > span, .gr-form label {
    color: #000000 !important;
    font-weight: 800 !important;
    font-size: 1.05em !important;
    background: transparent !important;
    opacity: 1 !important;
}

/* 单选框 (Radio) 强制染色修正：杜绝黑色背景 */
.gradio-container .gr-button-group,
.gradio-container .gr-radio-row,
.gradio-container .gr-input-label,
.gradio-container [data-testid="block-label"],
.gradio-container .gr-radio-item {
    background-color: #ffffff !important;
    border: 1px solid var(--border-color) !important;
    border-radius: 8px !important;
    color: #000000 !important;
}
.gradio-container .gr-input-label span,
.gradio-container .gr-radio-item span {
    color: #000000 !important;
    font-weight: 700 !important;
}
/* 选中状态文字加粗 */
.gradio-container input[type=radio]:checked + span {
    color: var(--primary) !important;
    font-weight: 800 !important;
}

/* 输入框 / 下拉框 全白背景强制注入 (仅限文本类) */
.gradio-container input[type=text], 
.gradio-container input[type=password],
.gradio-container textarea, 
.gradio-container select {
    background-color: #ffffff !important;
    color: #000000 !important;
    border: 2px solid var(--border-color) !important;
    font-weight: 600 !important;
    border-radius: 8px !important;
}

/* 主内容区 */
#g-main { max-width: 1400px; margin: 0 auto; padding: 24px 40px; }

/* 样式修正：移除多余背景，保持清新简洁 */
.g-card {
    background: transparent !important;
    padding: 0 !important;
    border: none !important;
    box-shadow: none !important;
}
.g-section {
    font-family: 'Poppins', sans-serif;
    font-size: 1.1em;
    font-weight: 800;
    color: var(--primary);
    margin-bottom: 24px;
    display: flex; align-items: center; gap: 8px;
}
.g-section::before {
    content: ''; width: 6px; height: 20px;
    background: var(--primary); border-radius: 3px;
}

/* 按钮样式精修 */
#run-btn {
    background: linear-gradient(135deg, #22c55e, #16a34a) !important;
    color: white !important;
    font-weight: 800 !important;
    border-radius: 10px !important;
}
#pick-src, #pick-out {
    background: var(--accent-light) !important;
    color: var(--primary) !important;
    font-weight: 800 !important;
}

/* 下载按钮高亮 */
#download-btn {
    height: 60px !important;
    font-size: 1.2em !important;
    background: #f0fdf4 !important;
    border: 2px dashed var(--primary) !important;
    color: var(--primary) !important;
    font-weight: 800 !important;
}
#download-btn:hover {
    background: var(--accent-light) !important;
    transform: translateY(-2px);
    transition: all 0.2s ease;
}

/* 隐藏 Gradio 官方页脚 */
footer { display: none !important; }

/* Dropdown 右侧内边距加大，让箭头远离文字；箭头本身变浅色减少干扰 */
.gradio-container [data-testid="dropdown"] input,
.gradio-container input[role="combobox"] {
    padding-right: 12px !important;
}
/* 彻底隐藏 Dropdown 三角箭头，避免遮挡长文字（点击仍可弹出选项） */
.gradio-container [data-testid="dropdown"] svg,
.gradio-container [data-testid="dropdown"] .wrap > button svg,
.gradio-container [data-testid="dropdown"] button[aria-haspopup="listbox"] svg,
.gradio-container [data-testid="dropdown"] .wrap-inner ~ svg,
.gradio-container [role="combobox"] ~ svg,
.gradio-container .dropdown-arrow,
.gradio-container .icon-wrap {
    display: none !important;
    visibility: hidden !important;
    width: 0 !important;
    height: 0 !important;
}
/* 用悬浮背景色提示"可点击下拉" */
.gradio-container [data-testid="dropdown"] {
    cursor: pointer !important;
}
.gradio-container [data-testid="dropdown"]:hover input,
.gradio-container [data-testid="dropdown"]:hover [role="combobox"] {
    background-color: #f0fdf4 !important;
}

/* Profile 选择器单独加醒目边框，和其他下拉区分 */
#profile-selector {
    background: linear-gradient(135deg, #ecfdf5, #ffffff) !important;
    border: 2px solid var(--primary) !important;
    border-radius: 10px !important;
    padding: 10px 14px !important;
    box-shadow: 0 2px 6px rgba(22, 163, 74, 0.15) !important;
    margin-bottom: 6px !important;
}
#profile-selector input,
#profile-selector [role="combobox"] {
    background-color: #ffffff !important;
    border: 1.5px solid var(--primary) !important;
    border-radius: 6px !important;
    font-weight: 700 !important;
    font-size: 1.05em !important;
    color: #14532d !important;
    padding: 8px 14px !important;
    min-height: 40px !important;
}
#profile-selector label,
#profile-selector label span {
    color: var(--primary) !important;
    font-weight: 800 !important;
}
#profile-selector:hover {
    box-shadow: 0 4px 12px rgba(22, 163, 74, 0.25) !important;
}
#profile-selector::after {
    content: "▾";
    position: absolute;
    right: 24px;
    top: 42px;
    color: var(--primary);
    font-size: 14px;
    pointer-events: none;
    font-weight: bold;
}

/* API 配置面板头部极致精简化，消除“横条” (滚动条或边框) */
#header-settings {
    border: none !important;
    background: transparent !important;
}
#header-settings .label-wrap {
    background: var(--accent-light) !important;
    color: var(--primary) !important;
    border: 1px solid #bbf7d0 !important;
    border-radius: 20px !important;
    padding: 6px 18px !important;
    font-size: 0.85em !important;
    font-weight: 700 !important;
    width: fit-content !important;
    min-width: 160px !important;
    justify-content: center !important;
    box-shadow: none !important;
}
#header-settings .label-wrap:hover {
    background: #dcfce7 !important;
}
/* 隐藏 Accordion 展开时的默认内边距/边框产生的视觉噪音 */
#header-settings .accordion-content {
    border: 1px solid var(--border-color) !important;
    border-radius: var(--radius) !important;
    margin-top: 8px !important;
    padding: 20px !important;
    background: #ffffff !important;
    box-shadow: var(--shadow-md) !important;
}
"""


# ── 配置读写 ───────────────────────────────────────────────────────────────────
def _load_config_data(profile: str) -> dict:
    """返回分段 JSON 原始结构；执行 legacy txt → json 迁移与 profile 继承。"""
    profile = _resolve_profile(profile)
    target = _config_path_for(profile)

    if target.exists():
        data = _read_config_json(target)
        if data:
            return data

    # 非默认 profile 首次加载：从默认 profile 继承，但清空 Dify URL（两个库隔离）
    if profile != DEFAULT_PROFILE:
        base = _load_config_data(DEFAULT_PROFILE)
        if base:
            inherited = {
                "qwen": dict(base.get("qwen", {})),
                "deepseek": dict(base.get("deepseek", {})),
                "mineru": dict(base.get("mineru", {})),
                "dify": dict(base.get("dify", {})),
            }
            inherited["dify"]["api_url"] = ""
            try:
                target.write_text(json.dumps(inherited, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError:
                pass
            return inherited

    return {}


def _load_config(profile: str = DEFAULT_PROFILE) -> dict[str, str]:
    return _flatten_config(_load_config_data(profile))


def _save_config(settings_raw: dict[str, str], profile: str = DEFAULT_PROFILE) -> None:
    profile = _resolve_profile(profile)
    target = _config_path_for(profile)
    base = _load_config_data(profile)
    merged = _nest_config(settings_raw, base=base)
    target.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 系统文件夹选择器 ───────────────────────────────────────────────────────────
# (移除了 _pick_folder 函数，改为 Web 原生上传方式)


def _slugify_url_path(url: str) -> str:
    parsed = urlparse(url)
    stem = Path(parsed.path).stem or parsed.netloc or "webpage"
    stem = re.sub(r"[^\w一-鿿-]+", "_", stem, flags=re.UNICODE).strip("_")
    return stem or "webpage"


def _is_disallowed_ip(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve_hostname_addresses(hostname: str) -> set[str]:
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return set()
    return {item[4][0] for item in addr_info if item and len(item) >= 5 and item[4]}


def _validate_source_url(url: str) -> str:
    source_url = url.strip()
    if any(char.isspace() for char in source_url):
        raise ValueError("网址中不能包含空格或换行。")
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("仅支持 http/https 网页地址。")
    if parsed.username or parsed.password:
        raise ValueError("网址中不能包含用户名或密码。")

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("网址缺少有效主机名。")
    if hostname == "localhost" or hostname.endswith(".local"):
        raise ValueError("不允许抓取本机或内网地址。")

    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        for resolved_host in _resolve_hostname_addresses(hostname):
            resolved_ip = ipaddress.ip_address(resolved_host)
            if _is_disallowed_ip(resolved_ip):
                raise ValueError("不允许抓取本机或内网地址。")
        return source_url

    if _is_disallowed_ip(ip):
        raise ValueError("不允许抓取本机或内网地址。")
    return source_url


def _normalize_upload_relative_path(path_text: str) -> Path | None:
    candidate = (path_text or "").strip().replace("\\", "/")
    if not candidate or candidate.startswith("/"):
        return None

    parts = candidate.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    if re.fullmatch(r"[A-Za-z]:", parts[0]):
        return None
    return Path(*parts)


def _resolve_uploaded_target(base_dir: Path, upload_name: str | None, temp_path: str | Path) -> Path:
    relative_path = _normalize_upload_relative_path(upload_name or "")
    if relative_path is None:
        relative_path = Path(str(temp_path)).name
    return base_dir / relative_path


def _build_upload_copy_plan(base_dir: Path, uploaded_files: list[object]) -> tuple[list[tuple[Path, Path]], bool]:
    copy_plan: list[tuple[Path, Path]] = []
    seen_targets: set[Path] = set()
    preserved_relative_path = False

    for f_data in uploaded_files:
        source_path = Path(getattr(f_data, "name", None) or getattr(f_data, "path", None) or str(f_data))
        orig_name = getattr(f_data, "orig_name", None)
        relative_path = _normalize_upload_relative_path(orig_name or "")
        if relative_path is not None and len(relative_path.parts) > 1:
            preserved_relative_path = True
        target = _resolve_uploaded_target(base_dir, orig_name, source_path)
        if target in seen_targets:
            raise ValueError(
                f"检测到同名文件冲突：{target.name}。当前上传接口不会保留子目录层级，请先改名后再上传。"
            )
        seen_targets.add(target)
        copy_plan.append((source_path, target))

    return copy_plan, len(copy_plan) > 1 and not preserved_relative_path


def _terminate_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def _build_download_archive(output_dir: Path) -> str:
    fd, archive_base = tempfile.mkstemp(prefix="cf_results_")
    os.close(fd)
    archive_base_path = Path(archive_base)
    archive_base_path.unlink(missing_ok=True)
    archive_full_path = shutil.make_archive(str(archive_base_path), "zip", root_dir=str(output_dir))
    _DOWNLOAD_ARCHIVES.add(Path(archive_full_path))
    return archive_full_path


def _fetch_webpage_response(url: str) -> tuple[str, requests.Response]:
    current_url = _validate_source_url(url)
    headers = {"User-Agent": "Mozilla/5.0"}
    session = requests.Session()

    for _ in range(5):
        response = session.get(current_url, timeout=60, headers=headers, allow_redirects=False)
        if 300 <= response.status_code < 400 and response.headers.get("Location"):
            current_url = _validate_source_url(urljoin(current_url, response.headers["Location"]))
            continue
        response.raise_for_status()
        content_type = (response.headers.get("Content-Type") or "").lower()
        if content_type and "text/html" not in content_type and "application/xhtml+xml" not in content_type:
            raise ValueError("仅支持可直接访问的 HTML 页面。")
        return current_url, response

    raise ValueError("网址重定向次数过多。")


def _build_status_tip(source_mode: str) -> str:
    if source_mode == "url":
        message = "状态：网址模式，请粘贴单个 HTML 页面地址后开始处理"
    else:
        message = "状态：上传模式，请选择本地资料目录后开始处理"
    return f"<div id='status-tip' style='margin-top:12px; color:#64748b; font-size:0.8em;'>{message}</div>"


# MinerU 受理格式，用于预估"主要耗时部分"
_MINERU_UPLOAD_EXTS = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".html", ".htm"}


def _format_upload_preview(uploaded_files) -> str:
    if not uploaded_files:
        return ""
    if isinstance(uploaded_files, str):
        uploaded_files = [uploaded_files]
    total_size = 0
    mineru_size = 0
    mineru_count = 0
    biggest_mb = 0.0
    biggest_name = ""
    count = 0
    for item in uploaded_files:
        try:
            path = Path(item) if isinstance(item, (str, Path)) else None
            if path is None:
                continue
            size = path.stat().st_size
        except (OSError, TypeError):
            continue
        count += 1
        total_size += size
        if path.suffix.lower() in _MINERU_UPLOAD_EXTS:
            mineru_count += 1
            mineru_size += size
            size_mb = size / (1024 * 1024)
            if size_mb > biggest_mb:
                biggest_mb = size_mb
                biggest_name = path.name
    if count == 0:
        return ""

    total_mb = total_size / (1024 * 1024)
    mineru_mb = mineru_size / (1024 * 1024)
    # 实测校准：
    # - 拆分链路（>100MB 触发 docx→PDF→切片并行）：实测 163MB/202页约 68s。
    #   多片并行 + PDF 压缩使处理极快，公式 60s 基线 + 1.5s/MB，留余量以防内容文字密度大的 PDF。
    # - 单份上传（<100MB）：上传 + 首轮轮询开销固定，实测 7MB ≈ 100s。
    #   公式 30s 基线 + 10s/MB，对 docx 直传 MinerU VLM 估算准。
    use_split_path = mineru_mb >= 100
    if use_split_path:
        estimated_seconds = max(60, int(60 + mineru_mb * 1.5))
    elif mineru_count:
        estimated_seconds = max(30, int(30 + mineru_mb * 10))
    else:
        estimated_seconds = 30
    est_min = max(1, estimated_seconds // 60)

    oversize_note = ""
    if biggest_mb > 200:
        oversize_note = (
            f"<br>⚠  <b>{biggest_name}</b> 大小 {biggest_mb:.1f} MB，超过 MinerU 单文件 200 MB 上限，"
            f"将自动回退本地解析（版面精度略低）。"
        )

    if use_split_path:
        color = "#b45309"
        bg = "#fffbeb"
        banner = (
            f"⏳ 共 {count} 个文件（其中 {mineru_count} 个走 MinerU，合计 {mineru_mb:.1f} MB）。"
            f"<br>最大一份 <b>{biggest_name}</b>（{biggest_mb:.1f} MB）将启用 "
            f"<b>拆分并行链路</b>：docx 先转 PDF，按每 180 页切片批量送 MinerU（绕开 200 页/文件上限）。"
            f"<br>预计耗时 <b>约 {est_min} 分钟</b>。切片并行比单份上传更快，实测 163 MB / 202 页仅需 1~2 分钟。"
            f"<br>请保持页面打开，不要刷新或关闭本程序。"
            f"{oversize_note}"
        )
    elif mineru_mb >= 20 or estimated_seconds >= 300:
        color = "#b45309"
        bg = "#fffbeb"
        banner = (
            f"⏳ 共 {count} 个文件、{total_mb:.1f} MB（MinerU 处理 {mineru_mb:.1f} MB），"
            f"预计 <b>约 {est_min} 分钟</b>。"
            f"<br>请保持页面打开，不要刷新或关闭本程序。{oversize_note}"
        )
    else:
        color = "#065f46"
        bg = "#ecfdf5"
        banner = (
            f"✅ 共 {count} 个文件、{total_mb:.1f} MB，预计 <b>~{est_min} 分钟</b>内完成。"
            f"{oversize_note}"
        )
    return (
        f"<div id='upload-preview' style='margin-top:10px; padding:10px 14px; border-radius:8px; "
        f"background:{bg}; border:1px solid {color}; color:{color}; font-size:0.88em; line-height:1.55;'>"
        f"{banner}"
        f"</div>"
    )


def _build_ui_batch_dir(source_mode: str, profile: str = DEFAULT_PROFILE) -> Path:
    profile = _resolve_profile(profile)
    base_dir = ensure_ui_batches_dir(profile)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"batch_{timestamp}_{source_mode}_{uuid4().hex[:6]}_"
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(base_dir)))


# ── 持久化数据统计与清理 ───────────────────────────────────────────────────────
def _format_size(size_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _iter_batch_dirs(profile: str | None = None) -> list[Path]:
    base = ensure_ui_batches_dir(profile)
    if not base.exists():
        return []
    batch_dirs: list[Path] = []
    try:
        candidates = list(base.iterdir())
    except OSError:
        return []
    for path in candidates:
        try:
            if path.is_dir():
                batch_dirs.append(path)
        except OSError:
            continue
    def _safe_ctime(path: Path) -> float:
        try:
            return path.stat().st_ctime
        except OSError:
            return 0

    return sorted(batch_dirs, key=_safe_ctime, reverse=True)


def _scan_unreadable_batch_dirs(profile: str | None = None) -> tuple[int, int]:
    base = ensure_ui_batches_dir(profile)
    missing_state = 0
    unreadable = 0
    try:
        candidates = list(base.iterdir())
    except OSError:
        return 0, 1
    for path in candidates:
        try:
            if not path.is_dir():
                continue
            list(path.iterdir())
        except OSError:
            unreadable += 1
            continue
        state_path = path / BATCH_STATE_FILE_NAME
        try:
            has_state = state_path.is_file()
        except OSError:
            unreadable += 1
            continue
        if not has_state:
            missing_state += 1
    return missing_state, unreadable


def _calc_dir_stats(root: Path) -> tuple[int, int]:
    total_files = 0
    total_size = 0
    try:
        entries = root.rglob("*")
        for entry in entries:
            try:
                is_file = entry.is_file()
            except OSError:
                continue
            if is_file:
                total_files += 1
                try:
                    total_size += entry.stat().st_size
                except OSError:
                    continue
    except OSError:
        return total_files, total_size
    return total_files, total_size


def scan_storage_summary(profile: str | None = None) -> tuple[str, str]:
    profile = _resolve_profile(profile)
    base = ensure_ui_batches_dir(profile)
    batches = _iter_batch_dirs(profile)
    profile_label = PROFILE_LABELS.get(profile, profile)
    if not batches:
        return (
            f"**当前 Profile**：{profile_label}（{profile}）\n\n"
            f"**持久化根目录**：`{base}`\n\n暂无批次目录，无需清理。",
            "（没有批次）",
        )

    total_files = 0
    total_size = 0
    detail_lines = [
        "| 批次目录 | 创建时间 | 文件数 | 占用 | 包含的 MD |",
        "| --- | --- | --- | --- | --- |",
    ]
    for batch in batches:
        files, size = _calc_dir_stats(batch)
        total_files += files
        total_size += size
        review_dir = batch / "review_markdown"
        md_names: list[str] = []
        try:
            if review_dir.exists():
                md_names = sorted(p.name for p in review_dir.glob("*.md"))
        except OSError:
            md_names = []
        if md_names:
            preview = "、".join(md_names[:3])
            if len(md_names) > 3:
                preview += f" 等 {len(md_names)} 份"
        else:
            preview = "—"
        try:
            ctime_raw = batch.stat().st_ctime
        except OSError:
            ctime_raw = 0
        ctime = datetime.fromtimestamp(ctime_raw).strftime("%Y-%m-%d %H:%M")
        detail_lines.append(
            f"| `{batch.name}` | {ctime} | {files} | {_format_size(size)} | {preview} |"
        )

    summary = (
        f"**当前 Profile**：{profile_label}（{profile}）\n\n"
        f"**持久化根目录**：`{base}`\n\n"
        f"共 **{len(batches)}** 个批次 · **{total_files}** 个文件 · "
        f"总占用 **{_format_size(total_size)}**"
    )
    return summary, "\n".join(detail_lines)


def refresh_storage_panel(profile: str | None = None):
    summary, details = scan_storage_summary(profile)
    return (
        summary,
        details,
        gr.update(value=False),
        "已刷新统计。",
    )


def cleanup_all_batches(confirm_checked: bool, profile: str | None = None):
    profile = _resolve_profile(profile)
    if not confirm_checked:
        summary, details = scan_storage_summary(profile)
        return (
            summary,
            details,
            gr.update(value=False),
            "⚠  请先勾选下方确认复选框再点清理按钮。",
        )

    batches = _iter_batch_dirs(profile)
    if not batches:
        summary, details = scan_storage_summary(profile)
        return (summary, details, gr.update(value=False), "当前 Profile 下没有可清理的批次。")

    removed = 0
    errors: list[str] = []
    for batch in batches:
        try:
            shutil.rmtree(batch)
            removed += 1
        except OSError as exc:
            errors.append(f"{batch.name}: {exc}")

    summary, details = scan_storage_summary(profile)
    profile_label = PROFILE_LABELS.get(profile, profile)
    status_parts = [f"✅ 已清理 {profile_label} 下 {removed}/{len(batches)} 个批次。"]
    if errors:
        status_parts.append("以下批次删除失败：" + "；".join(errors[:3]))
        if len(errors) > 3:
            status_parts.append(f"（其余 {len(errors) - 3} 个失败项见日志）")
    return (summary, details, gr.update(value=False), "\n".join(status_parts))


def _format_sample_choice(item: dict[str, object]) -> tuple[str, str]:
    title = str(item.get("title") or item.get("sample_id") or "未命名样本")
    decision = str(item.get("decision") or "")
    category = str(item.get("effective_category") or item.get("auto_category") or "待分类")
    sample_id = str(item.get("sample_id") or "")
    return (f"{title} | {decision} | {category}", sample_id)


def _format_sample_line(
    item: dict[str, object],
    dataset_id_to_name: dict[str, str] | None = None,
) -> str:
    title = str(item.get("title") or item.get("sample_id") or "未命名样本")
    sample_id = str(item.get("sample_id") or "")
    category = str(item.get("effective_category") or item.get("auto_category") or "待分类")
    review_status = str(item.get("review_status") or "未审核")
    id_to_name = dataset_id_to_name or {}
    dataset_display_parts: list[str] = []
    for dataset_id in (item.get("target_dataset_ids") or []):
        dataset_id_str = str(dataset_id)
        name = id_to_name.get(dataset_id_str)
        if name and name != dataset_id_str:
            dataset_display_parts.append(f"{name}（{dataset_id_str[:8]}…）")
        else:
            dataset_display_parts.append(dataset_id_str)
    target_dataset_text = "、".join(dataset_display_parts)
    import_status = str(item.get("import_status") or "")
    parts = [f"{title} ({sample_id})", f"分类：{category}", f"审核：{review_status}"]
    if target_dataset_text:
        parts.append(f"知识库：{target_dataset_text}")
    if import_status:
        parts.append(f"导入状态：{import_status}")
    return " | ".join(parts)


def _format_section_text(
    title: str,
    items: list[dict[str, object]],
    dataset_id_to_name: dict[str, str] | None = None,
) -> str:
    if not items:
        return f"{title}\n- 无"
    lines = [title]
    for item in items:
        lines.append(f"- {_format_sample_line(item, dataset_id_to_name)}")
    return "\n".join(lines)


def _build_batch_summary(snapshot: dict[str, object]) -> str:
    state = snapshot.get("state") or {}
    if not isinstance(state, dict):
        return "未选择批次。"
    batch_id = str(state.get("batch_id") or "")
    source_mode = str(state.get("source_mode") or "")
    created_at = str(state.get("created_at") or "")
    status = str(state.get("status") or "")
    return "\n".join(
        [
            f"批次：{batch_id or '未命名'}",
            f"模式：{source_mode or '未知'}",
            f"状态：{status or '未知'}",
            f"创建时间：{created_at or '未知'}",
        ]
    )


def _build_import_status_text(runtime_available: bool, error_message: str = "") -> str:
    if error_message:
        return error_message
    if runtime_available:
        return "Dify 配置已加载，可刷新知识库与批次状态。"
    return "Dify 未配置完整，当前仍可查看批次，但无法执行导入。"


def _resolve_dify_runtime_safe(
    dify_api_url: str,
    dify_api_key: str,
    dify_default_dataset_ids: str,
    dify_verify_ssl: bool,
):
    try:
        runtime = resolve_dify_runtime(
            api_url=dify_api_url,
            api_key=dify_api_key,
            default_dataset_ids=dify_default_dataset_ids,
            verify_ssl=dify_verify_ssl,
        )
    except ValueError as exc:
        return None, str(exc)
    return runtime, ""


def _empty_dashboard_updates(status_text: str, profile: str = DEFAULT_PROFILE, runtime: "DifyRuntime | None" = None) -> tuple:
    dataset_choices: list[tuple[str, str]] = []
    if runtime is not None:
        try:
            client = DifyClient(runtime)
            for ds in client.list_datasets():
                ds_id = str(ds.get("id") or "")
                ds_name = str(ds.get("name") or ds_id)
                if ds_id:
                    dataset_choices.append((ds_name, ds_id))
            dataset_choices.sort(key=lambda item: item[0])
        except Exception:
            pass
    missing_state, unreadable = _scan_unreadable_batch_dirs(profile)
    status_parts = [status_text]
    if missing_state or unreadable:
        detail_parts: list[str] = []
        if missing_state:
            detail_parts.append(f"{missing_state} 个缺少 {BATCH_STATE_FILE_NAME}")
        if unreadable:
            detail_parts.append(f"{unreadable} 个不可读取")
        status_parts.append(
            "提示：当前 Profile 下发现批次目录异常（"
            + "、".join(detail_parts)
            + "），这些目录不会进入批次下拉框。"
        )
    return (
        gr.update(choices=build_batch_choices(profile), value=None),
        "\n".join(part for part in status_parts if part),
        "未找到可用批次。",
        gr.update(choices=[], value=None),
        "当前没有待审核样本。",
        gr.update(choices=[], value=None),
        gr.update(choices=dataset_choices, value=[]),
        "可直接导入\n- 无",
        "待审核\n- 无",
        "已导入/失败\n- 无",
    )


def _render_dashboard(
    selected_batch_dir: str,
    dify_api_url: str,
    dify_api_key: str,
    dify_default_dataset_ids: str,
    dify_verify_ssl: bool,
    *,
    status_message: str = "",
    selected_sample_id: str = "",
    profile: str = DEFAULT_PROFILE,
) -> tuple:
    profile = _resolve_profile(profile)
    runtime, runtime_error = _resolve_dify_runtime_safe(
        dify_api_url,
        dify_api_key,
        dify_default_dataset_ids,
        dify_verify_ssl,
    )
    effective_status_message = status_message or runtime_error
    if runtime_error and status_message and runtime_error not in status_message:
        effective_status_message = f"{status_message}\n{runtime_error}"
    batch_choices = build_batch_choices(profile)
    if not batch_choices:
        return _empty_dashboard_updates(
            _build_import_status_text(runtime is not None, effective_status_message),
            profile=profile,
            runtime=runtime,
        )

    selected_value = selected_batch_dir if any(value == selected_batch_dir for _, value in batch_choices) else batch_choices[0][1]
    snapshot = collect_batch_snapshot(selected_value, runtime=runtime)
    snapshot_runtime_error = str(snapshot.get("runtime_error") or "")
    if snapshot_runtime_error:
        effective_status_message = snapshot_runtime_error if not effective_status_message else f"{effective_status_message}\n{snapshot_runtime_error}"
    pending_items = snapshot["pending_items"]
    ready_items = snapshot["ready_items"]
    history_items = snapshot["history_items"]
    category_choices = [(item, item) for item in snapshot["category_choices"]]
    dataset_choices = snapshot["dataset_choices"]
    dataset_id_to_name = {
        str(value): str(label) for label, value in dataset_choices if value
    }

    pending_choices = [_format_sample_choice(item) for item in pending_items]
    if pending_choices:
        pending_value = selected_sample_id if any(value == selected_sample_id for _, value in pending_choices) else pending_choices[0][1]
        selected_pending_item = snapshot["items_by_id"].get(pending_value) or {}
        pending_detail = _format_sample_line(selected_pending_item, dataset_id_to_name) if selected_pending_item else "当前没有待审核样本。"
        category_value = str(selected_pending_item.get("effective_category") or selected_pending_item.get("auto_category") or "")
        dataset_value = selected_pending_item.get("target_dataset_ids") or []
    else:
        pending_value = None
        pending_detail = "当前没有待审核样本。"
        category_value = None
        dataset_value = []

    return (
        gr.update(choices=batch_choices, value=selected_value),
        _build_import_status_text(runtime is not None, effective_status_message),
        _build_batch_summary(snapshot),
        gr.update(choices=pending_choices, value=pending_value),
        pending_detail,
        gr.update(choices=category_choices, value=category_value),
        gr.update(choices=dataset_choices, value=dataset_value),
        _format_section_text("可直接导入", ready_items, dataset_id_to_name),
        _format_section_text("待审核", pending_items, dataset_id_to_name),
        _format_section_text("已导入/失败", history_items, dataset_id_to_name),
    )


def refresh_import_dashboard(
    selected_batch_dir: str,
    dify_api_url: str,
    dify_api_key: str,
    dify_default_dataset_ids: str,
    dify_verify_ssl: bool,
    profile: str = DEFAULT_PROFILE,
):
    return _render_dashboard(
        selected_batch_dir,
        dify_api_url,
        dify_api_key,
        dify_default_dataset_ids,
        dify_verify_ssl,
        profile=profile,
    )


def select_pending_sample_and_refresh(
    selected_batch_dir: str,
    pending_sample_id: str,
    dify_api_url: str,
    dify_api_key: str,
    dify_default_dataset_ids: str,
    dify_verify_ssl: bool,
    profile: str = DEFAULT_PROFILE,
):
    return _render_dashboard(
        selected_batch_dir,
        dify_api_url,
        dify_api_key,
        dify_default_dataset_ids,
        dify_verify_ssl,
        selected_sample_id=pending_sample_id,
        profile=profile,
    )


def save_review_and_refresh(
    selected_batch_dir: str,
    pending_sample_id: str,
    existing_category: str,
    new_category: str,
    target_dataset_ids: list[str],
    dify_api_url: str,
    dify_api_key: str,
    dify_default_dataset_ids: str,
    dify_verify_ssl: bool,
    profile: str = DEFAULT_PROFILE,
):
    category = (new_category or "").strip() or (existing_category or "").strip()
    if not selected_batch_dir:
        return _render_dashboard("", dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl, status_message="请先选择批次。", profile=profile)
    if not pending_sample_id:
        return _render_dashboard(selected_batch_dir, dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl, status_message="当前没有可保存的待审核样本。", profile=profile)
    if not category:
        return _render_dashboard(selected_batch_dir, dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl, status_message="请先选择已有分类或输入新分类。", selected_sample_id=pending_sample_id, profile=profile)
    if not target_dataset_ids:
        return _render_dashboard(selected_batch_dir, dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl, status_message="请至少选择一个目标知识库。", selected_sample_id=pending_sample_id, profile=profile)

    runtime, _ = _resolve_dify_runtime_safe(
        dify_api_url,
        dify_api_key,
        dify_default_dataset_ids,
        dify_verify_ssl,
    )
    save_manual_review(
        selected_batch_dir,
        sample_id=pending_sample_id,
        category=category,
        dataset_ids=target_dataset_ids,
        runtime=runtime,
    )
    return _render_dashboard(
        selected_batch_dir,
        dify_api_url,
        dify_api_key,
        dify_default_dataset_ids,
        dify_verify_ssl,
        status_message="人工审核结果已保存到 sidecar 文件。",
        profile=profile,
    )


def merge_review_and_refresh(
    selected_batch_dir: str,
    dify_api_url: str,
    dify_api_key: str,
    dify_default_dataset_ids: str,
    dify_verify_ssl: bool,
    profile: str = DEFAULT_PROFILE,
):
    if not selected_batch_dir:
        return _render_dashboard("", dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl, status_message="请先选择批次。", profile=profile)
    runtime, _ = _resolve_dify_runtime_safe(
        dify_api_url,
        dify_api_key,
        dify_default_dataset_ids,
        dify_verify_ssl,
    )
    merge_reviewed_documents(selected_batch_dir, runtime=runtime)
    return _render_dashboard(
        selected_batch_dir,
        dify_api_url,
        dify_api_key,
        dify_default_dataset_ids,
        dify_verify_ssl,
        status_message="已为当前批次生成 merged 文件。",
        profile=profile,
    )


def import_ready_and_refresh(
    selected_batch_dir: str,
    dify_api_url: str,
    dify_api_key: str,
    dify_default_dataset_ids: str,
    dify_verify_ssl: bool,
    profile: str = DEFAULT_PROFILE,
):
    if not selected_batch_dir:
        return _render_dashboard("", dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl, status_message="请先选择批次。", profile=profile)
    runtime, runtime_error = _resolve_dify_runtime_safe(
        dify_api_url,
        dify_api_key,
        dify_default_dataset_ids,
        dify_verify_ssl,
    )
    if runtime_error:
        return _render_dashboard(selected_batch_dir, dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl, status_message=runtime_error, profile=profile)
    if runtime is None:
        return _render_dashboard(selected_batch_dir, dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl, status_message="Dify 配置不完整，暂无法导入。", profile=profile)
    import_ready_documents(selected_batch_dir, runtime=runtime)
    return _render_dashboard(
        selected_batch_dir,
        dify_api_url,
        dify_api_key,
        dify_default_dataset_ids,
        dify_verify_ssl,
        status_message="已执行可导入样本的一键导入，请查看批次报告与状态列表。",
        profile=profile,
    )


def import_ready_with_progress(
    selected_batch_dir: str,
    dify_api_url: str,
    dify_api_key: str,
    dify_default_dataset_ids: str,
    dify_verify_ssl: bool,
    profile: str = DEFAULT_PROFILE,
):
    profile = _resolve_profile(profile)
    progress_html_initial = _render_progress(0, "等待开始")

    def _compose(progress_html: str, dashboard_tuple: tuple) -> tuple:
        return (progress_html, *dashboard_tuple)

    if not selected_batch_dir:
        dashboard = _render_dashboard("", dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl, status_message="请先选择批次。", profile=profile)
        yield _compose(_render_progress(0, "请先选择批次"), dashboard)
        return

    runtime, runtime_error = _resolve_dify_runtime_safe(
        dify_api_url,
        dify_api_key,
        dify_default_dataset_ids,
        dify_verify_ssl,
    )
    if runtime_error:
        dashboard = _render_dashboard(selected_batch_dir, dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl, status_message=runtime_error, profile=profile)
        yield _compose(_render_progress(0, "Dify 配置无效"), dashboard)
        return
    if runtime is None:
        dashboard = _render_dashboard(selected_batch_dir, dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl, status_message="Dify 配置不完整，暂无法导入。", profile=profile)
        yield _compose(_render_progress(0, "Dify 配置不完整"), dashboard)
        return

    snapshot_preview = collect_batch_snapshot(selected_batch_dir, runtime=runtime)
    ready_count = len(snapshot_preview.get("ready_items") or [])
    if ready_count == 0:
        dashboard = _render_dashboard(selected_batch_dir, dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl, status_message="当前批次没有可导入样本。", profile=profile)
        yield _compose(_render_progress(0, "没有可导入样本"), dashboard)
        return

    dashboard_running = _render_dashboard(selected_batch_dir, dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl, status_message="Dify 导入中，请稍候...", profile=profile)
    yield _compose(_render_progress(3, f"准备导入 {ready_count} 个样本"), dashboard_running)

    progress_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()

    def _callback(event: dict) -> None:
        progress_queue.put(("event", event))

    def _runner() -> None:
        try:
            import_ready_documents(selected_batch_dir, runtime=runtime, progress_callback=_callback)
            progress_queue.put(("done", None))
        except Exception as exc:
            progress_queue.put(("error", str(exc)))

    threading.Thread(target=_runner, daemon=True).start()

    last_pct = 3
    last_message = f"准备导入 {ready_count} 个样本"

    while True:
        try:
            kind, payload = progress_queue.get(timeout=1800)
        except queue.Empty:
            dashboard = _render_dashboard(selected_batch_dir, dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl, status_message="Dify 导入超时。", profile=profile)
            yield _compose(_render_progress(last_pct, "超时未完成"), dashboard)
            return

        if kind == "done":
            dashboard_done = _render_dashboard(selected_batch_dir, dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl, status_message="Dify 导入完成，请查看各样本状态。", profile=profile)
            yield _compose(_render_progress(100, "导入完成"), dashboard_done)
            return
        if kind == "error":
            dashboard_err = _render_dashboard(selected_batch_dir, dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl, status_message=f"Dify 导入异常：{payload}", profile=profile)
            yield _compose(_render_progress(last_pct, f"导入异常：{payload}"), dashboard_err)
            return

        # kind == "event"
        event = payload if isinstance(payload, dict) else {}
        total = int(event.get("total") or ready_count or 1)
        done = int(event.get("done") or 0)
        message = str(event.get("message") or "")
        phase = str(event.get("phase") or "")
        if phase == "complete":
            last_pct = 100
        else:
            last_pct = max(3, min(97, int(3 + 94 * done / max(total, 1))))
        last_message = message or last_message
        yield _compose(_render_progress(last_pct, last_message), dashboard_running)


def _is_port_available(port: int) -> bool:
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _resolve_server_port() -> int:
    raw_port = os.getenv("GRADIO_SERVER_PORT", "").strip()
    preferred_port = int(raw_port) if raw_port.isdigit() else 7861

    for port in range(preferred_port, preferred_port + 50):
        if _is_port_available(port):
            return port

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _toggle_source_inputs(source_mode: str):
    is_url_mode = (source_mode or "").strip() == "url"
    active_mode = "url" if is_url_mode else "upload"
    return (
        gr.update(visible=not is_url_mode),
        gr.update(visible=is_url_mode),
        gr.update(value=_build_status_tip(active_mode)),
    )


def _clean_html(soup: BeautifulSoup) -> BeautifulSoup:
    for tag in soup(["script", "style", "noscript", "iframe", "svg", "canvas"]):
        tag.decompose()
    for tag in soup.find_all(True):
        attrs = dict(tag.attrs)
        for attr in list(attrs.keys()):
            if attr.lower().startswith("on"):
                tag.attrs.pop(attr, None)
    return soup


def _pick_main_html_node(soup: BeautifulSoup):
    selectors = [
        "article",
        "main",
        "[role='main']",
        ".article",
        ".article-content",
        ".article_content",
        ".content",
        ".news-content",
        ".detail",
        ".detail-content",
        ".Article_Con",
        ".trs_editor_view",
        ".TRS_Editor",
        ".TRS_UEDITOR",
        "#Zoom",
        "#zoom",
        "#content",
        "#article",
    ]
    for selector in selectors:
        node = soup.select_one(selector)
        if node and len(node.get_text(" ", strip=True)) >= 80:
            return node

    best_node = None
    best_score = -1
    keywords = ("article", "content", "detail", "main", "news", "show", "txt", "zoom", "trs")
    for node in soup.find_all(["article", "main", "section", "div"]):
        text = node.get_text(" ", strip=True)
        if len(text) < 80:
            continue
        marker_text = " ".join([
            node.name,
            node.get("id", ""),
            " ".join(node.get("class", [])),
        ]).lower()
        if "title" in marker_text and len(text) < 1000:
            continue
        score = sum(1 for keyword in keywords if keyword in marker_text)
        score = score * 3000 + len(text)
        if score > best_score:
            best_score = score
            best_node = node
    return best_node or soup.body or soup


def _download_webpage_to_markdown(url: str, target_dir: Path) -> Path:
    source_url, response = _fetch_webpage_response(url)
    encoding = response.apparent_encoding or response.encoding or "utf-8"
    html_text = response.content.decode(encoding, errors="ignore")
    soup = _clean_html(BeautifulSoup(html_text, "lxml"))
    main_node = _pick_main_html_node(soup)
    title = (soup.title.get_text(strip=True) if soup.title else "") or _slugify_url_path(source_url)
    title = re.sub(r"\s+", " ", title).strip()
    body_markdown = html_to_markdown(str(main_node), heading_style="ATX")
    body_markdown = re.sub(r"\n{3,}", "\n\n", body_markdown).strip()
    if not body_markdown:
        body_markdown = main_node.get_text("\n", strip=True)

    markdown_lines = [
        "---",
        f"原文URL: {source_url}",
        f"网页标题: {title}",
        "来源类型: html_url",
        "---",
        "",
    ]
    if not body_markdown.startswith("# "):
        markdown_lines.extend([f"# {title}"])
    markdown_lines.extend([
        f"原文: {source_url}",
        "",
        body_markdown,
        "",
    ])

    markdown_path = target_dir / f"{_slugify_url_path(source_url)}.md"
    markdown_path.write_text("\n".join(markdown_lines), encoding="utf-8")
    return markdown_path


# ── 进度条渲染 ─────────────────────────────────────────────────────────────────
def _render_progress(percent: int, message: str) -> str:
    pct = max(0, min(100, int(percent)))
    total_cells = 25
    lit = round(pct / 100 * total_cells)
    cells = "".join(
        f"<span style='flex:1; height:10px; border-radius:2px; "
        f"background:{ '#16a34a' if i < lit else '#e5e7eb'};'></span>"
        for i in range(total_cells)
    )
    return (
        "<div id='g-progress' style='margin:6px 0 4px 0;'>"
        f"<div style='display:flex; gap:2px; height:10px;'>{cells}</div>"
        "<div style='margin-top:8px; color:#0f172a; font-weight:700; "
        f"font-size:0.95em;'>{pct}% （{message}）</div></div>"
    )


def _infer_progress(log_text: str, total_files: int) -> tuple[int, str]:
    text = log_text or ""
    lines = text.splitlines()
    last_line = lines[-1] if lines else ""

    if "✅ 处理完成" in text:
        return 100, "处理完成"
    if "📦 任务核心逻辑已执行完毕" in text:
        return 95, "正在打包结果文件"
    if "目录扫描完成" in text:
        return 90, "目录扫描完成，准备打包"
    if last_line.lstrip().startswith("❌"):
        return 0, last_line.lstrip("❌ ").strip() or "处理失败"

    heartbeat = ""
    for ln in reversed(lines):
        stripped = ln.strip()
        if stripped.startswith("[MinerU]") or stripped.startswith("[Qwen]"):
            heartbeat = stripped
            break

    completed = text.count("已生成终稿MD:") + text.count("处理失败:")
    if completed > 0 and total_files > 0:
        pct = 20 + int(65 * min(completed, total_files) / max(total_files, 1))
        if heartbeat:
            return pct, f"{completed}/{total_files} · {heartbeat}"
        return pct, f"已处理 {completed}/{total_files} 份资料"

    if heartbeat and "🚀 正在启动后台转换引擎" in text:
        base_pct = 25 if total_files <= 1 else 22
        return base_pct, heartbeat

    if "🚀 正在启动后台转换引擎" in text:
        return 20, "正在启动后台转换引擎"
    if "📂 正在初始化持久批次目录" in text:
        return 10, "初始化批次目录"
    if "🌐 正在下载" in text:
        return 10, "下载并转换网页"
    if "🔍 正在预检" in text:
        return 5, "预检输入内容"
    if last_line.lstrip().startswith("⚠"):
        return 0, last_line.lstrip("⚠ ").strip() or "等待输入"
    return 0, "等待开始"


def run_scan_with_progress(
    uploaded_files,
    source_mode,
    source_url,
    profile,
    *args,
    **kwargs,
):
    profile = _resolve_profile(profile)
    mode_value = (source_mode or "upload").strip()
    if mode_value == "url":
        total_files = 1
    elif isinstance(uploaded_files, list):
        total_files = len(uploaded_files)
    elif uploaded_files:
        total_files = 1
    else:
        total_files = 0

    yield "", gr.update(value=None, interactive=False), _render_progress(0, "准备启动")
    for log, file_update in run_scan(
        uploaded_files, source_mode, source_url, profile, *args, **kwargs
    ):
        pct, msg = _infer_progress(log, total_files)
        yield log, file_update, _render_progress(pct, msg)


# ── 执行函数 ───────────────────────────────────────────────────────────────────
def run_scan(
    uploaded_files: list[gr.FileData] | None,
    source_mode: str,
    source_url: str,
    profile: str,
    pdf_extractor: str,
    enable_ocr: bool,
    enable_qwen: bool,
    mineru_token: str,
    qwen_api_key: str,
    qwen_base_url: str,
    qwen_model: str,
    dify_api_url: str = "",
    dify_api_key: str = "",
    dify_default_dataset_ids: str = "",
    dify_verify_ssl: bool = False,
    ragflow_api_url: str = "",
    ragflow_api_key: str = "",
    ragflow_default_dataset_ids: str = "",
    ragflow_verify_ssl: bool = False,
    enable_ragflow: bool = False,
    save_cfg: bool = False,
):
    profile = _resolve_profile(profile)
    if save_cfg:
        to_save: dict[str, str] = {}
        if mineru_token.strip():
            to_save["mineru vlm大模型 用于转换md格式key"] = mineru_token.strip()
        if qwen_api_key.strip():
            to_save["qwen_api_key"] = qwen_api_key.strip()
        if qwen_base_url.strip():
            to_save["qwen api连接"] = qwen_base_url.strip()
        if qwen_model.strip():
            to_save["qwen模型"] = qwen_model.strip()
        if dify_api_url.strip():
            to_save["dify_api_url"] = dify_api_url.strip()
        if dify_api_key.strip():
            to_save["dify_api_key"] = dify_api_key.strip()
        if dify_default_dataset_ids.strip():
            to_save["dify_default_dataset_ids"] = dify_default_dataset_ids.strip()
        to_save["dify_verify_ssl"] = "true" if dify_verify_ssl else "false"
        if ragflow_api_url.strip():
            to_save["ragflow_api_url"] = ragflow_api_url.strip()
        if ragflow_api_key.strip():
            to_save["ragflow_api_key"] = ragflow_api_key.strip()
        if ragflow_default_dataset_ids.strip():
            to_save["ragflow_default_dataset_ids"] = ragflow_default_dataset_ids.strip()
        to_save["ragflow_verify_ssl"] = "true" if ragflow_verify_ssl else "false"
        if to_save:
            _save_config(to_save, profile=profile)

    source_mode = (source_mode or "upload").strip()
    source_url = (source_url or "").strip()

    if source_mode == "url":
        if not source_url:
            yield "⚠  请选择网址模式后粘贴 HTML 页面地址。", gr.update(value=None, interactive=False)
            return
        try:
            source_url = _validate_source_url(source_url)
        except ValueError as exc:
            yield f"⚠  {exc}", gr.update(value=None, interactive=False)
            return
    elif not uploaded_files:
        yield "⚠  请先上传待处理的资料文件夹。", gr.update(value=None, interactive=False)
        return

    yield "🔍 正在预检输入内容...", gr.update(value=None, interactive=False)
    batch_dir = _build_ui_batch_dir(source_mode, profile=profile)
    in_dir = batch_dir / "input"
    out_dir = batch_dir / "review_markdown"
    structured_out_dir = batch_dir / "structured_outputs"
    in_dir.mkdir(parents=True)
    out_dir.mkdir(parents=True)
    structured_out_dir.mkdir(parents=True)

    if source_mode == "url":
        yield "🌐 正在下载 HTML 页面并转换为 Markdown 中间文件...", gr.update(value=None, interactive=False)
        try:
            markdown_path = _download_webpage_to_markdown(source_url, in_dir)
        except Exception as exc:
            write_batch_state(
                batch_dir,
                {
                    "batch_id": batch_dir.name,
                    "display_name": batch_dir.name,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "source_mode": source_mode,
                    "status": "failed",
                    "input_dir": str(in_dir),
                    "review_output_dir": str(out_dir),
                    "structured_output_dir": str(structured_out_dir),
                    "scan_report_path": str(structured_out_dir / "scan_report.json"),
                    "error": str(exc),
                },
            )
            shutil.rmtree(batch_dir, ignore_errors=True)
            yield f"❌ 网页转换失败：{exc}", gr.update(value=None, interactive=False)
            return
        input_desc = f"网址 1 个 -> {markdown_path.name}"
    else:
        yield "📂 正在初始化持久批次目录并同步文件结构...", gr.update(value=None, interactive=False)
        if not isinstance(uploaded_files, list):
            uploaded_files = [uploaded_files]  # type: ignore

        try:
            copy_plan, has_flattened_structure = _build_upload_copy_plan(in_dir, uploaded_files)
            for source_path, target in copy_plan:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target)
        except Exception as exc:
            write_batch_state(
                batch_dir,
                {
                    "batch_id": batch_dir.name,
                    "display_name": batch_dir.name,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "source_mode": source_mode,
                    "status": "failed",
                    "input_dir": str(in_dir),
                    "review_output_dir": str(out_dir),
                    "structured_output_dir": str(structured_out_dir),
                    "scan_report_path": str(structured_out_dir / "scan_report.json"),
                    "error": str(exc),
                },
            )
            shutil.rmtree(batch_dir, ignore_errors=True)
            yield f"❌ 上传文件准备失败：{exc}", gr.update(value=None, interactive=False)
            return
        input_desc = f"本地上传文件 {len(uploaded_files)} 个"
        if has_flattened_structure:
            input_desc += "（提示：当前上传接口未保留目录层级）"

    write_batch_state(
        batch_dir,
        {
            "batch_id": batch_dir.name,
            "display_name": f"{batch_dir.name} | {input_desc}",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source_mode": source_mode,
            "status": "running",
            "input_dir": str(in_dir),
            "review_output_dir": str(out_dir),
            "structured_output_dir": str(structured_out_dir),
            "scan_report_path": str(structured_out_dir / "scan_report.json"),
        },
    )

    yield f"🚀 正在启动后台转换引擎 (参数: {pdf_extractor})...", gr.update(value=None, interactive=False)

    cmd = [
        sys.executable, "-m", "minimum_workflow.cli",
        "--source-dir", str(in_dir),
        "--output-dir", str(out_dir),
        "--internal-output-dir", str(structured_out_dir),
        "--pdf-extractor", pdf_extractor,
    ]
    if enable_ocr:
        cmd.append("--enable-ocr")
    if enable_qwen:
        cmd.append("--enable-qwen")
    if mineru_token.strip():
        cmd += ["--mineru-token", mineru_token.strip()]
    if enable_qwen and qwen_api_key.strip():
        cmd += ["--qwen-api-key", qwen_api_key.strip()]
    if enable_qwen and qwen_base_url.strip():
        cmd += ["--qwen-base-url", qwen_base_url.strip()]
    if enable_qwen and qwen_model.strip():
        cmd += ["--qwen-model", qwen_model.strip()]

    header = f"▶  开始处理{input_desc}\n批次目录：{batch_dir}\n{'─' * 56}\n\n"
    yield header, None

    q: queue.Queue[str | None] = queue.Queue()

    def _read(proc: subprocess.Popen) -> None:
        assert proc.stdout
        for raw in proc.stdout:
            try:
                line = raw.decode("gbk").strip("\n")
            except UnicodeDecodeError:
                line = raw.decode("utf-8", errors="replace").strip("\n")
            q.put(line + "\n")
        proc.wait()
        q.put(None)

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=str(PROJECT_ROOT),
    )
    threading.Thread(target=_read, args=(proc,), daemon=True).start()

    buf = header
    while True:
        try:
            line = q.get(timeout=1800)
        except queue.Empty:
            buf += "\n⚠  等待超时，正在终止后台进程。"
            _terminate_process(proc)
            write_batch_state(
                batch_dir,
                {
                    "batch_id": batch_dir.name,
                    "display_name": f"{batch_dir.name} | {input_desc}",
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "source_mode": source_mode,
                    "status": "failed",
                    "input_dir": str(in_dir),
                    "review_output_dir": str(out_dir),
                    "structured_output_dir": str(structured_out_dir),
                    "scan_report_path": str(structured_out_dir / "scan_report.json"),
                    "error": "处理超时",
                },
            )
            shutil.rmtree(batch_dir, ignore_errors=True)
            yield buf + "\n❌ 处理超时，未生成可下载结果。", gr.update(value=None, interactive=False)
            return
        if line is None:
            break
        buf += line
        yield buf, None

    rc = proc.poll()
    if rc == 0:
        write_batch_state(
            batch_dir,
            {
                "batch_id": batch_dir.name,
                "display_name": f"{batch_dir.name} | {input_desc}",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "source_mode": source_mode,
                "status": "completed",
                "input_dir": str(in_dir),
                "review_output_dir": str(out_dir),
                "structured_output_dir": str(structured_out_dir),
                "scan_report_path": str(structured_out_dir / "scan_report.json"),
            },
        )
        yield buf + "\n📦 任务核心逻辑已执行完毕，正在打包结果文件...", gr.update(value=None, interactive=False)
        archive_full_path = _build_download_archive(out_dir)
        yield buf + "\n✅ 处理完成！结果已成功打包，并已写入持久批次目录。\n", gr.update(value=archive_full_path, interactive=True)
    elif rc is None:
        _terminate_process(proc)
        write_batch_state(
            batch_dir,
            {
                "batch_id": batch_dir.name,
                "display_name": f"{batch_dir.name} | {input_desc}",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "source_mode": source_mode,
                "status": "failed",
                "input_dir": str(in_dir),
                "review_output_dir": str(out_dir),
                "structured_output_dir": str(structured_out_dir),
                "scan_report_path": str(structured_out_dir / "scan_report.json"),
                "error": "后台进程状态异常",
            },
        )
        shutil.rmtree(batch_dir, ignore_errors=True)
        yield buf + "\n❌ 后台进程状态异常，任务已终止。", gr.update(value=None, interactive=False)
    else:
        write_batch_state(
            batch_dir,
            {
                "batch_id": batch_dir.name,
                "display_name": f"{batch_dir.name} | {input_desc}",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "source_mode": source_mode,
                "status": "failed",
                "input_dir": str(in_dir),
                "review_output_dir": str(out_dir),
                "structured_output_dir": str(structured_out_dir),
                "scan_report_path": str(structured_out_dir / "scan_report.json"),
                "error": f"处理退出码 {rc}",
            },
        )
        shutil.rmtree(batch_dir, ignore_errors=True)
        yield buf + f"\n❌ 处理退出码 {rc}，打包终止。请检查上方日志错误信息。", gr.update(value=None, interactive=False)
        return

    # RAGFlow 上传：处理完成后将成功的 Markdown 文件上传到 RAGFlow 知识库
    if enable_ragflow and ragflow_api_url.strip() and ragflow_api_key.strip():
        yield buf + "\n\n📤 正在上传到 RAGFlow...", None
        try:
            # 收集成功的 Markdown 文件
            scan_report_path = structured_out_dir / "scan_report.json"
            successful_markdown_files = []
            if scan_report_path.exists():
                report_data = json.loads(scan_report_path.read_text(encoding="utf-8"))
                for item in report_data.get("items", []):
                    if item.get("status") == "success" and item.get("structured_markdown_path"):
                        md_path = Path(item["structured_markdown_path"])
                        if md_path.exists():
                            successful_markdown_files.append(md_path)

            if successful_markdown_files:
                # 构建 RAGFlow 配置
                ragflow_config = {
                    "api_url": ragflow_api_url.strip(),
                    "api_key": ragflow_api_key.strip(),
                    "verify_ssl": str(ragflow_verify_ssl),
                }
                if ragflow_default_dataset_ids.strip():
                    ragflow_config["dataset_id"] = ragflow_default_dataset_ids.strip()

                # 上传到 RAGFlow
                ragflow_result = upload_to_ragflow(successful_markdown_files, ragflow_config)
                success_count = ragflow_result.get("success", 0)
                failed_count = ragflow_result.get("failed", 0)
                buf += f"\n✅ RAGFlow 上传完成：成功 {success_count}/{len(successful_markdown_files)}"
                if failed_count > 0:
                    buf += f"，失败 {failed_count} 个"
                yield buf, gr.update(value=archive_full_path, interactive=True)
            else:
                buf += "\n⚠️ 没有找到需要上传的 Markdown 文件"
                yield buf, gr.update(value=archive_full_path, interactive=True)
        except Exception as exc:
            buf += f"\n❌ RAGFlow 上传失败：{exc}"
            yield buf, gr.update(value=archive_full_path, interactive=True)
    else:
        yield buf + "\n✅ 处理完成！结果已成功打包，并已写入持久批次目录。\n", gr.update(value=archive_full_path, interactive=True)


# (移除了本地驱动打开函数，改为 ZIP 下载方式)


# ── 界面 ───────────────────────────────────────────────────────────────────────
def build_ui() -> gr.Blocks:
    cfg = _load_config()

    # 显式移除浏览器的暗色模式类，并为关键按钮注入原生 hover 悬浮提示
    js_light_mode = """() => {
        document.body.classList.remove('dark');
        const tooltips = {
            'run-btn': '启动自动化处理：按规则 / MinerU /（可选）Qwen 对输入资料分类、抽取、生成终稿 Markdown 并打包 ZIP 下载。可选启用 RAGFlow 上传。',
            'save-review-btn': '把当前选中的待审核样本的分类与目标知识库写入批次的审核文件（sidecar），供后续合并使用。',
            'merge-review-btn': '把所有已审核样本的分类结果合并回终稿 Markdown，生成可直接入库的 merged 文件；一键导入前必须执行。',
            'import-btn': '把已就绪（审核完成且指定了知识库）的样本推送到选定的 Dify 知识库，会自动处理分类标签绑定与元数据。',
            'refresh-import-btn': '重新读取本地批次状态，并从 Dify 拉取最新知识库列表。',
            'ragflow-upload-btn': '把当前批次中已成功生成的 Markdown 文件上传到 RAGFlow 知识库。',
            'refresh-storage-btn': '重新扫描 ui_batches 目录，统计批次数、文件数、总占用空间。',
            'cleanup-btn': '【危险操作】永久删除 ui_batches 下所有批次，包括上传的原始文件、生成的 Markdown、批次状态文件，不可恢复。'
        };
        for (const [id, title] of Object.entries(tooltips)) {
            const node = document.getElementById(id);
            if (node) {
                node.setAttribute('title', title);
                node.querySelectorAll('button').forEach(btn => btn.setAttribute('title', title));
            }
        }
    }"""

    with gr.Blocks(title="长风知识整理 · 资料入库") as demo:
        demo.load(None, None, None, js=js_light_mode)

        with gr.Row(elem_id="g-header"):
            # 左侧 (2/5)
            with gr.Column(scale=2):
                gr.HTML("""
                <div id="g-header-left">
                    <div id="g-logo">📂</div>
                    <div>
                        <div id="g-title">长风知识整理助手</div>
                        <div id="g-subtitle">资料目录 → 结构化 Markdown → 可直接入 Dify/RAGFlow 知识库</div>
                    </div>
                </div>
                """)

            # 右侧 (3/5)
            with gr.Column(scale=3):
                profile_selector = gr.Dropdown(
                    label="👥 当前企业 Profile（切换后自动加载对应 Dify / MinerU / Qwen 配置与批次）",
                    choices=PROFILES,
                    value=DEFAULT_PROFILE,
                    elem_id="profile-selector",
                )
                with gr.Accordion("⚙️ API 配置与高级选项", open=False, elem_id="header-settings"):
                    with gr.Row():
                        mineru_token = gr.Textbox(
                            label="MinerU Token",
                            value=cfg.get("mineru vlm大模型 用于转换md格式key", ""),
                            type="password", lines=1, scale=3,
                        )
                        pdf_extractor = gr.Radio(
                            choices=["mineru", "local"], value="mineru",
                            label="PDF 抽取策略", scale=2,
                        )
                    with gr.Row():
                        qwen_api_key = gr.Textbox(
                            label="Qwen API Key",
                            value=cfg.get("qwen_api_key", "") or cfg.get("qwen-key", ""),
                            type="password", lines=1,
                        )
                        qwen_base_url = gr.Textbox(
                            label="Qwen Base URL",
                            value=cfg.get("qwen api连接", "") or cfg.get("qwen_api_base", ""),
                            lines=1,
                        )
                        qwen_model = gr.Textbox(
                            label="Qwen 模型",
                            value=cfg.get("qwen模型", "") or cfg.get("qwen_model", ""),
                            lines=1,
                        )
                    with gr.Row():
                        dify_api_url = gr.Textbox(
                            label="Dify API URL",
                            value=cfg.get("dify_api_url", ""),
                            lines=1,
                        )
                        dify_api_key = gr.Textbox(
                            label="Dify API Key",
                            value=cfg.get("dify_api_key", ""),
                            type="password",
                            lines=1,
                        )
                        dify_default_dataset_ids = gr.Textbox(
                            label="默认勾选的知识库 ID（可选）",
                            info="留空则不预勾选；列表始终展示账户下全部知识库",
                            value=cfg.get("dify_default_dataset_ids", ""),
                            lines=1,
                        )
                    with gr.Row():
                        dify_verify_ssl = gr.Checkbox(
                            label="校验 Dify HTTPS 证书",
                            value=(cfg.get("dify_verify_ssl", "false").strip().lower() not in {"0", "false", "no", "off"}),
                            info="内网自签名证书场景可关闭；公网和正式证书场景应保持开启。",
                        )
                        enable_ocr = gr.Checkbox(label="启用 OCR（图片/扫描件目录）", value=False)
                        enable_qwen = gr.Checkbox(label="启用 Qwen 字段补强", value=False)
                        save_cfg = gr.Checkbox(label="保存配置到本地", value=True)
                    with gr.Row():
                        ragflow_api_url = gr.Textbox(
                            label="RAGFlow API URL",
                            value=cfg.get("ragflow_api_url", ""),
                            lines=1,
                        )
                        ragflow_api_key = gr.Textbox(
                            label="RAGFlow API Key",
                            value=cfg.get("ragflow_api_key", ""),
                            type="password",
                            lines=1,
                        )
                        ragflow_default_dataset_ids = gr.Textbox(
                            label="RAGFlow 默认知识库 ID（可选）",
                            info="留空则不预设；可在导入时手动指定",
                            value=cfg.get("ragflow_default_dataset_ids", ""),
                            lines=1,
                        )
                    with gr.Row():
                        ragflow_verify_ssl = gr.Checkbox(
                            label="校验 RAGFlow HTTPS 证书",
                            value=(cfg.get("ragflow_verify_ssl", "false").strip().lower() not in {"0", "false", "no", "off"}),
                            info="内网自签名证书场景可关闭；公网和正式证书场景应保持开启。",
                        )
                        enable_ragflow = gr.Checkbox(label="启用 RAGFlow 上传", value=False)

        # 主区域：四列 —— 输入 | 日志+进度 | Dify 控制 | Dify 状态
        with gr.Row():
            # 第 1 列：输入方式 + 执行动作
            with gr.Column(scale=5, min_width=240):
                gr.HTML('<div class="g-section">输入方式</div>')
                source_mode = gr.Radio(
                    choices=[("上传资料目录", "upload"), ("粘贴 HTML 网址", "url")],
                    value="upload",
                    label="选择输入来源",
                )

                with gr.Column(visible=True) as upload_input_group:
                    source_files = gr.File(
                        label="📂 选择本地资料目录",
                        file_count="directory",
                        type="filepath",
                        elem_id="upload-box"
                    )
                    upload_preview = gr.HTML("")
                    gr.HTML(
                        "<div style='margin-top:8px; color:#475569; font-size:0.85em;'>"
                        "当前模式为目录上传；若要转换网页，请切换上方到“粘贴 HTML 网址”。"
                        "</div>"
                        "<div style='margin-top:6px; color:#92400e; font-size:0.82em;'>"
                        "注意：Gradio 目录上传不保留子目录层级；同名文件请先改名。"
                        "</div>"
                        "<div style='margin-top:6px; color:#0c4a6e; font-size:0.82em;'>"
                        "📦 <b>文件大小说明</b>：MinerU 公开批量接口单文件上限约 <b>200 MB</b>；"
                        "超过 200 MB 的 PDF / docx 会自动回退到本地解析引擎（pypdf / pdfplumber / docx XML），"
                        "仅版面不如 MinerU 精细。"
                        "<br>🕐 <b>耗时参考</b>（实测）：7 MB 单份约 1.5 分钟；100+ MB 会启用拆分并行链路，"
                        "163 MB / 202 页实测 <b>约 1 分钟</b>完成。请选择文件后查看上方自动显示的预计时长。"
                        "</div>"
                    )

                with gr.Column(visible=False) as url_input_group:
                    gr.HTML("<div style='margin-bottom:8px; color:#166534; font-size:0.95em; font-weight:700;'>网址转换入口：请粘贴单个 HTML 页面地址，系统会先转成 Markdown 中间文件再走主链路。</div>")
                    source_url = gr.Textbox(
                        label="🌐 粘贴 HTML 页面网址",
                        placeholder="例如：https://fgw.guizhou.gov.cn/fggz/tzgg/202604/t20260410_89982551.html",
                        lines=3,
                    )

                gr.HTML("<div style='height:16px'></div>")
                gr.HTML('<div class="g-section">执行动作</div>')

                run_btn = gr.Button("▶  开始自动化处理", variant="primary",
                                    elem_id="run-btn")

                result_file = gr.DownloadButton(
                    label="📦 点击这里：下载最终处理结果 (ZIP)",
                    elem_id="download-btn",
                    interactive=False,
                    visible=True,
                )

                status_tip = gr.HTML(_build_status_tip("upload"))

            # 第 2 列：实时处理日志 + 进度条
            with gr.Column(scale=6, min_width=300):
                gr.HTML('<div class="g-section">实时处理日志 (详细)</div>')
                progress_html = gr.HTML(_render_progress(0, "等待开始"))
                log_out = gr.Textbox(
                    label="", lines=28, max_lines=60,
                    interactive=False, elem_id="log-area",
                    placeholder="处理细节将在此终端实时显示...",
                )

            # 第 3 列：Dify 导入控制（×2.2 放大）
            with gr.Column(scale=11, min_width=360):
                gr.HTML('<div class="g-section">Dify 导入</div>')
                initial_batch_choices = build_batch_choices(DEFAULT_PROFILE)
                initial_batch_value = initial_batch_choices[0][1] if initial_batch_choices else None

                batch_selector = gr.Dropdown(
                    label="选择持久批次",
                    choices=initial_batch_choices,
                    value=initial_batch_value,
                )
                refresh_import_btn = gr.Button("🔄 刷新批次与知识库", elem_id="refresh-import-btn")
                pending_selector = gr.Dropdown(label="待审核样本", choices=[], value=None)
                existing_category = gr.Dropdown(label="已有分类", choices=[], value=None, allow_custom_value=False)
                new_category = gr.Textbox(label="新建分类名称", placeholder="若列表没有对应分类，可在这里输入")
                target_dataset_ids = gr.CheckboxGroup(label="目标知识库", choices=[], value=[])
                save_review_btn = gr.Button("💾 保存人工分类", variant="secondary", elem_id="save-review-btn")
                merge_review_btn = gr.Button("🧩 生成合并文件", variant="secondary", elem_id="merge-review-btn")
                import_btn = gr.Button("⬆️ 一键导入已就绪样本", variant="primary", elem_id="import-btn")

            # 第 4 列：Dify 状态 + 详情（相应缩小）
            with gr.Column(scale=8, min_width=320):
                dify_status = gr.Textbox(label="Dify 状态", lines=2, interactive=False)
                dify_progress_html = gr.HTML(_render_progress(0, "等待开始"))
                batch_summary = gr.Textbox(label="批次概览", lines=4, interactive=False)
                pending_detail = gr.Textbox(label="当前待审核样本", lines=3, interactive=False)
                ready_summary = gr.Textbox(label="可直接导入", lines=6, interactive=False)

            # 第 5 列：RAGFlow 导入控制
            with gr.Column(scale=8, min_width=320):
                gr.HTML('<div class="g-section">RAGFlow 导入</div>')
                ragflow_dataset_id = gr.Textbox(
                    label="RAGFlow 知识库 ID",
                    info="留空则使用配置文件中的默认知识库",
                    value=cfg.get("ragflow_default_dataset_ids", ""),
                    lines=1,
                )
                ragflow_upload_btn = gr.Button("⬆️ 上传到 RAGFlow", variant="primary", elem_id="ragflow-upload-btn")
                ragflow_status = gr.Textbox(label="RAGFlow 状态", lines=2, interactive=False)
                ragflow_progress_html = gr.HTML(_render_progress(0, "等待开始"))
                pending_summary = gr.Textbox(label="待审核", lines=6, interactive=False)
                history_summary = gr.Textbox(label="已导入 / 失败", lines=6, interactive=False)

        gr.HTML("<div style='height:20px'></div>")
        with gr.Accordion(
            "🗂 持久化数据管理（上传原件 + 生成 MD + 批次状态）",
            open=False,
            elem_id="storage-panel",
        ):
            initial_summary, initial_details = scan_storage_summary(DEFAULT_PROFILE)
            storage_summary_md = gr.Markdown(initial_summary)
            with gr.Accordion("展开查看各批次明细", open=False):
                storage_details_md = gr.Markdown(initial_details)
            with gr.Row():
                refresh_storage_btn = gr.Button("🔄 刷新统计", variant="secondary", elem_id="refresh-storage-btn")
                cleanup_status = gr.Textbox(
                    label="清理状态",
                    lines=2,
                    interactive=False,
                    placeholder="勾选下方复选框后点右侧红色按钮即可清理全部批次。",
                )
            confirm_cleanup = gr.Checkbox(
                label="我已确认要永久删除全部批次（上传原文件、生成的 Markdown、批次状态文件均会被清空，不可恢复）",
                value=False,
            )
            cleanup_btn = gr.Button("🗑  一键清理全部批次", variant="stop", elem_id="cleanup-btn")

        # 事件绑定
        source_mode.change(
            _toggle_source_inputs,
            inputs=source_mode,
            outputs=[upload_input_group, url_input_group, status_tip],
        )
        source_files.change(
            _format_upload_preview,
            inputs=[source_files],
            outputs=[upload_preview],
        )

        run_btn.click(
            run_scan_with_progress,
            inputs=[source_files, source_mode, source_url,
                    profile_selector,
                    pdf_extractor,
                    enable_ocr, enable_qwen,
                    mineru_token, qwen_api_key, qwen_base_url, qwen_model,
                    dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl,
                    ragflow_api_url, ragflow_api_key, ragflow_default_dataset_ids, ragflow_verify_ssl, enable_ragflow,
                    save_cfg],
            outputs=[log_out, result_file, progress_html],
        )

        refresh_outputs = [
            batch_selector,
            dify_status,
            batch_summary,
            pending_selector,
            pending_detail,
            existing_category,
            target_dataset_ids,
            ready_summary,
            pending_summary,
            history_summary,
        ]

        refresh_import_btn.click(
            refresh_import_dashboard,
            inputs=[batch_selector, dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl, profile_selector],
            outputs=refresh_outputs,
        )
        batch_selector.change(
            refresh_import_dashboard,
            inputs=[batch_selector, dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl, profile_selector],
            outputs=refresh_outputs,
        )
        pending_selector.change(
            select_pending_sample_and_refresh,
            inputs=[batch_selector, pending_selector, dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl, profile_selector],
            outputs=refresh_outputs,
        )
        save_review_btn.click(
            save_review_and_refresh,
            inputs=[
                batch_selector,
                pending_selector,
                existing_category,
                new_category,
                target_dataset_ids,
                dify_api_url,
                dify_api_key,
                dify_default_dataset_ids,
                dify_verify_ssl,
                profile_selector,
            ],
            outputs=refresh_outputs,
        )
        merge_review_btn.click(
            merge_review_and_refresh,
            inputs=[batch_selector, dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl, profile_selector],
            outputs=refresh_outputs,
        )
        import_btn.click(
            import_ready_with_progress,
            inputs=[batch_selector, dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl, profile_selector],
            outputs=[dify_progress_html, *refresh_outputs],
        )

        storage_outputs = [storage_summary_md, storage_details_md, confirm_cleanup, cleanup_status]
        refresh_storage_btn.click(
            refresh_storage_panel,
            inputs=[profile_selector],
            outputs=storage_outputs,
        )
        cleanup_btn.click(
            cleanup_all_batches,
            inputs=[confirm_cleanup, profile_selector],
            outputs=storage_outputs,
        )

        # Profile 切换：重载配置字段 + 刷新批次/存储面板
        def _on_profile_change(new_profile):
            new_profile = _resolve_profile(new_profile)
            cfg2 = _load_config(new_profile)
            mineru_val = cfg2.get("mineru vlm大模型 用于转换md格式key", "")
            qwen_key_val = cfg2.get("qwen_api_key", "") or cfg2.get("qwen-key", "")
            qwen_url_val = cfg2.get("qwen api连接", "") or cfg2.get("qwen_api_base", "")
            qwen_model_val = cfg2.get("qwen模型", "") or cfg2.get("qwen_model", "")
            dify_url_val = cfg2.get("dify_api_url", "")
            dify_key_val = cfg2.get("dify_api_key", "")
            dify_ids_val = cfg2.get("dify_default_dataset_ids", "")
            dify_verify_ssl_val = cfg2.get("dify_verify_ssl", "false").strip().lower() not in {"0", "false", "no", "off"}
            ragflow_url_val = cfg2.get("ragflow_api_url", "")
            ragflow_key_val = cfg2.get("ragflow_api_key", "")
            ragflow_ids_val = cfg2.get("ragflow_default_dataset_ids", "")
            ragflow_verify_ssl_val = cfg2.get("ragflow_verify_ssl", "false").strip().lower() not in {"0", "false", "no", "off"}
            dashboard = _render_dashboard(
                "", dify_url_val, dify_key_val, dify_ids_val, dify_verify_ssl_val,
                status_message=f"已切换到 Profile：{PROFILE_LABELS.get(new_profile, new_profile)}",
                profile=new_profile,
            )
            summary, details = scan_storage_summary(new_profile)
            return (
                mineru_val, qwen_key_val, qwen_url_val, qwen_model_val,
                dify_url_val, dify_key_val, dify_ids_val, gr.update(value=dify_verify_ssl_val),
                ragflow_url_val, ragflow_key_val, ragflow_ids_val, gr.update(value=ragflow_verify_ssl_val),
                *dashboard,
                summary, details, gr.update(value=False),
                f"已切换到 {PROFILE_LABELS.get(new_profile, new_profile)}",
            )

        profile_selector.change(
            _on_profile_change,
            inputs=[profile_selector],
            outputs=[
                mineru_token, qwen_api_key, qwen_base_url, qwen_model,
                dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl,
                ragflow_api_url, ragflow_api_key, ragflow_default_dataset_ids, ragflow_verify_ssl,
                *refresh_outputs,
                storage_summary_md, storage_details_md, confirm_cleanup, cleanup_status,
            ],
        )

        # RAGFlow 上传按钮事件
        def ragflow_upload_with_progress(
            batch_dir,
            ragflow_api_url,
            ragflow_api_key,
            ragflow_dataset_id,
            ragflow_verify_ssl,
            profile,
        ):
            profile = _resolve_profile(profile)
            if not batch_dir:
                yield _render_progress(0, "请先选择批次"), "请先选择批次"
                return
            if not ragflow_api_url.strip() or not ragflow_api_key.strip():
                yield _render_progress(0, "请填写 RAGFlow API URL 和 API Key"), "请填写 RAGFlow API URL 和 API Key"
                return

            yield _render_progress(5, "正在准备上传到 RAGFlow..."), "正在准备上传..."

            try:
                # 构建 RAGFlow 配置
                ragflow_config = {
                    "api_url": ragflow_api_url.strip(),
                    "api_key": ragflow_api_key.strip(),
                    "verify_ssl": str(ragflow_verify_ssl),
                }
                if ragflow_dataset_id.strip():
                    ragflow_config["dataset_id"] = ragflow_dataset_id.strip()

                # 收集成功的 Markdown 文件
                state = load_batch_state(batch_dir)
                structured_output_dir = Path(str(state.get("structured_output_dir") or ""))
                scan_report_path = structured_output_dir / "scan_report.json"

                successful_markdown_files = []
                if scan_report_path.exists():
                    report_data = json.loads(scan_report_path.read_text(encoding="utf-8"))
                    for item in report_data.get("items", []):
                        if item.get("status") == "success" and item.get("structured_markdown_path"):
                            md_path = Path(item["structured_markdown_path"])
                            if md_path.exists():
                                successful_markdown_files.append(md_path)

                if not successful_markdown_files:
                    yield _render_progress(0, "没有找到需要上传的 Markdown 文件"), "没有找到需要上传的 Markdown 文件"
                    return

                total = len(successful_markdown_files)
                yield _render_progress(10, f"准备上传 {total} 个文件..."), f"准备上传 {total} 个文件..."

                # 上传到 RAGFlow
                def progress_callback(payload):
                    msg = payload.get("message", "")
                    total = payload.get("total", 0)
                    done = payload.get("done", 0)
                    pct = max(10, min(95, int(10 + 85 * done / max(total, 1))))
                    return pct, msg

                results = batch_upload_to_ragflow(
                    RagflowClient(RagflowRuntime(
                        api_url=ragflow_config["api_url"],
                        api_key=ragflow_config["api_key"],
                        default_dataset_ids=[ragflow_config.get("dataset_id", "")],
                        verify_ssl=ragflow_config.get("verify_ssl", "true").lower() in {"true", "1", "yes"},
                    )),
                    ragflow_config.get("dataset_id", ""),
                    successful_markdown_files,
                )

                success_count = sum(1 for r in results if r["status"] == "success")
                failed_count = sum(1 for r in results if r["status"] == "failed")

                if failed_count == 0:
                    yield _render_progress(100, f"上传完成：成功 {success_count}/{total}"), f"✅ RAGFlow 上传完成：成功 {success_count}/{total}"
                else:
                    yield _render_progress(100, f"上传完成：成功 {success_count}/{total}，失败 {failed_count}"), f"⚠️ RAGFlow 上传完成：成功 {success_count}/{total}，失败 {failed_count}"

            except Exception as exc:
                yield _render_progress(0, f"上传失败：{exc}"), f"❌ RAGFlow 上传失败：{exc}"

        ragflow_upload_btn.click(
            ragflow_upload_with_progress,
            inputs=[batch_selector, ragflow_api_url, ragflow_api_key, ragflow_dataset_id, ragflow_verify_ssl, profile_selector],
            outputs=[ragflow_progress_html, ragflow_status],
        )

        demo.load(
            refresh_import_dashboard,
            inputs=[batch_selector, dify_api_url, dify_api_key, dify_default_dataset_ids, dify_verify_ssl, profile_selector],
            outputs=refresh_outputs,
        )

    return demo


if __name__ == "__main__":
    # 规避系统代理拦截 Gradio 自检请求（localhost/127.0.0.1 必须直连，否则返回 502）
    _no_proxy_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
    for _env_key in ("NO_PROXY", "no_proxy"):
        _existing = {h.strip() for h in os.environ.get(_env_key, "").split(",") if h.strip()}
        os.environ[_env_key] = ",".join(sorted(_existing | _no_proxy_hosts))

    demo = build_ui()
    demo.launch(
        server_name=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"),
        server_port=_resolve_server_port(),
        share=False,
        inbrowser=True,
        show_error=True,
        css=STYLE,
        theme=gr.themes.Default(),
    )
