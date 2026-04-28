"""产品参数确认函独立模块（E 类）。

场景：投标资料里的"产品参数确认函"（制造商出具给采购方的参数承诺书），
形态与检测报告完全不同，但常与检测报告混在同一 PDF 中：
- 标题：# 产品参数确认函
- 致语：致：xxx消防救援总队
- 主语：我公司：xxx（产品制造商名称）作为 xxx（产品名称）生产厂家
- 参数表：管道表格，列头含 `序号|产品名称|品牌型号|响应产品参数|备注`
- 签章：制造商盖章：xxx
- 日期：日期：YYYY年MM月DD日

一个 PDF 常含多份确认函（一个产品一份），按 `# 产品参数确认函` 标题切分。

设计约束（与 detection_report_module 对齐）：
- 分类器跑在 MinerU 清洗后 Markdown 上
- 不删原文，YAML frontmatter + 结构化正文 + 原文全文
- 分类命中 <3 个特征即视为非参数确认函，上游走兜底流程
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from minimum_workflow.detection_report_module import (
    _FEATURE_WEIGHTS as _DR_FEATURE_WEIGHTS,  # 仅用于对比，未实际使用
    ClassificationResult,
)


# ---------------------------------------------------------------------------
# 1. 分类器特征（8 条，命中 ≥3 判为参数确认函）
# ---------------------------------------------------------------------------

_FEATURE_PATTERNS: dict[str, re.Pattern[str]] = {
    "P1.标题": re.compile(r"(?m)^#+\s*产品?参数确认函"),
    "P2.致语": re.compile(r"致[：:]\s*[^\n，,。；;]{2,40}"),
    "P3.我公司主语": re.compile(r"我公司[：:]\s*[^\n，,。；;（(]{2,60}"),
    "P4.生产厂家": re.compile(r"作为[^\n]{0,60}生产厂家"),
    "P5.项目号": re.compile(r"项目[号编]号?[：:]\s*[A-Za-z0-9\-]{3,30}|[（(]项目号[)）]"),
    "P6.制造商盖章": re.compile(r"制造商盖章|(?:生产)?厂家盖章"),
    "P7.参数表头": re.compile(
        r"[|｜]\s*序号\s*[|｜]\s*产品名称\s*[|｜]\s*(?:品牌)?型号\s*[|｜]"
        r"|[|｜]\s*序号\s*[|｜]\s*产品名称\s*[|｜]\s*品牌型号\s*[|｜]"
    ),
    "P8.落款日期": re.compile(r"(?m)^\s*日期[：:]\s*\d{4}\s*[\-年./]\s*\d{1,2}"),
}

_FEATURE_WEIGHTS: dict[str, float] = {
    "P1.标题": 3.0,        # 最硬
    "P2.致语": 1.5,
    "P3.我公司主语": 2.0,
    "P4.生产厂家": 2.5,
    "P5.项目号": 1.0,
    "P6.制造商盖章": 2.0,
    "P7.参数表头": 2.0,
    "P8.落款日期": 1.0,
}
_WEIGHT_TOTAL = sum(_FEATURE_WEIGHTS.values())

DEFAULT_CLASSIFIER_THRESHOLD = 3


def _group_score(markdown: str) -> tuple[int, dict[str, bool]]:
    hits: dict[str, bool] = {}
    for name, pattern in _FEATURE_PATTERNS.items():
        hits[name] = bool(pattern.search(markdown))
    return sum(1 for v in hits.values() if v), hits


def _compute_weighted(hits: dict[str, bool]) -> tuple[float, float]:
    weighted = sum(_FEATURE_WEIGHTS.get(g, 0.0) for g, v in hits.items() if v)
    confidence = min(1.0, weighted / _WEIGHT_TOTAL) if _WEIGHT_TOTAL else 0.0
    return weighted, confidence


def classify_parameter_letter(
    markdown: str,
    *,
    threshold: int = DEFAULT_CLASSIFIER_THRESHOLD,
) -> ClassificationResult:
    """命中 ≥ threshold 个特征判为参数确认函。"""
    score, hits = _group_score(markdown or "")
    weighted, confidence = _compute_weighted(hits)
    return ClassificationResult(
        is_detection_report=score >= threshold,  # 复用 dataclass，语义：是否参数确认函
        score=score,
        hits=hits,
        weighted_score=round(weighted, 2),
        confidence=round(confidence, 3),
    )


# ---------------------------------------------------------------------------
# 2. 多子函切分（按 `# 产品参数确认函` 标题位置切）
# ---------------------------------------------------------------------------

_LETTER_TITLE_PATTERN = re.compile(r"(?m)^#+\s*产品?参数确认函\s*$")


@dataclass
class ParameterLetter:
    product_name: str
    start_offset: int
    end_offset: int
    text: str
    fields: dict[str, str] = field(default_factory=dict)
    classifier: ClassificationResult | None = None


def split_letters(markdown: str) -> list[ParameterLetter]:
    """按 `# 产品参数确认函` 标题切。

    - 0 个标题：返回空列表（调用方回退，可把整篇作为单份兜底）
    - 1 个标题：整篇作为一份
    - ≥2 个标题：按相邻起点切段
    """
    starts = [m.start() for m in _LETTER_TITLE_PATTERN.finditer(markdown)]
    if not starts:
        return []
    letters: list[ParameterLetter] = []
    total = len(markdown)
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else total
        text = markdown[start:end]
        letters.append(ParameterLetter(product_name="", start_offset=start, end_offset=end, text=text))
    return letters


# ---------------------------------------------------------------------------
# 3. 字段抽取
# ---------------------------------------------------------------------------

_DATE_PATTERN = r"(\d{4})\s*[\-年./]\s*(\d{1,2})\s*[\-月./]\s*(\d{1,2})"


def _normalize_date(raw: str) -> str:
    m = re.search(_DATE_PATTERN, raw)
    if not m:
        return raw.strip()
    y, mth, d = m.groups()
    return f"{int(y):04d}-{int(mth):02d}-{int(d):02d}"


def _first_group(text: str, pattern: str, flags: int = 0) -> str:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else ""


def _extract_model_from_table(text: str) -> str:
    """从参数表的"品牌型号"列拿第一个非空值。

    表格形态：| 序号 | 产品名称 | 品牌型号 | 响应产品参数 | 备注 |
              | 1 | 水下机器人 | 博雅王道ROBOSEA-ROV-25 | ... | / |
    表头后紧跟分隔行 `| --- | --- |...`，再是首条数据行。
    """
    lines = text.splitlines()
    header_idx = -1
    for i, line in enumerate(lines):
        if "序号" in line and "品牌型号" in line and "产品名称" in line:
            header_idx = i
            break
    if header_idx < 0:
        return ""
    # 找表头所在行的列数，跳过分隔行
    header_cells = [c.strip() for c in lines[header_idx].strip("|").split("|")]
    try:
        brand_col = header_cells.index("品牌型号")
    except ValueError:
        # 可能是"型号"
        for idx, c in enumerate(header_cells):
            if "品牌型号" in c or c == "型号":
                brand_col = idx
                break
        else:
            return ""
    # 往后找首条数据行
    for line in lines[header_idx + 1:]:
        if not line.strip().startswith("|"):
            continue
        if re.match(r"^\|\s*-+", line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) <= brand_col:
            continue
        value = cells[brand_col]
        if value and value not in {"-", "/", "无"}:
            return value[:80]
    return ""


def extract_letter_fields(letter_text: str) -> dict[str, str]:
    """从一份参数确认函文本抽字段。

    输出字段：
      addressee / manufacturer / supplier / product_name / model /
      project_name / project_no / issue_date
    """
    text = letter_text

    addressee = _first_group(text, r"致[：:]\s*([^\n，,。；;]{2,40})")
    manufacturer = _first_group(
        text, r"我公司[：:]\s*([^\n，,。；;（(]{2,60})"
    )
    supplier = _first_group(
        text, r"配合\s*([^\n，,。；;（(]{2,60})\s*[（(]\s*供应商名称"
    )
    product_name = _first_group(
        text, r"作为\s*([^\n，,。；;（(]{2,40})\s*[（(]?\s*产品名称"
    )
    project_name = _first_group(
        text, r"贵单位组织的[：:]?\s*([^\n，,。；;（(]{4,80})\s*[（(]?\s*项目名称"
    )
    project_no = _first_group(
        text, r"[、，,]\s*([A-Za-z0-9\-]{3,30})\s*[（(]?\s*项目号"
    )
    if not project_no:
        project_no = _first_group(text, r"项目[号编]号?[：:]\s*([A-Za-z0-9\-]{3,30})")

    model = _extract_model_from_table(text)

    issue_date = ""
    m = re.search(rf"(?m)^\s*日期[：:]\s*{_DATE_PATTERN}", text)
    if m:
        issue_date = _normalize_date(m.group(0))

    return {
        "addressee": addressee,
        "manufacturer": manufacturer,
        "supplier": supplier,
        "product_name": product_name,
        "model": model,
        "project_name": project_name,
        "project_no": project_no,
        "issue_date": issue_date,
    }


# ---------------------------------------------------------------------------
# 4. 渲染
# ---------------------------------------------------------------------------

_FILENAME_SAFE_PATTERN = re.compile(r"[\\/:*?\"<>|\s]+")


def _sanitize_for_filename(value: str) -> str:
    cleaned = _FILENAME_SAFE_PATTERN.sub("_", (value or "").strip())
    return cleaned.strip("_") or "未命名"


def build_letter_filename(fields: dict[str, str]) -> str:
    """`参数确认函_<产品名称>_<型号>_<日期>.md`；缺失部分用占位符。"""
    product = _sanitize_for_filename(fields.get("product_name") or "未知产品")
    model = _sanitize_for_filename(fields.get("model") or "未知型号")
    date = _sanitize_for_filename(fields.get("issue_date") or "未知日期")
    return f"参数确认函_{product}_{model}_{date}.md"


def _yaml_line(key: str, value: str) -> str:
    safe = (value or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'{key}: "{safe}"'


def render_letter_md(
    letter: ParameterLetter,
    source_meta: dict[str, str],
) -> tuple[str, str]:
    f = letter.fields
    lines: list[str] = ["---"]
    lines.append(_yaml_line("document_type", "产品参数确认函"))
    for key in (
        "product_name",
        "model",
        "manufacturer",
        "supplier",
        "addressee",
        "project_name",
        "project_no",
        "issue_date",
    ):
        lines.append(_yaml_line(key, f.get(key, "")))
    lines.append(_yaml_line("source_file", source_meta.get("source_file", "")))
    lines.append(_yaml_line("source_path", source_meta.get("source_path", "")))
    lines.append(_yaml_line("extract_time", source_meta.get("extract_time", "")))
    if letter.classifier is not None:
        lines.append(f"classifier_score: {letter.classifier.score}")
        lines.append(f"classifier_weighted: {letter.classifier.weighted_score}")
        lines.append(f"classifier_confidence: {letter.classifier.confidence}")
    lines.append("---")
    lines.append("")
    lines.append("# 产品参数确认函结构化信息")
    lines.append("")
    lines.append("## 基本信息")
    lines += [
        f"- 产品名称：{f.get('product_name','')}",
        f"- 品牌型号：{f.get('model','')}",
        f"- 制造商：{f.get('manufacturer','')}",
        f"- 供应商：{f.get('supplier','')}",
        f"- 致：{f.get('addressee','')}",
    ]
    lines.append("")
    lines.append("## 项目信息")
    lines += [
        f"- 项目名称：{f.get('project_name','')}",
        f"- 项目号：{f.get('project_no','')}",
        f"- 落款日期：{f.get('issue_date','')}",
    ]
    lines.append("")
    lines.append("## 原文")
    lines.append("")
    lines.append(letter.text.strip())
    lines.append("")
    return build_letter_filename(f), "\n".join(lines)


# ---------------------------------------------------------------------------
# 5. 顶层入口
# ---------------------------------------------------------------------------

def process_parameter_letter(
    markdown: str,
    source_meta: dict[str, str],
) -> tuple[ClassificationResult, list[tuple[str, str]], list[ParameterLetter]]:
    """顶层入口，返回 (整篇分类, [(filename, md_content)...], letters)。"""
    cls = classify_parameter_letter(markdown)
    if not cls.is_detection_report:  # 这里的语义是"是否参数确认函"
        return cls, [], []

    letters = split_letters(markdown)
    if not letters:
        letters = [ParameterLetter(product_name="", start_offset=0, end_offset=len(markdown), text=markdown)]

    outputs: list[tuple[str, str]] = []
    for letter in letters:
        letter.fields = extract_letter_fields(letter.text)
        letter.product_name = letter.fields.get("product_name", "")
        letter.classifier = classify_parameter_letter(letter.text, threshold=2)  # 子函阈值降为 2
        outputs.append(render_letter_md(letter, source_meta))
    return cls, outputs, letters


def build_parameter_classifier_json(
    overall: ClassificationResult,
    letters: list[ParameterLetter],
    source_meta: dict[str, str],
) -> dict:
    return {
        "source_file": source_meta.get("source_file", ""),
        "source_path": source_meta.get("source_path", ""),
        "extract_time": source_meta.get("extract_time", ""),
        "document_type": "产品参数确认函",
        "overall": {
            "is_parameter_letter": overall.is_detection_report,
            "score": overall.score,
            "weighted_score": overall.weighted_score,
            "confidence": overall.confidence,
            "hits": overall.hits,
        },
        "letters": [
            {
                "product_name": letter.fields.get("product_name", ""),
                "model": letter.fields.get("model", ""),
                "score": letter.classifier.score if letter.classifier else 0,
                "weighted_score": letter.classifier.weighted_score if letter.classifier else 0.0,
                "confidence": letter.classifier.confidence if letter.classifier else 0.0,
                "hits": letter.classifier.hits if letter.classifier else {},
            }
            for letter in letters
        ],
    }
