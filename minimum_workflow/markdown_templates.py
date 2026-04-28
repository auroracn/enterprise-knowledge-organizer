from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from minimum_workflow.contracts import SampleRecord
from minimum_workflow.field_extractors import normalize_policy_date


PAGE_HEADING_RE = re.compile(r"^#\s*第\d+页")


def normalize_multiline_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(item) for item in value if str(item).strip())
    return str(value)


def clean_page_excerpt_line(line: str) -> str:
    cleaned = re.sub(r"\s+", " ", line or "").strip()
    if not cleaned:
        return ""
    if PAGE_HEADING_RE.match(cleaned):
        return ""
    if cleaned in {"… …", "……", "...", "PART", "Company Introduction", "Core product", "Industry application"}:
        return ""
    if cleaned.startswith(("PART ", "# 第")):
        return ""
    if cleaned in {"A", "B", "J", "K", "M", "+", "++", "-->", "*排名不分顺序"}:
        return ""
    if re.fullmatch(r"[A-Za-z]{1,4}", cleaned):
        return ""
    return cleaned


def split_extracted_pages(text: str) -> list[tuple[str, list[str]]]:
    pages: list[tuple[str, list[str]]] = []
    current_heading = "全文"
    current_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if PAGE_HEADING_RE.match(line):
            if current_lines:
                pages.append((current_heading, current_lines))
            current_heading = line.lstrip("# ").strip()
            current_lines = []
            continue
        current_lines.append(raw_line)
    if current_lines:
        pages.append((current_heading, current_lines))
    return pages


def format_page_excerpt(page_heading: str, lines: list[str], *, max_lines: int = 10) -> str:
    cleaned_lines: list[str] = []
    seen: set[str] = set()
    for raw_line in lines:
        cleaned = clean_page_excerpt_line(raw_line)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        cleaned_lines.append(cleaned)
        if len(cleaned_lines) >= max_lines:
            break
    if not cleaned_lines:
        return ""
    bullet_lines = "\n".join(f"- {line}" for line in cleaned_lines)
    return f"### {page_heading}\n{bullet_lines}"


def build_page_excerpt_blocks(
    text: str,
    keywords: tuple[str, ...],
    *,
    max_pages: int = 4,
    max_lines_per_page: int = 10,
) -> str:
    if not text.strip():
        return ""
    blocks: list[str] = []
    for page_heading, page_lines in split_extracted_pages(text):
        page_text = "\n".join(page_lines)
        if not any(keyword in page_text for keyword in keywords):
            continue
        block = format_page_excerpt(page_heading, page_lines, max_lines=max_lines_per_page)
        if not block:
            continue
        blocks.append(block)
        if len(blocks) >= max_pages:
            break
    return "\n\n".join(blocks)


def build_solution_deep_sections(payload: dict[str, Any]) -> list[tuple[str, str]]:
    full_text = normalize_multiline_text(payload.get("提取正文"))
    return [
        (
            "## 十一、行业背景与痛点原文",
            build_page_excerpt_blocks(
                full_text,
                (
                    "行业背景",
                    "数字化转型",
                    "市场规模",
                    "趋势与挑战",
                    "企业巡检现状",
                    "安全痛点",
                    "目标群体",
                    "项目背景",
                    "方案背景",
                    "建设背景",
                    "巡检现状",
                    "痛点挑战",
                    "政策背景",
                    "现状与需求分析",
                    "需求分析",
                    "行业现状",
                    "应用背景",
                ),
            ),
        ),
        (
            "## 十二、方案架构与巡检流程原文",
            build_page_excerpt_blocks(
                full_text,
                (
                    "整体架构",
                    "巡检流程",
                    "巡检规划",
                    "巡检平台",
                    "巡检任务",
                    "巡检路线",
                    "报警规则",
                    "数据传输",
                    "技术方案",
                    "业务架构",
                    "系统架构",
                    "方案设计",
                    "总体方案",
                    "智能巡视方案设计",
                    "方案架构",
                    "侦察方案",
                    "灭火方案",
                    "通信保障方案",
                ),
            ),
        ),
        (
            "## 十三、产品资料与能力细节",
            build_page_excerpt_blocks(
                full_text,
                ("产品介绍", "核心产品", "产品发展线", "方案优势", "绝影", "X30", "M20", "IP67", "IP66", "激光雷达", "深度相机", "热插拔换电", "产品生态", "巡逻机器人", "机器狗总体介绍"),
                max_pages=5,
            ),
        ),
        (
            "## 十四、应用实例与落地线索",
            build_page_excerpt_blocks(
                full_text,
                ("应用实例", "应用案例", "项目案例", "案例介绍", "海外行业应用落地", "变电站巡检", "应急使命", "安防巡逻", "其他应用", "落地应用", "行业应用"),
                max_pages=5,
            ),
        ),
    ]


def build_supplier_deep_sections(payload: dict[str, Any]) -> list[tuple[str, str]]:
    full_text = normalize_multiline_text(payload.get("提取正文"))
    return [
        (
            "## 五、发展历程与关键节点",
            build_page_excerpt_blocks(
                full_text,
                ("发展历程", "公司成立", "专精特新", "小巨人", "Science Robotics", "国家高新技术企业"),
                max_pages=4,
            ),
        ),
        (
            "## 六、荣誉资质与标准线索",
            build_page_excerpt_blocks(
                full_text,
                ("荣誉资质", "标准制定", "国家级标准", "专利授权", "专利申请", "团体标准"),
                max_pages=4,
            ),
        ),
        (
            "## 七、创始人与团队线索",
            build_page_excerpt_blocks(
                full_text,
                ("创始人简介", "创始人&CEO", "联合创始人&CTO", "人才优势", "研发人员占比"),
                max_pages=4,
            ),
        ),
        (
            "## 八、分支机构与布局覆盖",
            build_page_excerpt_blocks(
                full_text,
                ("分支机构", "国内布局", "全球布局", "全球影响力", "客户与合作伙伴"),
                max_pages=4,
            ),
        ),
        (
            "## 九、产品生态与应用线索",
            build_page_excerpt_blocks(
                full_text,
                ("核心产品", "产品介绍", "产品生态", "行业应用", "应用案例", "绝影 X30", "山猫M20", "绝影 Lite3"),
                max_pages=5,
            ),
        ),
    ]


def build_education_training_deep_sections(payload: dict[str, Any]) -> list[tuple[str, str]]:
    full_text = normalize_multiline_text(payload.get("提取正文"))
    return [
        (
            "## 九、课程体系与合作模式原文",
            build_page_excerpt_blocks(
                full_text,
                ("产教融合", "课程体系", "教学", "实训", "科研", "竞赛", "合作目标", "合作定位", "联合实验室", "实验室介绍"),
                max_pages=5,
            ),
        ),
        (
            "## 十、配套产品资料",
            build_page_excerpt_blocks(
                full_text,
                ("配套产品介绍", "产品介绍", "核心产品", "绝影", "Lite", "Lite3", "实训台", "产品发展线"),
                max_pages=4,
            ),
        ),
        (
            "## 十一、应用实例与案例线索",
            build_page_excerpt_blocks(
                full_text,
                ("应用实例", "案例介绍", "合作案例", "校园巡检", "教育科研", "电力巡检", "应急消防", "安防巡逻", "其他应用"),
                max_pages=5,
            ),
        ),
    ]


def append_rich_markdown_section(lines: list[str], heading: str, content: str) -> None:
    lines.extend([
        heading,
        content.strip() if content.strip() else "- 未提取",
        "",
    ])


def append_full_text_section(lines: list[str], payload: dict[str, Any]) -> None:
    full_text = normalize_multiline_text(payload.get("提取正文")).strip()
    if not full_text:
        lines.extend([
            "## 原文全文",
            "未提取",
            "",
        ])
        return
    filtered = "\n".join(
        line for line in full_text.splitlines()
        if not re.match(r"^\s*https?://localhost\S*\s*$", line)
    ).strip()
    lines.extend([
        "## 原文全文",
        filtered or "未提取",
        "",
    ])


def build_policy_sections(payload: dict[str, Any]) -> dict[str, str]:
    text = payload.get("文本预览", "") or ""
    core_tasks = payload.get("核心任务", []) or []
    core_task_text = "；".join(core_tasks) if core_tasks else "待根据正文补充。"
    title = payload.get("文件标题") or payload.get("标题") or "未命名政策文件"
    document_number = payload.get("发文字号") or "未提取"
    issuing_unit = payload.get("发文单位") or payload.get("单位名称") or "未提取"
    issue_date = payload.get("成文日期") or "未提取"
    effective_status = payload.get("生效状态") or "未注明"
    if not text:
        return {
            "文件摘要": f"{title}，当前尚未提取到可用正文。",
            "核心要求": core_task_text,
            "业务相关": "待根据正文补充。",
            "执行意义": "待根据正文补充。",
            "时效边界": f"生效状态：{effective_status}。待结合正式来源进一步确认。",
        }
    return {
        "文件摘要": f"文件标题：{title}；发文字号：{document_number}；发文单位：{issuing_unit}；成文日期：{issue_date}。",
        "核心要求": core_task_text,
        "业务相关": "当前为政策类首轮样例，后续需结合长风业务场景补条目映射。",
        "执行意义": "当前文本已进入结构化最小闭环，可作为后续规则判断、模板填充和政策任务拆条输入。",
        "时效边界": f"生效状态：{effective_status}。若为整理稿或转载稿，正式落库前仍需回核正式来源与有效状态。",
    }


def build_generic_sections(payload: dict[str, Any]) -> dict[str, str]:
    preview_text = payload.get("文本预览", "") or ""
    return {
        "资料摘要": preview_text or "当前尚未提取到可用正文。",
        "抽取说明": payload.get("抽取说明", ""),
        "归档建议": payload.get("分流结果", "待审核"),
    }


SUPPLIER_EMPTY_VALUES = {"", "未提取", "未注明", "未识别"}
PRODUCT_EMPTY_VALUES = SUPPLIER_EMPTY_VALUES
EDUCATION_EMPTY_VALUES = SUPPLIER_EMPTY_VALUES


def format_supplier_optional_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        cleaned_items = [str(item).strip() for item in value if str(item).strip() and str(item).strip() not in SUPPLIER_EMPTY_VALUES]
        return "；".join(cleaned_items)
    cleaned = str(value).strip()
    if cleaned in SUPPLIER_EMPTY_VALUES:
        return ""
    return cleaned


def format_product_optional_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        cleaned_items = [str(item).strip() for item in value if str(item).strip() and str(item).strip() not in PRODUCT_EMPTY_VALUES]
        return "；".join(cleaned_items)
    cleaned = str(value).strip()
    if cleaned in PRODUCT_EMPTY_VALUES:
        return ""
    return cleaned


def format_education_optional_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        cleaned_items = [str(item).strip() for item in value if str(item).strip() and str(item).strip() not in EDUCATION_EMPTY_VALUES]
        return "；".join(cleaned_items)
    cleaned = str(value).strip()
    if cleaned in EDUCATION_EMPTY_VALUES:
        return ""
    return cleaned


def looks_like_supplier_list_preview(text: str) -> bool:
    if len(text) < 80:
        return False
    company_markers = ("有限公司", "股份有限公司", "科技有限公司", "企业：")
    return sum(text.count(marker) for marker in company_markers) >= 3


def build_supplier_sections(payload: dict[str, Any]) -> dict[str, str]:
    company_name = format_supplier_optional_value(payload.get("企业名称", payload.get("主体名称", "")) or payload.get("主体名称", ""))
    company_type = format_supplier_optional_value(payload.get("企业类别"))
    business_direction = format_supplier_optional_value(payload.get("主营方向"))
    core_products = format_supplier_optional_value(payload.get("核心产品"))
    core_capabilities = format_supplier_optional_value(payload.get("核心能力"))

    summary_parts: list[str] = []
    if company_name:
        summary_parts.append(company_name)
    if company_type:
        summary_parts.append(f"企业类别：{company_type}")
    if business_direction:
        summary_parts.append(f"主营方向：{business_direction}")
    if core_products:
        summary_parts.append(f"核心产品：{core_products}")
    if core_capabilities:
        summary_parts.append(f"核心能力：{core_capabilities}")

    preview_text = format_supplier_optional_value(payload.get("文本预览"))
    if summary_parts:
        company_summary = "；".join(summary_parts)
    elif preview_text and not looks_like_supplier_list_preview(preview_text):
        company_summary = preview_text
    else:
        company_summary = ""

    return {
        "企业摘要": company_summary,
        "主营方向": business_direction,
        "核心产品": core_products,
        "核心能力": core_capabilities,
        "企业类别": company_type,
        "企业名称": company_name,
    }


def build_contact_sections(payload: dict[str, Any]) -> dict[str, str]:
    unit_name = payload.get("单位名称字段", payload.get("单位名称", "")) or payload.get("单位名称", "")
    unit_type = payload.get("单位类型字段", "未注明") or "未注明"
    contact_name = payload.get("联系人姓名", "未提取") or "未提取"
    contact_role = payload.get("联系人角色字段", "未提取") or "未提取"
    contact_info = payload.get("联系方式字段", "未提取") or "未提取"
    contact_clues = payload.get("对接线索字段", "未提取") or "未提取"

    summary_parts: list[str] = []
    if unit_name:
        summary_parts.append(unit_name)
    if unit_type != "未注明":
        summary_parts.append(f"单位类型：{unit_type}")
    if contact_clues != "未提取":
        summary_parts.append(f"对接线索：{contact_clues}")
    unit_summary = "；".join(summary_parts) if summary_parts else payload.get("文本预览", "") or "当前尚未提取到可用正文。"

    return {
        "单位名称": unit_name,
        "单位类型": unit_type,
        "联系人姓名": contact_name,
        "联系人角色": contact_role,
        "联系方式": contact_info,
        "对接线索": contact_clues,
        "单位摘要": unit_summary,
    }


def build_solution_sections(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "资料摘要": payload.get("文本预览", "") or "当前尚未提取到可用正文。",
        "应用背景": payload.get("所属场景字段", "未提取") or "未提取",
        "解决问题": payload.get("解决问题字段", "未提取") or "未提取",
        "资料形态": payload.get("证据类型字段", "未提取") or "未提取",
        "产品能力": payload.get("产品能力字段", "未提取") or "未提取",
        "实施方式": payload.get("实施方式字段", "未提取") or "未提取",
        "预算组织": payload.get("预算组织字段", "未提取") or "未提取",
        "效果数据": payload.get("效果数据字段", "未提取") or "未提取",
        "可复用经验": payload.get("可复用经验字段", "未提取") or "未提取",
    }


def build_product_sections(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "资料摘要": payload.get("文本预览", "") or "当前尚未提取到可用正文。",
        "核心用途": format_product_optional_value(payload.get("核心用途字段")),
        "资料形态": format_product_optional_value(payload.get("产品证据类型字段")),
        "核心参数": format_product_optional_value(payload.get("核心参数字段")),
        "适用场景": format_product_optional_value(payload.get("适用场景字段")),
        "搭配关系": format_product_optional_value(payload.get("搭配关系字段")),
    }


def build_education_training_sections(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "资料摘要": payload.get("文本预览", "") or "当前尚未提取到可用正文。",
        "培训主题": format_education_optional_value(payload.get("培训主题字段")),
        "适用对象": format_education_optional_value(payload.get("适用对象字段")),
        "培训类型": format_education_optional_value(payload.get("培训类型字段")),
        "专业方向": format_education_optional_value(payload.get("专业方向字段")),
        "课程体系": format_education_optional_value(payload.get("课程体系字段")),
        "实施方式": format_education_optional_value(payload.get("实施方式字段")),
        "核心内容": format_education_optional_value(payload.get("核心内容字段")),
    }


def build_procurement_sections(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "资料摘要": payload.get("文本预览", "") or "当前尚未提取到可用正文。",
        "采购方式": payload.get("采购方式字段", "未提取") or "未提取",
        "预算限价": payload.get("预算最高限价字段", "未提取") or "未提取",
        "评分办法": payload.get("评分办法字段", "未提取") or "未提取",
        "采购需求": payload.get("采购需求摘要字段", "未提取") or "未提取",
    }


def build_contract_sections(payload: dict[str, Any]) -> dict[str, str]:
    items = payload.get("产品型号价格字段") or []
    items_text = ""
    if isinstance(items, list) and items:
        parts = []
        for item in items:
            if isinstance(item, dict):
                parts.append("；".join(f"{k}：{v}" for k, v in item.items() if v))
            else:
                parts.append(str(item))
        items_text = "\n".join(parts) if parts else "未提取"
    return {
        "资料摘要": payload.get("文本预览", "") or "当前尚未提取到可用正文。",
        "合同名称": payload.get("合同名称字段", "未提取") or "未提取",
        "合同编号": payload.get("合同编号字段", "未提取") or "未提取",
        "合同类型": payload.get("合同类型字段", "未提取") or "未提取",
        "甲方": payload.get("甲方字段", "未提取") or "未提取",
        "乙方": payload.get("乙方字段", "未提取") or "未提取",
        "合同金额": payload.get("合同金额字段", "未提取") or "未提取",
        "合同期限": payload.get("合同期限字段", "未提取") or "未提取",
        "签订日期": payload.get("签订日期字段", "未提取") or "未提取",
        "合同标的": payload.get("合同标的字段", "未提取") or "未提取",
        "履约状态": payload.get("履约状态字段", "未提取") or "未提取",
    }


def build_price_quote_sections(payload: dict[str, Any]) -> dict[str, str]:
    items = payload.get("产品型号价格字段") or []
    items_text = "未提取"
    if isinstance(items, list) and items:
        parts = []
        for item in items:
            if isinstance(item, dict):
                parts.append("；".join(f"{k}：{v}" for k, v in item.items() if v))
            else:
                parts.append(str(item))
        items_text = "\n".join(parts) if parts else "未提取"
    return {
        "资料摘要": payload.get("文本预览", "") or "当前尚未提取到可用正文。",
        "报价单名称": payload.get("报价单名称字段", "未提取") or "未提取",
        "报价主体": payload.get("报价主体字段", "未提取") or "未提取",
        "产品型号价格": items_text,
        "有效期": payload.get("有效期字段", "未提取") or "未提取",
        "报价日期": payload.get("报价日期字段", "未提取") or "未提取",
        "价格类型": payload.get("价格类型字段", "未提取") or "未提取",
    }


INDUSTRY_KNOWLEDGE_EMPTY_VALUES = SUPPLIER_EMPTY_VALUES


def format_industry_knowledge_optional_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        cleaned_items = [str(item).strip() for item in value if str(item).strip() and str(item).strip() not in INDUSTRY_KNOWLEDGE_EMPTY_VALUES]
        return "；".join(cleaned_items)
    cleaned = str(value).strip()
    if cleaned in INDUSTRY_KNOWLEDGE_EMPTY_VALUES:
        return ""
    return cleaned


def build_industry_knowledge_sections(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "资料摘要": payload.get("文本预览", "") or "当前尚未提取到可用正文。",
        "行业领域": format_industry_knowledge_optional_value(payload.get("行业领域字段")),
        "产业链环节": format_industry_knowledge_optional_value(payload.get("产业链环节字段")),
        "市场规模": format_industry_knowledge_optional_value(payload.get("市场规模字段")),
        "核心玩家": format_industry_knowledge_optional_value(payload.get("核心玩家字段")),
        "发展趋势": format_industry_knowledge_optional_value(payload.get("发展趋势字段")),
    }


def build_industry_knowledge_deep_sections(payload: dict[str, Any]) -> list[tuple[str, str]]:
    full_text = normalize_multiline_text(payload.get("提取正文"))
    return [
        (
            "## 七、产业链结构原文",
            build_page_excerpt_blocks(
                full_text,
                (
                    "产业链", "上游", "中游", "下游", "全产业链", "价值链",
                    "供应链", "产业结构", "产业图谱", "产业生态",
                ),
                max_pages=5,
            ),
        ),
        (
            "## 八、市场规模与竞争格局原文",
            build_page_excerpt_blocks(
                full_text,
                (
                    "市场规模", "竞争格局", "市场份额", "行业格局",
                    "细分市场", "赛道", "产业集群", "行业壁垒",
                ),
                max_pages=5,
            ),
        ),
        (
            "## 九、发展趋势与政策驱动原文",
            build_page_excerpt_blocks(
                full_text,
                (
                    "发展趋势", "行业趋势", "未来趋势", "政策驱动",
                    "产业政策", "行业驱动力", "增长预测", "投资方向",
                ),
                max_pages=4,
            ),
        ),
    ]


FIELD_DISPLAY_LABELS = {
    "文件日期字段": "文件日期",
    "招投标记录数": "招投标记录数",
    "招投标发布日期范围": "招投标发布日期范围",
    "招投标采购单位数": "招投标采购单位数",
    "招投标预算样本数": "招投标预算样本数",
    "招投标表格Markdown": "招投标结构化表格",
    "单位名称字段": "单位名称",
    "单位类型字段": "单位类型",
    "联系人角色字段": "联系人角色",
    "联系方式字段": "联系方式",
    "对接线索字段": "对接线索",
    "方案名称字段": "方案名称",
    "所属场景字段": "所属场景",
    "客户名称字段": "客户/使用单位",
    "解决问题字段": "解决的问题",
    "产品能力字段": "投入的产品/设备/能力",
    "实施方式字段": "实施方式",
    "预算组织字段": "预算、进度与组织方式",
    "效果数据字段": "结果与效果数据",
    "可复用经验字段": "可复用经验",
    "证据类型字段": "证据类型",
    "培训主题字段": "培训主题",
    "适用对象字段": "适用对象",
    "培训类型字段": "培训类型",
    "专业方向字段": "专业方向",
    "课程体系字段": "课程体系",
    "核心内容字段": "核心内容",
    "项目编号字段": "项目编号",
    "采购人字段": "采购人",
    "采购代理机构字段": "采购代理机构",
    "采购方式字段": "采购方式",
    "预算最高限价字段": "预算/最高限价",
    "评分办法字段": "评分办法",
    "采购需求摘要字段": "采购需求摘要",
    "产品名称字段": "产品名称",
    "型号字段": "型号",
    "供应商名称字段": "供应商名称",
    "产品类别字段": "产品类别",
    "核心用途字段": "核心用途",
    "核心参数字段": "核心参数",
    "适用场景字段": "适用场景",
    "搭配关系字段": "搭配关系",
    "产品证据类型字段": "产品证据类型",
    "报告文档类型字段": "报告文档类型",
    "产品编号字段": "产品编号",
    "检定依据字段": "检定依据",
    "检定结果字段": "检定结果",
    "检测机构字段": "检测机构",
    "报告编号字段": "报告编号",
    "报告日期字段": "报告日期",
    "有效期至字段": "有效期至",
    "合同名称字段": "合同名称",
    "合同编号字段": "合同编号",
    "合同类型字段": "合同类型",
    "甲方字段": "甲方",
    "乙方字段": "乙方",
    "合同金额字段": "合同金额",
    "合同期限字段": "合同期限",
    "签订日期字段": "签订日期",
    "合同标的字段": "合同标的",
    "履约状态字段": "履约状态",
    "报价单名称字段": "报价单名称",
    "报价主体字段": "报价主体",
    "产品型号价格字段": "产品型号价格",
    "有效期字段": "有效期",
    "报价日期字段": "报价日期",
    "价格类型字段": "价格类型",
    "行业领域字段": "行业领域",
    "产业链环节字段": "产业链环节",
    "市场规模字段": "市场规模",
    "核心玩家字段": "核心玩家",
    "发展趋势字段": "发展趋势",
}

TEMPLATE_PRIMARY_FIELDS = {
    "政策官方文件模板": {"文件标题", "发文字号", "发文单位", "成文日期", "核心任务", "生效状态"},
    "供应商企业模板": {"企业名称", "企业类别", "主营方向", "核心产品", "核心能力"},
    "单位联系人模板": {"单位名称字段", "单位类型字段", "联系人姓名", "联系人角色字段", "联系方式字段", "对接线索字段"},
    "方案案例模板": {"方案名称字段", "所属场景字段", "客户名称字段", "文件日期字段", "解决问题字段", "产品能力字段", "实施方式字段", "预算组织字段", "效果数据字段", "可复用经验字段", "证据类型字段"},
    "教育培训模板": {"文件标题", "单位名称字段", "培训主题字段", "适用对象字段", "培训类型字段", "专业方向字段", "课程体系字段", "实施方式字段", "核心内容字段"},
    "招标采购文件模板": {"文件标题", "项目编号字段", "采购人字段", "采购代理机构字段", "采购方式字段", "文件日期字段", "预算最高限价字段", "评分办法字段", "采购需求摘要字段"},
    "产品设备模板": {"产品名称字段", "型号字段", "供应商名称字段", "产品类别字段", "核心用途字段", "核心参数字段", "适用场景字段", "搭配关系字段", "产品证据类型字段", "报告文档类型字段", "产品编号字段", "检定依据字段", "检定结果字段", "检测机构字段", "报告编号字段", "报告日期字段", "有效期至字段"},
    "合同商务模板": {"合同名称字段", "合同编号字段", "合同类型字段", "甲方字段", "乙方字段", "合同金额字段", "合同期限字段", "签订日期字段", "合同标的字段", "履约状态字段"},
    "报价清单模板": {"报价单名称字段", "报价主体字段", "产品型号价格字段", "有效期字段", "报价日期字段", "价格类型字段"},
    "行业知识模板": {"文件标题", "行业领域字段", "产业链环节字段", "市场规模字段", "核心玩家字段", "发展趋势字段"},
}

SUPPLEMENTAL_FIELD_ORDER = [
    "文件标题",
    "发文字号",
    "发文单位",
    "成文日期",
    "文件日期字段",
    "招投标记录数",
    "招投标发布日期范围",
    "招投标采购单位数",
    "招投标预算样本数",
    "招投标表格Markdown",
    "核心任务",
    "生效状态",
    "企业名称",
    "企业类别",
    "主营方向",
    "核心产品",
    "核心能力",
    "单位名称字段",
    "单位类型字段",
    "联系人姓名",
    "联系人角色字段",
    "联系方式字段",
    "对接线索字段",
    "方案名称字段",
    "所属场景字段",
    "客户名称字段",
    "解决问题字段",
    "产品能力字段",
    "实施方式字段",
    "预算组织字段",
    "效果数据字段",
    "可复用经验字段",
    "证据类型字段",
    "培训主题字段",
    "适用对象字段",
    "培训类型字段",
    "专业方向字段",
    "课程体系字段",
    "核心内容字段",
    "项目编号字段",
    "采购人字段",
    "采购代理机构字段",
    "采购方式字段",
    "预算最高限价字段",
    "评分办法字段",
    "采购需求摘要字段",
    "产品名称字段",
    "型号字段",
    "供应商名称字段",
    "产品类别字段",
    "核心用途字段",
    "核心参数字段",
    "适用场景字段",
    "搭配关系字段",
    "产品证据类型字段",
    "报告文档类型字段",
    "产品编号字段",
    "检定依据字段",
    "检定结果字段",
    "检测机构字段",
    "报告编号字段",
    "报告日期字段",
    "有效期至字段",
    "合同名称字段",
    "合同编号字段",
    "合同类型字段",
    "甲方字段",
    "乙方字段",
    "合同金额字段",
    "合同期限字段",
    "签订日期字段",
    "合同标的字段",
    "履约状态字段",
    "报价单名称字段",
    "报价主体字段",
    "产品型号价格字段",
    "有效期字段",
    "报价日期字段",
    "价格类型字段",
    "行业领域字段",
    "产业链环节字段",
    "市场规模字段",
    "核心玩家字段",
    "发展趋势字段",
    "模板归属",
    "资料层级",
    "发布时间",
    "证据边界",
    "来源形态",
    "目录判定",
    "判定依据",
    "OCR页数",
    "OCR结果概况",
    "OCR失败页",
    "取舍说明",
]


def is_empty_payload_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, list):
        return len(value) == 0
    return False


def format_markdown_value(value: Any, default: str = "未提取") -> str:
    if is_empty_payload_value(value):
        return default
    if isinstance(value, list):
        return "；".join(str(item) for item in value if str(item).strip()) or default
    return str(value)


# 当前模板未主展示的非空字段继续走补充区，保持现有输出口径不变。
def build_supplemental_field_lines(template_name: str, payload: dict[str, Any]) -> list[str]:
    primary_fields = TEMPLATE_PRIMARY_FIELDS.get(template_name, set())
    lines: list[str] = []
    for key in SUPPLEMENTAL_FIELD_ORDER:
        if key in primary_fields:
            continue
        value = payload.get(key)
        if is_empty_payload_value(value):
            continue
        label = FIELD_DISPLAY_LABELS.get(key, key)
        if isinstance(value, str) and "\n" in value:
            lines.extend([
                f"### {label}",
                "",
                value.strip(),
                "",
            ])
            continue
        lines.append(f"- {label}：{format_markdown_value(value)}")
    return lines


FRONTMATTER_PATTERN = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
MARKDOWN_TEMPLATE_CATEGORY_MAP = {
    "政策官方文件模板": "policy",
    "方案案例模板": "solution",
    "产品设备模板": "certificate",
    "供应商企业模板": "intro",
    "教育培训模板": "education_training",
    "招标采购文件模板": "procurement",
    "合同商务模板": "contract",
    "报价清单模板": "price_quote",
    "招投标汇总模板": "procurement_summary",
    "参考架构/白皮书口径（当前按原文全量提取Markdown输出）": "reference",
    "行业知识模板": "industry_knowledge",
    "待人工补规则": "unknown",
}


def parse_markdown_frontmatter(markdown_text: str) -> tuple[dict[str, str], str]:
    cleaned_text = (markdown_text or "").replace("﻿", "").replace("\r", "")
    match = FRONTMATTER_PATTERN.match(cleaned_text)
    if not match:
        return {}, cleaned_text.strip()

    metadata: dict[str, str] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata, cleaned_text[match.end() :].strip()


def normalize_frontmatter_value(value: Any) -> str:
    if is_empty_payload_value(value):
        return ""
    if isinstance(value, bool):
        text = "是" if value else "否"
    elif isinstance(value, list):
        text = "；".join(str(item).strip() for item in value if str(item).strip())
    else:
        text = str(value)
    return re.sub(r"\s+", " ", text.replace("\r", " ").replace("\n", " ")).strip()


def first_non_empty_frontmatter_value(*values: Any) -> str:
    for value in values:
        normalized = normalize_frontmatter_value(value)
        if normalized:
            return normalized
    return ""


def infer_markdown_category(payload: dict[str, Any]) -> str:
    template_name = str(payload.get("推荐模板") or "")
    if template_name in MARKDOWN_TEMPLATE_CATEGORY_MAP:
        return MARKDOWN_TEMPLATE_CATEGORY_MAP[template_name]
    if "参考架构" in template_name:
        return "reference"
    return "unknown"


def infer_markdown_relative_path(sample: SampleRecord, payload: dict[str, Any]) -> str:
    hinted_path = first_non_empty_frontmatter_value(sample.relative_path_hint)
    if hinted_path:
        return hinted_path
    source_path = Path(str(payload.get("原始路径") or ""))
    return source_path.name


def infer_normalized_date_from_text(text: str, patterns: tuple[str, ...]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        normalized = normalize_policy_date(match.group(1))
        if normalized:
            return normalized
    return ""


def build_markdown_metadata_entries(
    sample: SampleRecord,
    payload: dict[str, Any],
    existing_metadata: dict[str, str],
    body_text: str,
) -> list[tuple[str, str]]:
    entries = [
        ("源文件名", first_non_empty_frontmatter_value(payload.get("原始文件名"))),
        ("源文件相对路径", infer_markdown_relative_path(sample, payload)),
        ("文档类别", infer_markdown_category(payload)),
        ("文档分类", first_non_empty_frontmatter_value(payload.get("文档分类"))),
        ("推荐模板", first_non_empty_frontmatter_value(payload.get("推荐模板"))),
        ("知识库分类", first_non_empty_frontmatter_value(payload.get("知识库分类"))),
        ("分类来源", first_non_empty_frontmatter_value(payload.get("分类来源"))),
        ("人工审核状态", first_non_empty_frontmatter_value(payload.get("人工审核状态"))),
        ("提取时间戳", first_non_empty_frontmatter_value(payload.get("生成时间"))),
    ]
    template_name = str(payload.get("推荐模板") or "")

    if template_name == "政策官方文件模板":
        entries.extend(
            [
                ("发布单位", first_non_empty_frontmatter_value(existing_metadata.get("发布单位"), existing_metadata.get("发文单位"), payload.get("发文单位"), payload.get("主体名称"), payload.get("单位名称"))),
                ("文号", first_non_empty_frontmatter_value(existing_metadata.get("文号"), existing_metadata.get("发文字号"), payload.get("发文字号"))),
                ("发布日期", first_non_empty_frontmatter_value(existing_metadata.get("发布日期"), existing_metadata.get("成文日期"), payload.get("成文日期"), payload.get("发布时间"))),
                (
                    "生效日期",
                    first_non_empty_frontmatter_value(
                        existing_metadata.get("生效日期"),
                        infer_normalized_date_from_text(
                            body_text,
                            (
                                r"生效日期[:：]\s*([^\n]+)",
                                r"自\s*(20\d{2}年\d{1,2}月\d{1,2}日)\s*起施行",
                            ),
                        ),
                    ),
                ),
            ]
        )
    elif template_name == "方案案例模板":
        entries.extend(
            [
                ("项目名称", first_non_empty_frontmatter_value(existing_metadata.get("项目名称"), payload.get("方案名称字段"), payload.get("文件标题"), payload.get("标题"))),
                ("客户/牵头单位", first_non_empty_frontmatter_value(existing_metadata.get("客户/牵头单位"), existing_metadata.get("客户名称"), payload.get("客户名称字段"))),
                ("编制单位", first_non_empty_frontmatter_value(existing_metadata.get("编制单位"), existing_metadata.get("牵头单位"), payload.get("主体名称"), payload.get("单位名称"))),
                ("编制日期", first_non_empty_frontmatter_value(existing_metadata.get("编制日期"), payload.get("文件日期字段"), payload.get("发布时间"))),
            ]
        )
    elif template_name == "产品设备模板":
        entries.extend(
            [
                ("产品名称", first_non_empty_frontmatter_value(existing_metadata.get("产品名称"), payload.get("产品名称字段"), payload.get("产品名称"), payload.get("文件标题"))),
                ("标准编号", first_non_empty_frontmatter_value(existing_metadata.get("标准编号"), payload.get("检定依据字段"))),
                ("颁发机构", first_non_empty_frontmatter_value(existing_metadata.get("颁发机构"), payload.get("检测机构字段"), payload.get("供应商名称字段"))),
                ("有效期", first_non_empty_frontmatter_value(existing_metadata.get("有效期"), payload.get("有效期至字段"), payload.get("有效期字段"))),
            ]
        )
    elif template_name == "供应商企业模板":
        entries.extend(
            [
                ("公司名称", first_non_empty_frontmatter_value(existing_metadata.get("公司名称"), payload.get("企业名称"), payload.get("主体名称"), payload.get("单位名称"))),
                ("主营业务", first_non_empty_frontmatter_value(existing_metadata.get("主营业务"), payload.get("主营方向"), payload.get("核心能力"))),
                (
                    "成立时间",
                    first_non_empty_frontmatter_value(
                        existing_metadata.get("成立时间"),
                        infer_normalized_date_from_text(
                            body_text,
                            (
                                r"成立(?:于|时间|日期)?[:：]?\s*(20\d{2}年\d{1,2}月(?:\d{1,2}日)?)",
                                r"创立(?:于|时间|日期)?[:：]?\s*(20\d{2}年\d{1,2}月(?:\d{1,2}日)?)",
                                r"创办(?:于|时间|日期)?[:：]?\s*(20\d{2}年\d{1,2}月(?:\d{1,2}日)?)",
                            ),
                        ),
                    ),
                ),
            ]
        )
    elif template_name == "行业知识模板":
        entries.extend(
            [
                ("行业领域", first_non_empty_frontmatter_value(existing_metadata.get("行业领域"), payload.get("行业领域字段"))),
                ("产业链环节", first_non_empty_frontmatter_value(existing_metadata.get("产业链环节"), payload.get("产业链环节字段"))),
                ("市场规模", first_non_empty_frontmatter_value(existing_metadata.get("市场规模"), payload.get("市场规模字段"))),
            ]
        )
    return entries


def build_preserved_markdown(sample: SampleRecord, payload: dict[str, Any]) -> str:
    existing_metadata_raw = payload.get("原始Markdown元数据") or {}
    existing_metadata = existing_metadata_raw if isinstance(existing_metadata_raw, dict) else {}
    body_text = str(payload.get("提取正文") or "").strip()
    metadata_entries = build_markdown_metadata_entries(sample, payload, existing_metadata, body_text)

    lines = ["---"]
    emitted_keys: set[str] = set()
    for key, value in metadata_entries:
        if key in emitted_keys:
            continue
        resolved_value = first_non_empty_frontmatter_value(existing_metadata.get(key), value)
        if not resolved_value:
            continue
        emitted_keys.add(key)
        lines.append(f"{key}: {resolved_value}")

    for key, value in existing_metadata.items():
        if key in emitted_keys:
            continue
        normalized = normalize_frontmatter_value(value)
        if not normalized:
            continue
        lines.append(f"{key}: {normalized}")

    lines.extend(["---", ""])
    if body_text:
        lines.append(body_text)
    return "\n".join(lines).rstrip() + "\n"


# 主流程仍保留原有 Markdown 章节结构，这里只把模板渲染从 pipeline 中拆出去。
def build_markdown(sample: SampleRecord, payload: dict[str, Any]) -> str:
    if payload.get("文件类型") == "markdown":
        return build_preserved_markdown(sample, payload)

    risks = payload.get("风险说明", []) or []
    notes = payload.get("备注", []) or []
    dedup_keys = payload.get("去重主键", []) or []
    preview_text = payload.get("文本预览", "") or "无"

    # 兜底清洗：标题里如果混进了 HTML 注释（例如拆分链路的 "<!-- 分片：xxx -->"）或 markdown 标题符号，去掉。
    raw_title = str(payload.get("标题", "") or "").strip()
    cleaned_title = re.sub(r"<!--.*?-->", "", raw_title, flags=re.DOTALL).strip()
    cleaned_title = re.sub(r"^#+\s*", "", cleaned_title).strip()
    if not cleaned_title:
        cleaned_title = str(payload.get("原始文件名", "") or "").strip() or "未命名资料"

    lines = [
        f"# {cleaned_title}",
        "",
        "## 元数据",
        f"- 原始文件名：{payload['原始文件名']}",
        f"- 原始路径：{payload['原始路径']}",
        f"- 文档分类：{payload['文档分类']}",
        f"- 推荐模板：{payload['推荐模板']}",
    ]
    if not is_empty_payload_value(payload.get("知识库分类")):
        lines.append(f"- 知识库分类：{format_markdown_value(payload.get('知识库分类'))}")
    if not is_empty_payload_value(payload.get("分类来源")):
        lines.append(f"- 分类来源：{format_markdown_value(payload.get('分类来源'))}")
    if not is_empty_payload_value(payload.get("人工审核状态")):
        lines.append(f"- 人工审核状态：{format_markdown_value(payload.get('人工审核状态'))}")
    if not is_empty_payload_value(payload.get("人工审核时间")):
        lines.append(f"- 人工审核时间：{format_markdown_value(payload.get('人工审核时间'))}")
    for label, key in (
        ("一级分类", "一级分类"),
        ("二级分类", "二级分类"),
        ("分类置信度", "分类置信度"),
        ("分类依据", "分类依据"),
    ):
        value = payload.get(key)
        if not is_empty_payload_value(value):
            lines.append(f"- {label}：{format_markdown_value(value)}")
    lines.append("")

    if payload.get("推荐模板") == "政策官方文件模板":
        sections = build_policy_sections(payload)
        core_tasks = payload.get("核心任务", []) or []
        lines.extend([
            "## 一、文件摘要",
            f"- {sections['文件摘要']}",
            "",
            "## 二、核心要求",
            f"- {sections['核心要求']}",
            "",
            "## 三、与低空/长风业务相关的部分",
            f"- {sections['业务相关']}",
            "",
            "## 四、执行或应用意义",
            f"- {sections['执行意义']}",
            "",
            "## 五、时效与边界",
            f"- {sections['时效边界']}",
            "",
            "## 六、字段提取结果",
            f"- 文件标题：{payload.get('文件标题', '')}",
            f"- 发文字号：{payload.get('发文字号', '')}",
            f"- 发文单位：{payload.get('发文单位', '')}",
            f"- 成文日期：{payload.get('成文日期', '')}",
            f"- 生效状态：{payload.get('生效状态', '')}",
            f"- 核心任务：{'；'.join(core_tasks) if core_tasks else '未提取'}",
            "",
        ])
    elif payload.get("推荐模板") == "供应商企业模板":
        sections = build_supplier_sections(payload)
        if sections["企业摘要"]:
            lines.extend([
                "## 一、企业摘要",
                f"- {sections['企业摘要']}",
                "",
            ])

        supplier_direction_lines: list[str] = []
        if sections["主营方向"]:
            supplier_direction_lines.append(f"- 主营方向：{sections['主营方向']}")
        if sections["核心能力"]:
            supplier_direction_lines.append(f"- 核心能力：{sections['核心能力']}")
        if supplier_direction_lines:
            lines.extend([
                "## 二、主营方向与能力",
                *supplier_direction_lines,
                "",
            ])

        if sections["核心产品"]:
            lines.extend([
                "## 三、代表产品或服务",
                f"- 核心产品：{sections['核心产品']}",
                "",
            ])

        supplier_field_lines: list[str] = []
        if sections["企业名称"]:
            supplier_field_lines.append(f"- 企业名称：{sections['企业名称']}")
        if sections["企业类别"]:
            supplier_field_lines.append(f"- 企业类别：{sections['企业类别']}")
        if sections["主营方向"]:
            supplier_field_lines.append(f"- 主营方向：{sections['主营方向']}")
        if sections["核心产品"]:
            supplier_field_lines.append(f"- 核心产品：{sections['核心产品']}")
        if sections["核心能力"]:
            supplier_field_lines.append(f"- 核心能力：{sections['核心能力']}")
        if supplier_field_lines:
            lines.extend([
                "## 四、字段提取结果",
                *supplier_field_lines,
                "",
            ])

        for heading, content in build_supplier_deep_sections(payload):
            if content.strip():
                append_rich_markdown_section(lines, heading, content)
    elif payload.get("推荐模板") == "单位联系人模板":
        sections = build_contact_sections(payload)
        lines.extend([
            "## 一、单位摘要",
            f"- {sections['单位摘要']}",
            "",
            "## 二、联系人与对接线索",
            f"- 联系人姓名：{sections['联系人姓名']}",
            f"- 联系人角色：{sections['联系人角色']}",
            f"- 联系方式：{sections['联系方式']}",
            f"- 对接线索：{sections['对接线索']}",
            "",
            "## 三、字段提取结果",
            f"- 单位名称：{sections['单位名称']}",
            f"- 单位类型：{sections['单位类型']}",
            f"- 联系人姓名：{sections['联系人姓名']}",
            f"- 联系人角色：{sections['联系人角色']}",
            f"- 联系方式：{sections['联系方式']}",
            f"- 对接线索：{sections['对接线索']}",
            "",
        ])
    elif payload.get("推荐模板") == "方案案例模板":
        sections = build_solution_sections(payload)

        def _sol(key: str) -> str:
            val = sections.get(key, "")
            if not val or val == "未提取":
                return ""
            return val

        if _sol("应用背景"):
            lines.extend(["## 一、应用背景", f"- {_sol('应用背景')}", ""])
        if _sol("解决问题"):
            lines.extend(["## 二、解决的问题", f"- {_sol('解决问题')}", ""])
        if _sol("资料形态") or payload.get("是否需要拆分"):
            sub = []
            if _sol("资料形态"):
                sub.append(f"- 当前更像：{_sol('资料形态')}")
            if payload.get("是否需要拆分"):
                sub.append(f"- 是否需要拆分：是")
                if payload.get("拆分说明"):
                    sub.append(f"- 拆分说明：{payload['拆分说明']}")
            if sub:
                lines.extend(["## 三、资料形态判断", *sub, ""])
        if _sol("产品能力"):
            lines.extend(["## 四、投入的产品/设备/能力", f"- {_sol('产品能力')}", ""])
        if _sol("实施方式"):
            lines.extend(["## 五、实施方式", f"- {_sol('实施方式')}", ""])
        if _sol("预算组织"):
            lines.extend(["## 六、预算、进度与组织方式", f"- {_sol('预算组织')}", ""])
        if _sol("效果数据"):
            lines.extend(["## 七、结果与效果数据", f"- {_sol('效果数据')}", ""])
        if _sol("可复用经验"):
            lines.extend(["## 八、可复用经验", f"- {_sol('可复用经验')}", ""])

        sol_field_map = [
            ("方案名称", payload.get('方案名称字段')),
            ("所属场景", payload.get('所属场景字段')),
            ("客户/使用单位", payload.get('客户名称字段')),
            ("文件日期", payload.get('文件日期字段')),
            ("解决的问题", payload.get('解决问题字段')),
            ("投入的产品/设备/能力", payload.get('产品能力字段')),
            ("实施方式", payload.get('实施方式字段')),
            ("预算、进度与组织方式", payload.get('预算组织字段')),
            ("结果与效果数据", payload.get('效果数据字段')),
            ("可复用经验", payload.get('可复用经验字段')),
            ("证据类型", payload.get('证据类型字段')),
        ]
        sol_field_lines = [f"- {lbl}：{val}" for lbl, val in sol_field_map if not is_empty_payload_value(val)]
        if sol_field_lines:
            lines.extend(["## 九、字段提取结果", *sol_field_lines, ""])
        for heading, content in build_solution_deep_sections(payload):
            if content.strip():
                append_rich_markdown_section(lines, heading, content)
    elif payload.get("推荐模板") == "产品设备模板":
        sections = build_product_sections(payload)
        lines.extend([
            "## 一、资料摘要",
            f"- {sections['资料摘要']}",
            "",
        ])

        if sections["核心用途"]:
            lines.extend([
                "## 二、核心用途",
                f"- {sections['核心用途']}",
                "",
            ])

        lines.extend([
            "## 三、资料形态判断",
            f"- 当前更像：{sections['资料形态'] or '未提取'}",
            f"- 是否需要拆分：{'是' if payload['是否需要拆分'] else '否'}",
            f"- 拆分说明：{payload['拆分说明']}",
            "",
        ])

        if sections["核心参数"]:
            lines.extend([
                "## 四、核心参数",
                f"- {sections['核心参数']}",
                "",
            ])

        if sections["适用场景"]:
            lines.extend([
                "## 五、适用场景",
                f"- {sections['适用场景']}",
                "",
            ])

        if sections["搭配关系"]:
            lines.extend([
                "## 六、搭配、替代与挂载关系",
                f"- {sections['搭配关系']}",
                "",
            ])

        product_field_lines: list[str] = []
        if format_product_optional_value(payload.get('产品名称字段')):
            product_field_lines.append(f"- 产品名称：{format_product_optional_value(payload.get('产品名称字段'))}")
        if format_product_optional_value(payload.get('型号字段')):
            product_field_lines.append(f"- 型号：{format_product_optional_value(payload.get('型号字段'))}")
        if format_product_optional_value(payload.get('供应商名称字段')):
            product_field_lines.append(f"- 供应商名称：{format_product_optional_value(payload.get('供应商名称字段'))}")
        if format_product_optional_value(payload.get('产品类别字段')):
            product_field_lines.append(f"- 产品类别：{format_product_optional_value(payload.get('产品类别字段'))}")
        if sections["核心用途"]:
            product_field_lines.append(f"- 核心用途：{sections['核心用途']}")
        if sections["核心参数"]:
            product_field_lines.append(f"- 核心参数：{sections['核心参数']}")
        if sections["适用场景"]:
            product_field_lines.append(f"- 适用场景：{sections['适用场景']}")
        if sections["搭配关系"]:
            product_field_lines.append(f"- 搭配关系：{sections['搭配关系']}")
        if format_product_optional_value(payload.get('产品证据类型字段')):
            product_field_lines.append(f"- 证据类型：{format_product_optional_value(payload.get('产品证据类型字段'))}")
        if format_product_optional_value(payload.get('报告文档类型字段')):
            product_field_lines.append(f"- 报告文档类型：{format_product_optional_value(payload.get('报告文档类型字段'))}")
        if format_product_optional_value(payload.get('产品编号字段')):
            product_field_lines.append(f"- 产品编号：{format_product_optional_value(payload.get('产品编号字段'))}")
        if format_product_optional_value(payload.get('检定依据字段')):
            product_field_lines.append(f"- 检定依据：{format_product_optional_value(payload.get('检定依据字段'))}")
        if format_product_optional_value(payload.get('检定结果字段')):
            product_field_lines.append(f"- 检定结果：{format_product_optional_value(payload.get('检定结果字段'))}")
        if format_product_optional_value(payload.get('检测机构字段')):
            product_field_lines.append(f"- 检测机构：{format_product_optional_value(payload.get('检测机构字段'))}")
        if format_product_optional_value(payload.get('报告编号字段')):
            product_field_lines.append(f"- 报告编号：{format_product_optional_value(payload.get('报告编号字段'))}")
        if format_product_optional_value(payload.get('报告日期字段')):
            product_field_lines.append(f"- 报告日期：{format_product_optional_value(payload.get('报告日期字段'))}")
        if format_product_optional_value(payload.get('有效期至字段')):
            product_field_lines.append(f"- 有效期至：{format_product_optional_value(payload.get('有效期至字段'))}")
        if product_field_lines:
            lines.extend([
                "## 七、字段提取结果",
                *product_field_lines,
                "",
            ])
    elif payload.get("推荐模板") == "教育培训模板":
        sections = build_education_training_sections(payload)
        lines.extend([
            "## 一、资料摘要",
            f"- {sections['资料摘要']}",
            "",
            "## 二、培训主题",
            f"- {sections['培训主题'] or '未提取'}",
            "",
            "## 三、适用对象",
            f"- {sections['适用对象'] or '未提取'}",
            "",
            "## 四、培训类型",
            f"- {sections['培训类型'] or '未提取'}",
            "",
            "## 五、专业方向/课程体系",
        ])
        if sections["专业方向"]:
            lines.append(f"- 专业方向：{sections['专业方向']}")
        if sections["课程体系"]:
            lines.append(f"- 课程体系：{sections['课程体系']}")
        if not sections["专业方向"] and not sections["课程体系"]:
            lines.append("- 未提取")
        lines.extend(["",])

        if sections["实施方式"]:
            lines.extend([
                "## 六、实施方式",
                f"- {sections['实施方式']}",
                "",
            ])

        if sections["核心内容"]:
            lines.extend([
                "## 七、核心内容",
                f"- {sections['核心内容']}",
                "",
            ])

        education_field_lines: list[str] = []
        if format_education_optional_value(payload.get('文件标题')):
            education_field_lines.append(f"- 文件标题：{format_education_optional_value(payload.get('文件标题'))}")
        if format_education_optional_value(payload.get('单位名称字段')):
            education_field_lines.append(f"- 单位名称：{format_education_optional_value(payload.get('单位名称字段'))}")
        if sections["培训主题"]:
            education_field_lines.append(f"- 培训主题：{sections['培训主题']}")
        if sections["适用对象"]:
            education_field_lines.append(f"- 适用对象：{sections['适用对象']}")
        if sections["培训类型"]:
            education_field_lines.append(f"- 培训类型：{sections['培训类型']}")
        if sections["专业方向"]:
            education_field_lines.append(f"- 专业方向：{sections['专业方向']}")
        if sections["课程体系"]:
            education_field_lines.append(f"- 课程体系：{sections['课程体系']}")
        if sections["实施方式"]:
            education_field_lines.append(f"- 实施方式：{sections['实施方式']}")
        if sections["核心内容"]:
            education_field_lines.append(f"- 核心内容：{sections['核心内容']}")
        if education_field_lines:
            lines.extend([
                "## 八、字段提取结果",
                *education_field_lines,
                "",
            ])
        for heading, content in build_education_training_deep_sections(payload):
            append_rich_markdown_section(lines, heading, content)
    elif payload.get("推荐模板") == "招标采购文件模板":
        sections = build_procurement_sections(payload)
        lines.extend([
            "## 一、资料摘要",
            f"- {sections['资料摘要']}",
            "",
            "## 二、采购方式与预算",
            f"- 采购方式：{sections['采购方式']}",
            f"- 预算/最高限价：{sections['预算限价']}",
            "",
            "## 三、评分办法",
            f"- {sections['评分办法']}",
            "",
            "## 四、采购需求摘要",
            f"- {sections['采购需求']}",
            "",
            "## 五、字段提取结果",
            f"- 文件标题：{payload.get('文件标题', '')}",
            f"- 项目编号：{payload.get('项目编号字段', '')}",
            f"- 采购人：{payload.get('采购人字段', '')}",
            f"- 采购代理机构：{payload.get('采购代理机构字段', '')}",
            f"- 采购方式：{payload.get('采购方式字段', '')}",
            f"- 文件日期：{payload.get('文件日期字段', '')}",
            f"- 预算/最高限价：{payload.get('预算最高限价字段', '')}",
            f"- 评分办法：{payload.get('评分办法字段', '')}",
            f"- 采购需求摘要：{payload.get('采购需求摘要字段', '')}",
            "",
        ])
    elif payload.get("推荐模板") == "合同商务模板":
        sections = build_contract_sections(payload)
        lines.extend([
            "## 一、资料摘要",
            f"- {sections['资料摘要']}",
            "",
            "## 二、合同基本信息",
            f"- 合同名称：{sections['合同名称']}",
            f"- 合同编号：{sections['合同编号']}",
            f"- 合同类型：{sections['合同类型']}",
            f"- 签订日期：{sections['签订日期']}",
            "",
            "## 三、合同主体",
            f"- 甲方：{sections['甲方']}",
            f"- 乙方：{sections['乙方']}",
            "",
            "## 四、合同标的与金额",
            f"- 合同标的：{sections['合同标的']}",
            f"- 合同金额：{sections['合同金额']}",
            f"- 合同期限：{sections['合同期限']}",
            f"- 履约状态：{sections['履约状态']}",
            "",
            "## 五、字段提取结果",
            f"- 文件标题：{payload.get('文件标题', '')}",
            f"- 合同名称：{sections['合同名称']}",
            f"- 合同编号：{sections['合同编号']}",
            f"- 合同类型：{sections['合同类型']}",
            f"- 甲方：{sections['甲方']}",
            f"- 乙方：{sections['乙方']}",
            f"- 合同金额：{sections['合同金额']}",
            f"- 合同期限：{sections['合同期限']}",
            f"- 签订日期：{sections['签订日期']}",
            f"- 合同标的：{sections['合同标的']}",
            f"- 履约状态：{sections['履约状态']}",
            "",
        ])
    elif payload.get("推荐模板") == "报价清单模板":
        sections = build_price_quote_sections(payload)
        lines.extend([
            "## 一、资料摘要",
            f"- {sections['资料摘要']}",
            "",
            "## 二、报价基本信息",
            f"- 报价单名称：{sections['报价单名称']}",
            f"- 报价主体：{sections['报价主体']}",
            f"- 报价日期：{sections['报价日期']}",
            f"- 有效期：{sections['有效期']}",
            f"- 价格类型：{sections['价格类型']}",
            "",
            "## 三、产品型号价格",
            sections["产品型号价格"],
            "",
            "## 四、字段提取结果",
            f"- 文件标题：{payload.get('文件标题', '')}",
            f"- 报价单名称：{sections['报价单名称']}",
            f"- 报价主体：{sections['报价主体']}",
            f"- 产品型号价格：{sections['产品型号价格']}",
            f"- 有效期：{sections['有效期']}",
            f"- 报价日期：{sections['报价日期']}",
            f"- 价格类型：{sections['价格类型']}",
            "",
        ])
    elif payload.get("推荐模板") == "行业知识模板":
        sections = build_industry_knowledge_sections(payload)
        lines.extend([
            "## 一、资料摘要",
            f"- {sections['资料摘要']}",
            "",
        ])

        if sections["行业领域"]:
            lines.extend([
                "## 二、行业领域",
                f"- {sections['行业领域']}",
                "",
            ])

        if sections["产业链环节"]:
            lines.extend([
                "## 三、产业链环节",
                f"- {sections['产业链环节']}",
                "",
            ])

        if sections["市场规模"]:
            lines.extend([
                "## 四、市场规模",
                f"- {sections['市场规模']}",
                "",
            ])

        if sections["核心玩家"]:
            lines.extend([
                "## 五、核心玩家",
                f"- {sections['核心玩家']}",
                "",
            ])

        if sections["发展趋势"]:
            lines.extend([
                "## 六、发展趋势",
                f"- {sections['发展趋势']}",
                "",
            ])

        industry_field_lines: list[str] = []
        if format_industry_knowledge_optional_value(payload.get('文件标题')):
            industry_field_lines.append(f"- 文件标题：{format_industry_knowledge_optional_value(payload.get('文件标题'))}")
        if sections["行业领域"]:
            industry_field_lines.append(f"- 行业领域：{sections['行业领域']}")
        if sections["产业链环节"]:
            industry_field_lines.append(f"- 产业链环节：{sections['产业链环节']}")
        if sections["市场规模"]:
            industry_field_lines.append(f"- 市场规模：{sections['市场规模']}")
        if sections["核心玩家"]:
            industry_field_lines.append(f"- 核心玩家：{sections['核心玩家']}")
        if sections["发展趋势"]:
            industry_field_lines.append(f"- 发展趋势：{sections['发展趋势']}")
        if industry_field_lines:
            lines.extend([
                "## 字段提取结果",
                *industry_field_lines,
                "",
            ])
        for heading, content in build_industry_knowledge_deep_sections(payload):
            if content.strip():
                append_rich_markdown_section(lines, heading, content)
    elif payload.get("处理路径") == "素材":
        lines.extend([
            "## 素材信息",
            f"- 文件名：{payload['原始文件名']}",
            f"- 原始路径：{payload['原始路径']}",
            f"- 文件格式：{payload['文件格式']}",
            f"- 处理说明：{payload.get('抽取说明', '')}",
            "",
        ])
    else:
        sections = build_generic_sections(payload)
        lines.extend([
            "## 摘要",
            f"- 核心摘要：{payload.get('核心摘要', '') or '无'}",
            f"- 文本预览：{preview_text}",
            "",
            "## 资料摘要",
            f"- {sections['资料摘要']}",
            "",
            "## 抽取说明",
            f"- {sections['抽取说明']}",
            "",
            "## 归档建议",
            f"- {sections['归档建议']}",
            "",
        ])

    append_full_text_section(lines, payload)

    supplemental_lines = build_supplemental_field_lines(payload.get("推荐模板", ""), payload)
    if supplemental_lines:
        lines.extend([
            "## 模型补充字段",
            *supplemental_lines,
            "",
        ])

    lines.extend([
        "## 证据与原始依据",
        f"- 原始来源：{payload['原始路径']}",
        f"- 去重主键：{'; '.join(dedup_keys)}",
        f"- 是否需要拆分：{'是' if payload['是否需要拆分'] else '否'}",
        f"- 拆分说明：{payload['拆分说明']}",
        f"- 抽取说明：{payload['抽取说明']}",
        "",
        "## 入库与归档判断",
        f"- 是否适合直接入库：{'是' if payload['是否适合直接入库'] else '否'}",
        f"- 当前分流：{payload['分流结果']}",
        f"- 风险说明：{'；'.join(risks)}",
    ])
    if not is_empty_payload_value(payload.get("导入状态")):
        lines.append(f"- 导入状态：{format_markdown_value(payload.get('导入状态'))}")
    if not is_empty_payload_value(payload.get("导入批次号")):
        lines.append(f"- 导入批次号：{format_markdown_value(payload.get('导入批次号'))}")
    if not is_empty_payload_value(payload.get("目标知识库ID列表")):
        lines.append(f"- 目标知识库ID列表：{format_markdown_value(payload.get('目标知识库ID列表'))}")
    lines.extend([
        "",
        "## 备注",
        *[f"- {note}" for note in notes],
    ])
    return "\n".join(lines)
