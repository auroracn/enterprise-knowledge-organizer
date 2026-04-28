"""
检测报告独立模块。

职责：
1. 前置弱信号：按文件名判断"疑似检测报告"，上游据此强制启用 OCR。
2. 后置分类：在 MinerU 清洗后 MD 上跑 8 条通用特征，命中 ≥3 则归为检测报告。
3. 多子报告切分：按规范化的"报告编号"分组切段。
4. 字段抽取：report_no / product_name / model / manufacturer / test_organization /
              test_basis / test_result / report_date / expire_date。
5. 渲染：一份子报告一个 MD + YAML frontmatter；文件名 `设备检验报告_<型号>_<编号>_<日期>.md`。

设计约束（用户确认）：
- **不按发证机构识别**，全部走通用特征；下次可能是新机构。
- **分类器跑在 MinerU 清洗后的文本上**，不跑原始 docx/pdf（扫描图正文在 OCR 前无特征）。
- 字段缺失时不在渲染里硬塞，保持空白跳过。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# 1. 分类器特征（与进度文档中的 8 条一致，已在 27 份全量样本上验证 100% 精确率）
# ---------------------------------------------------------------------------

_FEATURE_PATTERNS: dict[str, re.Pattern[str]] = {
    "G1.标题": re.compile(r"(?m)^#+\s*检[验测](检测)?报告"),
    "G2a.报告编号": re.compile(r"(报告编号|委托编号)[.:：\s]*[A-Za-z0-9][A-Za-z0-9\-/().]{3,}"),
    "G2b.No编号行": re.compile(r"(?m)^\s*No[\s.:]+[A-Za-z0-9()\-./]{4,}"),
    "G3.页码": re.compile(r"共\s*\d+\s*页\s*第\s*\d+\s*页|第\s*\d+\s*页\s*共\s*\d+\s*页"),
    "G4a.检测依据": re.compile(r"检[验测]依据"),
    "G4b.检测结论": re.compile(r"检[验测]结论"),
    "G4c.检测类别": re.compile(r"检[验测]类别"),
    "G4d.型式/委托": re.compile(r"型式试验|委托检验|委托试验"),
    "G5a.委托人/单位": re.compile(r"(认证)?委托(人|单位)"),
    "G5b.受检单位": re.compile(r"受检单位"),
    "G5c.生产企业": re.compile(r"生产(企业|单位|厂家)"),
    "G5d.样品信息": re.compile(r"样品状态|样品名称|样品型号"),
    "G5e.受理/收样": re.compile(r"受理日期|收样日期|送样日期"),
    "G5f.抽样": re.compile(r"抽样(者|基数|地点|日期)"),
    "G6.机构名": re.compile(
        r"检验检测(中心|机构|公司|研究所|研究院)"
        r"|质量监督检验|计量检测|检测(单位|机构)|质检(中心|研究院)"
    ),
    "G7.专用章": re.compile(r"检验检?测?专用章|检验报告专用章"),
    "G8a.CNAS": re.compile(r"CNAS\s*[A-Z]?\d+"),
    "G8b.国认监": re.compile(r"国认监"),
    "G8c.校验码": re.compile(r"校验码[:：]\s*\d+"),
}

_NEGATIVE_FILENAME_PATTERN = re.compile(r"彩页|说明书|合同|保单|承诺函|参数偏离表|参数确认函")

DEFAULT_CLASSIFIER_THRESHOLD = 3
# 段级分类阈值更低：子报告文本只有几百字，命中 2 组即视为检测报告段
DEFAULT_SEGMENT_THRESHOLD = 2

# 8 组加权。权重依据：
# - G7 专用章、G1 标题、G2 编号、G6 机构名：独占性最强，是检测报告的"硬标识"
# - G4 检测词、G5 业务字段、G8 资质：辅助证据
# - G3 页码：最弱，合同/方案也有
_FEATURE_WEIGHTS: dict[str, float] = {
    "G1.标题": 2.0,
    "G2.编号": 2.0,
    "G3.页码": 1.0,
    "G4.检测词(≥2)": 1.5,
    "G5.业务字段(≥2)": 1.5,
    "G6.机构名": 2.0,
    "G7.专用章": 2.5,
    "G8.资质(≥1)": 1.5,
}
# 加权满分 = sum(_FEATURE_WEIGHTS.values())；confidence 归一化参考值取满分
_WEIGHT_TOTAL = sum(_FEATURE_WEIGHTS.values())


@dataclass
class ClassificationResult:
    is_detection_report: bool
    score: int  # 命中的特征组数（最大 8）
    hits: dict[str, bool]  # 每组是否命中
    weighted_score: float = 0.0  # 加权得分
    confidence: float = 0.0  # 归一化到 [0, 1]


def _group_score(markdown: str) -> tuple[int, dict[str, bool]]:
    """按 8 组聚合命中。G2/G4/G5/G8 内部任一子项命中即该组算 1；G4/G5 需要 ≥2 个子项。"""
    def hit(name: str) -> bool:
        return bool(_FEATURE_PATTERNS[name].search(markdown))

    def multi(prefix: str) -> int:
        return sum(1 for k in _FEATURE_PATTERNS if k.startswith(prefix) and _FEATURE_PATTERNS[k].search(markdown))

    groups = {
        "G1.标题": hit("G1.标题"),
        "G2.编号": multi("G2") >= 1,
        "G3.页码": hit("G3.页码"),
        "G4.检测词(≥2)": multi("G4") >= 2,
        "G5.业务字段(≥2)": multi("G5") >= 2,
        "G6.机构名": hit("G6.机构名"),
        "G7.专用章": hit("G7.专用章"),
        "G8.资质(≥1)": multi("G8") >= 1,
    }
    return sum(1 for v in groups.values() if v), groups


def _compute_weighted(hits: dict[str, bool]) -> tuple[float, float]:
    """返回 (加权得分, 归一化置信度 0-1)。"""
    weighted = sum(_FEATURE_WEIGHTS.get(g, 0.0) for g, v in hits.items() if v)
    confidence = min(1.0, weighted / _WEIGHT_TOTAL) if _WEIGHT_TOTAL else 0.0
    return weighted, confidence


def classify_detection_report(
    markdown: str,
    *,
    threshold: int = DEFAULT_CLASSIFIER_THRESHOLD,
) -> ClassificationResult:
    """命中 ≥ threshold 组判为检测报告。同时计算加权得分和置信度。"""
    score, hits = _group_score(markdown or "")
    weighted, confidence = _compute_weighted(hits)
    return ClassificationResult(
        is_detection_report=score >= threshold,
        score=score,
        hits=hits,
        weighted_score=round(weighted, 2),
        confidence=round(confidence, 3),
    )


def classify_segment(
    segment_text: str,
    *,
    threshold: int = DEFAULT_SEGMENT_THRESHOLD,
) -> ClassificationResult:
    """段级分类：对单份子报告文本使用更低阈值，允许部分特征缺失。

    子报告往往不含全局资质（G8）或专用章（G7，通常只在首页），
    因此不能用整篇的 threshold=3 要求它。
    """
    score, hits = _group_score(segment_text or "")
    weighted, confidence = _compute_weighted(hits)
    return ClassificationResult(
        is_detection_report=score >= threshold,
        score=score,
        hits=hits,
        weighted_score=round(weighted, 2),
        confidence=round(confidence, 3),
    )


def has_detection_report_filename(name: str) -> bool:
    """前置弱信号：文件名含"检验/检测报告"。命中即应强制启用 OCR。"""
    if not name:
        return False
    stem = Path(name).stem
    if _NEGATIVE_FILENAME_PATTERN.search(stem):
        return False
    return bool(re.search(r"检[验测](检测)?报告", stem))


# ---------------------------------------------------------------------------
# 2. 报告编号抽取 + 规范化（跨发证机构通用）
# ---------------------------------------------------------------------------

# 三类来源正则；后续如遇新形态只需扩充这里
_NO_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?m)^\s*No[\s.:]+([A-Za-z0-9()\-./]{4,40})"),
    re.compile(r"报告编号[.:：\s]+([A-Za-z0-9][A-Za-z0-9\-/().]{3,40})"),
    re.compile(r"委托编号[.:：\s]+([A-Za-z0-9][A-Za-z0-9\-/().]{3,40})"),
)


def _normalize_report_no(raw: str) -> str:
    """报告编号规范化：去空格、两端标点、换行。保留大小写区分。"""
    value = raw.strip()
    value = re.sub(r"\s+", "", value)
    value = value.rstrip(".,;:;：，。、/")
    value = value.rstrip("#")
    return value


def extract_report_numbers(markdown: str) -> list[tuple[str, int]]:
    """提取全文中所有报告编号（规范化后）及其首次出现位置。按出现顺序，去重。"""
    seen: dict[str, int] = {}
    for pattern in _NO_PATTERNS:
        for match in pattern.finditer(markdown):
            raw = match.group(1)
            normalized = _normalize_report_no(raw)
            if len(normalized) < 4:
                continue
            if normalized in seen:
                continue
            seen[normalized] = match.start()
    return sorted(seen.items(), key=lambda x: x[1])


# ---------------------------------------------------------------------------
# 3. 子报告切分
# ---------------------------------------------------------------------------

@dataclass
class SubReport:
    report_no: str
    start_offset: int
    end_offset: int
    text: str
    fields: dict[str, str] = field(default_factory=dict)
    classifier: ClassificationResult | None = None  # 段级分类结果


def split_subreports(markdown: str) -> list[SubReport]:
    """按规范化编号分组，以每个编号首次出现位置为子报告起点，切出各段正文。

    - 编号数 0：返回空列表（调用方应当回退为整篇当成单一文档处理）
    - 编号数 1：整篇作为一份子报告
    - 编号数 ≥2：按相邻起点切段
    """
    numbers = extract_report_numbers(markdown)
    if not numbers:
        return []
    subreports: list[SubReport] = []
    total = len(markdown)
    for i, (no, start) in enumerate(numbers):
        end = numbers[i + 1][1] if i + 1 < len(numbers) else total
        text = markdown[start:end]
        subreports.append(SubReport(report_no=no, start_offset=start, end_offset=end, text=text))
    return subreports


# ---------------------------------------------------------------------------
# 4. 字段抽取（表格优先 + 正则兜底 + 值校验）
# ---------------------------------------------------------------------------

_DATE_PATTERN = r"(\d{4})\s*[\-年./]\s*(\d{1,2})\s*[\-月./]\s*(\d{1,2})"

# 表格键 → 目标字段。键在表格单元格内需与"去掉英文部分"后的值精确相等。
# 多个键按优先级排序（list 顺序）。
_TABLE_KEY_MAP: dict[str, list[str]] = {
    "product_name": ["产品名称", "样品名称", "产品型号名称"],
    "model": ["型号规格", "规格型号", "产品型号", "型号"],
    "manufacturer": ["生产企业", "生产单位", "生产者", "制造单位", "制造商", "认证委托人", "委托单位", "受检单位"],
    "test_basis": ["检验依据", "检测依据"],
    "test_result": ["检验结论", "检测结论", "本项结论"],
    "report_date": ["签发日期", "报告日期", "生产日期"],
    "expire_date": ["有效期至"],
}

# 英文表头后缀（来自双语表格，如"产品名称 Product Name"）
_ENGLISH_SUFFIX_PATTERN = re.compile(r"[A-Za-z&/.\-()\s]+$")

# 非法/可疑值（大概率是表头或占位）
_INVALID_VALUE_PATTERNS = (
    re.compile(r"^[A-Za-z\s&/.()\-]+$"),  # 纯英文/符号
    re.compile(r"^[\-/空　空白]+$"),
    re.compile(r"^[-_=*. ]+$"),
)


def _normalize_date(raw: str) -> str:
    m = re.search(_DATE_PATTERN, raw)
    if not m:
        return raw.strip()
    y, mth, d = m.groups()
    return f"{int(y):04d}-{int(mth):02d}-{int(d):02d}"


def _strip_english_tail(cell: str) -> str:
    """双语表头常见形如"产品名称 Product Name"，抽取时只保留中文核心键。"""
    cleaned = _ENGLISH_SUFFIX_PATTERN.sub("", cell).strip()
    return cleaned or cell.strip()


def _is_valid_field_value(field: str, value: str) -> bool:
    """过滤表头/占位/纯英文。"""
    if not value:
        return False
    stripped = value.strip()
    if len(stripped) < 2:
        return False
    for pat in _INVALID_VALUE_PATTERNS:
        if pat.fullmatch(stripped):
            return False
    # 型号字段要求至少含 1 个数字或特定符号，避免抓到"型号"本身或"Model"
    if field == "model":
        if not re.search(r"[0-9]", stripped) and len(stripped) < 4:
            return False
        if stripped.lower() in {"model", "type", "model & type", "type specification", "serial no"}:
            return False
    return True


def _parse_pipe_tables(text: str) -> dict[str, str]:
    """解析 Markdown 管道表格，按键名吸出字段。同一字段按出现顺序第一个合法值为准。"""
    result: dict[str, str] = {}
    # 处理 `| a | b | c |` 单行（允许首列空）
    for match in re.finditer(r"(?m)^\|(.+)\|\s*$", text):
        raw = match.group(1)
        cells = [c.strip() for c in raw.split("|")]
        # 逐单元格检查是否为键，取下一单元格作为值
        for i, cell in enumerate(cells[:-1]):
            key_text = _strip_english_tail(cell)
            for field, keys in _TABLE_KEY_MAP.items():
                if field in result:
                    continue
                if key_text not in keys:
                    continue
                value = cells[i + 1].strip()
                # 当值本身也是键（同行多列 KV 齐列时会相邻），跳过
                if _strip_english_tail(value) in (k for kl in _TABLE_KEY_MAP.values() for k in kl):
                    continue
                if _is_valid_field_value(field, value):
                    result[field] = value
    return result


def _first_match(text: str, patterns: list[str], field: str = "") -> str:
    for pat in patterns:
        for m in re.finditer(pat, text):
            value = m.group(1).strip()
            if not field or _is_valid_field_value(field, value):
                return value
    return ""


def _clean_inline_value(value: str, *, max_len: int = 80) -> str:
    value = value.split("\n")[0]
    value = re.split(
        r"[ \t]{2,}|(?:\s(?:型号|产品型号|型号规格|规格型号|认证委托人|生产者|生产企业|生产单位|生产日期|检验类别|抽样者|抽样基数|抽样地点|样品数量|样品状态|受理日期|检验依据|检验项目|检验结论|备注|通讯地址|联系电话|商 ?标|商标)\s)",
        value,
        maxsplit=1,
    )[0]
    value = value.strip(" 　,.;:，。；：、|")
    if len(value) > max_len:
        value = value[: max_len - 1] + "…"
    return value


def extract_fields(subreport_text: str, *, fallback_no: str = "") -> dict[str, str]:
    """从子报告文本里抽 9 个字段。
    策略：先从 Markdown 管道表格抽（结构化，准确），再用正则在行内兜底。
    """
    text = subreport_text

    # 1) 报告编号
    report_no = fallback_no or ""
    if not report_no:
        for pat in _NO_PATTERNS:
            m = pat.search(text)
            if m:
                report_no = _normalize_report_no(m.group(1))
                break

    # 2) 先过表格
    table_hits = _parse_pipe_tables(text)

    # 3) 行内 / 段落级兜底
    product_name = table_hits.get("product_name") or _clean_inline_value(
        _first_match(text, [
            r"产品名称[\s　]*[:：]?[\s　]*([^\n，,；;。|]{2,40})",
            r"样品名称[\s　]*[:：]?[\s　]*([^\n，,；;。|]{2,40})",
            r"产品型号名称[\s　]*[:：]?[\s　]*([^\n，,；;。|]{2,40})",
        ], field="product_name")
    )

    model = table_hits.get("model") or _clean_inline_value(
        _first_match(text, [
            r"(?:型号规格|规格型号|产品型号(?!名称))[\s　]*[:：]?[\s　]*([A-Za-z0-9\-/.+·· ]{2,40})",
            r"(?<![a-zA-Z一-龥])型号[\s　]*[:：]?[\s　]*([A-Za-z0-9\-/.+·· ]{2,40})",
        ], field="model"),
        max_len=40,
    )

    manufacturer = table_hits.get("manufacturer") or _clean_inline_value(
        _first_match(text, [
            r"生产企业[\s　]*[:：]?[\s　]*([^\n，,；;。|]{2,60})",
            r"生产单位[\s　]*[:：]?[\s　]*([^\n，,；;。|]{2,60})",
            r"制造(?:单位|商)[\s　]*[:：]?[\s　]*([^\n，,；;。|]{2,60})",
            r"认证委托人[\s　]*[:：]?[\s　]*([^\n，,；;。|]{2,60})",
            r"委托单位[\s　]*[:：]?[\s　]*([^\n，,；;。|]{2,60})",
            r"生产者[\s　]*[:：]?[\s　]*([^\n，,；;。|]{2,60})",
        ], field="manufacturer")
    )

    test_organization = ""
    for match in re.finditer(
        r"(?m)^#+\s*([^\n#]*?(?:检验检测(?:中心|机构|公司|研究所|研究院)|质量监督检验(?:中心|机构)|计量检测(?:中心|公司|股份有限公司)|研究所|质检(?:中心|研究院))[^\n#]*)",
        text,
    ):
        candidate = match.group(1).strip()
        if 4 <= len(candidate) <= 60:
            test_organization = candidate
            break
    if not test_organization:
        test_organization = _clean_inline_value(_first_match(
            text,
            [r"(检测(?:单位|机构)[\s　]*[:：]?[\s　]*[^\n，,；;。|]{2,60})"],
        ))

    test_basis = table_hits.get("test_basis") or _clean_inline_value(
        _first_match(text, [r"检[验测]依据[\s　]*[:：]?[\s　]*([^\n|]{4,200})"]),
        max_len=200,
    )

    test_result = ""
    for pattern in [
        r"检[验测]结论[^。\n]{0,30}?(合格|不合格|通过|不通过)",
        r"(?<!不)结论[:：][^。\n]{0,10}?(合格|不合格|通过|不通过)",
        r"检[验测]结论[^。\n]{0,30}?(符合(?:要求|标准|.{0,6}要求)|不符合(?:要求|标准|.{0,6}要求))",
        r"检[验测]结果[^。\n]{0,30}?(合格|不合格|符合(?:要求|标准)|不符合(?:要求|标准))",
        r"本项结论[:：\s]+(合格|不合格)",
        # 兜底：没有显式"检验结论"前缀的完整句（常见于报告正文尾部）
        r"(所检项目均?符合(?:标准|.{0,10}要求))",
    ]:
        m = re.search(pattern, text)
        if m:
            test_result = m.group(1).strip()
            break
    test_result = _clean_inline_value(test_result or table_hits.get("test_result", ""), max_len=30)

    report_date = ""
    for pat in [
        rf"签发日期[\s　]*[:：]?[\s　]*{_DATE_PATTERN}",
        rf"报告日期[\s　]*[:：]?[\s　]*{_DATE_PATTERN}",
        rf"生产日期[\s　]*[:：]?[\s　]*{_DATE_PATTERN}",
    ]:
        m = re.search(pat, text)
        if m:
            report_date = _normalize_date(m.group(0))
            break

    expire_date = ""
    m = re.search(rf"有效期至[\s　]*[:：]?[\s　]*{_DATE_PATTERN}", text)
    if m:
        expire_date = _normalize_date(m.group(0))

    return {
        "report_no": report_no,
        "product_name": product_name,
        "model": model,
        "manufacturer": manufacturer,
        "test_organization": test_organization,
        "test_basis": test_basis,
        "test_result": test_result,
        "report_date": report_date,
        "expire_date": expire_date,
    }


# ---------------------------------------------------------------------------
# 5. 渲染（YAML frontmatter + 结构化正文，参考 22\225\01_报告Markdown\ 老脚本风格）
# ---------------------------------------------------------------------------

_FILENAME_SAFE_PATTERN = re.compile(r"[\\/:*?\"<>|\s]+")


def _sanitize_for_filename(value: str) -> str:
    cleaned = _FILENAME_SAFE_PATTERN.sub("_", (value or "").strip())
    return cleaned.strip("_") or "未命名"


def build_filename(fields: dict[str, str]) -> str:
    """`设备检验报告_<型号>_<编号>_<日期>.md`；缺的部分用占位符。"""
    model = _sanitize_for_filename(fields.get("model") or "未知型号")
    report_no = _sanitize_for_filename(fields.get("report_no") or "未知编号")
    date = _sanitize_for_filename(fields.get("report_date") or "未知日期")
    return f"设备检验报告_{model}_{report_no}_{date}.md"


def _yaml_line(key: str, value: str) -> str:
    """YAML 单行，value 简单加双引号，转义内部双引号。"""
    safe = (value or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'{key}: "{safe}"'


def render_subreport_md(
    sub: SubReport,
    source_meta: dict[str, str],
) -> tuple[str, str]:
    """渲染单份子报告 MD。返回 (filename, markdown_text)。"""
    f = sub.fields
    lines: list[str] = ["---"]
    lines.append(_yaml_line("document_type", "设备检验报告"))
    for key in (
        "manufacturer",
        "product_name",
        "model",
        "report_no",
        "test_organization",
        "test_basis",
        "test_result",
        "report_date",
        "expire_date",
    ):
        lines.append(_yaml_line(key, f.get(key, "")))
    lines.append(_yaml_line("source_file", source_meta.get("source_file", "")))
    lines.append(_yaml_line("source_path", source_meta.get("source_path", "")))
    lines.append(_yaml_line("extract_time", source_meta.get("extract_time", "")))
    if sub.classifier is not None:
        lines.append(f'classifier_score: {sub.classifier.score}')
        lines.append(f'classifier_weighted: {sub.classifier.weighted_score}')
        lines.append(f'classifier_confidence: {sub.classifier.confidence}')
    lines.append("---")
    lines.append("")
    lines.append("# 设备检测报告结构化信息")
    lines.append("")
    lines.append("## 基本信息")
    lines += [
        f"- 制造单位：{f.get('manufacturer','')}",
        f"- 产品名称：{f.get('product_name','')}",
        f"- 型号规格：{f.get('model','')}",
        f"- 报告编号：{f.get('report_no','')}",
    ]
    lines.append("")
    lines.append("## 检测信息")
    lines += [
        f"- 检验依据：{f.get('test_basis','')}",
        f"- 检验结果：**{f.get('test_result','')}**" if f.get("test_result") else "- 检验结果：",
        f"- 检测机构：{f.get('test_organization','')}",
        f"- 报告日期：{f.get('report_date','')}",
        f"- 有效期至：{f.get('expire_date','')}",
    ]
    lines.append("")
    lines.append("## 原文")
    lines.append("")
    lines.append(sub.text.strip())
    lines.append("")
    return build_filename(f), "\n".join(lines)


# ---------------------------------------------------------------------------
# 6. 顶层入口
# ---------------------------------------------------------------------------

def process(
    markdown: str,
    source_meta: dict[str, str],
) -> tuple[ClassificationResult, list[tuple[str, str]]]:
    """顶层入口。
    返回 (分类结果, [(filename, md_content), ...])。
    - 未命中分类：返回空列表，调用方走原有 profile 流程
    - 命中但无编号：返回整篇包一份兜底 SubReport
    - 命中且 ≥1 编号：每个子报告一个 MD
    """
    cls = classify_detection_report(markdown)
    if not cls.is_detection_report:
        return cls, []

    subs = split_subreports(markdown)
    if not subs:
        # 兜底：分类命中但没抽到编号，整篇作为单份（编号置空）
        subs = [SubReport(report_no="", start_offset=0, end_offset=len(markdown), text=markdown)]

    outputs: list[tuple[str, str]] = []
    for sub in subs:
        sub.fields = extract_fields(sub.text, fallback_no=sub.report_no)
        sub.classifier = classify_segment(sub.text)
        outputs.append(render_subreport_md(sub, source_meta))
    return cls, outputs


def build_classifier_json(
    overall: ClassificationResult,
    subs: list[SubReport],
    source_meta: dict[str, str],
) -> dict:
    """产出分类器明细，供上层写入 `_classifier.json`。

    结构：
      - overall: 整篇分类结果（score/weighted/confidence/hits）
      - segments: 每个子报告的段级分类 + 编号
    """
    return {
        "source_file": source_meta.get("source_file", ""),
        "source_path": source_meta.get("source_path", ""),
        "extract_time": source_meta.get("extract_time", ""),
        "overall": {
            "is_detection_report": overall.is_detection_report,
            "score": overall.score,
            "weighted_score": overall.weighted_score,
            "confidence": overall.confidence,
            "hits": overall.hits,
        },
        "segments": [
            {
                "report_no": sub.report_no,
                "score": sub.classifier.score if sub.classifier else 0,
                "weighted_score": sub.classifier.weighted_score if sub.classifier else 0.0,
                "confidence": sub.classifier.confidence if sub.classifier else 0.0,
                "hits": sub.classifier.hits if sub.classifier else {},
            }
            for sub in subs
        ],
    }


def process_with_details(
    markdown: str,
    source_meta: dict[str, str],
) -> tuple[ClassificationResult, list[tuple[str, str]], list[SubReport]]:
    """与 `process` 同，但额外返回 SubReport 列表（含段级分类），供上层写 JSON。"""
    cls = classify_detection_report(markdown)
    if not cls.is_detection_report:
        return cls, [], []

    subs = split_subreports(markdown)
    if not subs:
        subs = [SubReport(report_no="", start_offset=0, end_offset=len(markdown), text=markdown)]

    outputs: list[tuple[str, str]] = []
    for sub in subs:
        sub.fields = extract_fields(sub.text, fallback_no=sub.report_no)
        sub.classifier = classify_segment(sub.text)
        outputs.append(render_subreport_md(sub, source_meta))
    return cls, outputs, subs
