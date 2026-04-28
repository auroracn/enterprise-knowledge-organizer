from __future__ import annotations

import argparse
import re
from pathlib import Path


URL_PATTERN = re.compile(r"https?://[^\s)）]+")
FRONTMATTER_PATTERN = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
SECTION_HEADING_PATTERN = re.compile(r"^##\s+(.+)$")
TITLE_PATTERN = re.compile(r"^#\s+(.+)$")
LIST_ITEM_PATTERN = re.compile(r"^[-*]\s+(.*)$")
KEY_VALUE_PATTERN = re.compile(r"^[\-\*]?\s*([^：:]+)[：:]\s*(.+)$")


# 解析 frontmatter。当前样本只需覆盖简单 key: value 场景，避免引入额外依赖。
def parse_frontmatter(markdown_text: str) -> tuple[dict[str, str], str]:
    match = FRONTMATTER_PATTERN.match(markdown_text)
    if not match:
        return {}, markdown_text.strip()

    metadata: dict[str, str] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()

    return metadata, markdown_text[match.end() :].strip()


# 做最小清洗：去掉多余空白与空行，不改写原始事实表述。
def clean_text(text: str) -> str:
    text = text.replace("\ufeff", "").replace("\r", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# 按二级标题切分正文，保留标题下原始段落，便于后续按字段映射。
def parse_sections(body_text: str) -> tuple[str, dict[str, str]]:
    title = ""
    sections: dict[str, list[str]] = {}
    current_heading: str | None = None

    for raw_line in body_text.splitlines():
        line = raw_line.rstrip()
        stripped_line = line.strip()
        if not stripped_line:
            if current_heading:
                sections.setdefault(current_heading, []).append("")
            continue

        title_match = TITLE_PATTERN.match(stripped_line)
        if title_match:
            title = title_match.group(1).strip()
            continue

        heading_match = SECTION_HEADING_PATTERN.match(stripped_line)
        if heading_match:
            current_heading = heading_match.group(1).strip()
            sections.setdefault(current_heading, [])
            continue

        if current_heading:
            sections.setdefault(current_heading, []).append(stripped_line)

    return title, {heading: clean_text("\n".join(lines)) for heading, lines in sections.items()}


# 提取列表项；若原段不是列表，则按整段返回，保证弱结构样本也能落模板。
def extract_list_items(section_text: str) -> list[str]:
    items: list[str] = []
    for raw_line in section_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        item_match = LIST_ITEM_PATTERN.match(line)
        if item_match:
            items.append(item_match.group(1).strip())
        else:
            items.append(line)
    return items


# 提取“字段：内容”结构，便于主体、别名、联系线索等分栏。
def extract_key_values(section_text: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for item in extract_list_items(section_text):
        match = KEY_VALUE_PATTERN.match(item)
        if not match:
            continue
        key = match.group(1).strip()
        value = match.group(2).strip()
        pairs[key] = value
    return pairs


# 把顿号、逗号分隔值拆成列表，用于别名、电话、邮箱等多值字段。
def split_multi_values(raw_value: str) -> list[str]:
    normalized = raw_value.replace("；", "，").replace(";", "，")
    parts = [part.strip() for part in re.split(r"[、，,]", normalized) if part.strip()]
    return parts


# 汇总来源链接，既读取“来源链接”段，也从联系线索中补抓 URL。
def collect_links(sections: dict[str, str]) -> list[str]:
    links: list[str] = []
    for heading in ("官网与联系线索", "来源链接"):
        content = sections.get(heading, "")
        for match in URL_PATTERN.findall(content):
            if match not in links:
                links.append(match)
    return links


# 从文件名中拆出主体名与 hash 后缀；输出文件名不带 hash，但元数据保留。
def split_source_stem(source_path: Path) -> tuple[str, str]:
    stem = source_path.stem
    if "-" not in stem:
        return stem, ""
    subject_name, hash_suffix = stem.rsplit("-", 1)
    return subject_name.strip(), hash_suffix.strip()


# 生成适合 Dify 检索与人工优化的 frontmatter。
def build_metadata(source_path: Path, frontmatter: dict[str, str], title: str, sections: dict[str, str]) -> dict[str, str]:
    subject_from_name, hash_suffix = split_source_stem(source_path)
    subject_name = frontmatter.get("company_name") or title or subject_from_name
    links = collect_links(sections)

    return {
        "源文件名": source_path.name,
        "源文件位置": source_path.as_posix(),
        "文档分类": "竞争对手分析Markdown",
        "主体名称": subject_name,
        "entity_key": frontmatter.get("entity_key", ""),
        "文件名hash后缀": hash_suffix,
        "是否重点竞对": frontmatter.get("focus_competitor", "false"),
        "样本类型": frontmatter.get("sample_type", ""),
        "证据边界": "基于原始抓取 Markdown 整理；未补充外部核验，未核实内容仅保留为线索或待核验。",
        "来源链接": "；".join(links),
    }


# 将结构化结果渲染成清晰要点版 Markdown，突出用户要求的重点段落。
def build_clear_markdown(source_path: Path, markdown_text: str) -> str:
    frontmatter, body_text = parse_frontmatter(clean_text(markdown_text))
    title, sections = parse_sections(body_text)
    metadata = build_metadata(source_path, frontmatter, title, sections)

    subject_info = extract_key_values(sections.get("主体与别名", ""))
    contact_info = extract_key_values(sections.get("官网与联系线索", ""))
    business_info = extract_key_values(sections.get("经营范围匹配", ""))
    performance_items = extract_list_items(sections.get("公开业绩摘要", ""))
    six_dimension_items = extract_list_items(sections.get("六维判断", ""))
    risk_items = extract_list_items(sections.get("风险提示", ""))
    links = collect_links(sections)

    aliases = split_multi_values(subject_info.get("别名/账号线索", ""))
    phones = split_multi_values(contact_info.get("电话", ""))
    mails = split_multi_values(contact_info.get("邮箱", ""))

    pending_evidence: list[str] = []
    if risk_items:
        pending_evidence.extend(risk_items)
    if not performance_items:
        pending_evidence.append("公开业绩材料待补证。")
    if not links:
        pending_evidence.append("来源链接待补充。")

    lines: list[str] = ["---"]
    for key, value in metadata.items():
        lines.append(f"{key}: {value}")
    lines.extend([
        "---",
        "",
        f"# {metadata['主体名称']}-清晰要点版",
        "",
        "## 主体",
        f"- 主体名称：{metadata['主体名称']}",
        f"- 工商主体：{subject_info.get('工商主体', metadata['主体名称'])}",
        f"- 统一社会信用代码：{subject_info.get('统一社会信用代码', '待补充')}",
        f"- 重点竞对：{metadata['是否重点竞对']}",
        "",
        "## 别名",
    ])

    if aliases:
        lines.extend(f"- {item}" for item in aliases)
    else:
        lines.append("- 待补充")

    lines.extend([
        "",
        "## 联系线索",
        f"- 官网：{contact_info.get('官网', '待补充')}",
        f"- 联系页：{contact_info.get('联系页', '待补充')}",
        f"- 电话：{'、'.join(phones) if phones else '待补充'}",
        f"- 邮箱：{'、'.join(mails) if mails else '待补充'}",
        "",
        "## 业务匹配",
        f"- 分类：{business_info.get('分类', '待补充')}",
        f"- 一致点：{business_info.get('一致点', '待补充')}",
        f"- 冲突点：{business_info.get('冲突点', '待补充')}",
        "",
        "## 公开业绩",
    ])

    if performance_items:
        lines.extend(f"- {item}" for item in performance_items)
    else:
        lines.append("- 待补证")

    lines.extend([
        "",
        "## 六维判断",
    ])
    if six_dimension_items:
        lines.extend(f"- {item}" for item in six_dimension_items)
    else:
        lines.append("- 待补证")

    lines.extend([
        "",
        "## 风险提示",
    ])
    if risk_items:
        lines.extend(f"- {item}" for item in risk_items)
    else:
        lines.append("- 未提取到明确风险提示")

    lines.extend([
        "",
        "## 待补证据",
    ])
    for item in pending_evidence:
        lines.append(f"- {item}")

    lines.extend([
        "",
        "## 证据边界",
        f"- {metadata['证据边界']}",
        "",
        "## 来源链接",
    ])
    if links:
        lines.extend(f"- {link}" for link in links)
    else:
        lines.append("- 待补充")

    return "\n".join(lines).strip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将竞对分析 Markdown 标准化为适合 Dify 入库的清晰要点版。")
    parser.add_argument("--source", required=True, help="源 Markdown 文件绝对路径")
    parser.add_argument("--output", required=True, help="输出 Markdown 文件绝对路径")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_path = Path(args.source)
    output_path = Path(args.output)

    markdown_text = source_path.read_text(encoding="utf-8")
    output_content = build_clear_markdown(source_path, markdown_text)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output_content, encoding="utf-8")


if __name__ == "__main__":
    main()
