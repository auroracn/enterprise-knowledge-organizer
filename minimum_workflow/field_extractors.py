from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from minimum_workflow.contracts import ExtractionResult, SampleRecord


def extract_fields(sample: SampleRecord, extraction: ExtractionResult) -> dict[str, Any]:
    if sample.recommended_template == "政策官方文件模板":
        return extract_policy_fields(sample, extraction)
    if sample.recommended_template == "供应商企业模板":
        return extract_supplier_fields(sample, extraction)
    if sample.recommended_template == "单位联系人模板":
        return extract_contact_fields(sample, extraction)
    if sample.recommended_template == "方案案例模板":
        return extract_solution_fields(sample, extraction)
    if sample.recommended_template == "产品设备模板":
        return extract_product_fields(sample, extraction)
    if sample.recommended_template == "教育培训模板":
        return extract_education_training_fields(sample, extraction)
    if sample.recommended_template == "招标采购文件模板":
        return extract_procurement_fields(sample, extraction)
    if sample.recommended_template == "合同商务模板":
        return extract_contract_fields(sample, extraction)
    if sample.recommended_template == "报价清单模板":
        return extract_price_quote_fields(sample, extraction)
    if sample.recommended_template == "行业知识模板":
        return extract_industry_knowledge_fields(sample, extraction)
    if sample.recommended_template and "参考架构" in sample.recommended_template:
        return extract_reference_fields(sample, extraction)
    return {}


def extract_policy_fields(sample: SampleRecord, extraction: ExtractionResult) -> dict[str, Any]:
    text = extraction.extracted_text or ""
    title = infer_policy_title(sample, text)
    document_number = infer_policy_document_number(sample, text)
    issuing_unit = infer_policy_issuing_unit(sample, text)
    issue_date = infer_policy_issue_date(text)
    effective_status = infer_policy_status(text)
    core_tasks = extract_policy_tasks(text)

    return {
        "文件标题": title,
        "发文字号": document_number,
        "发文单位": issuing_unit,
        "成文日期": issue_date,
        "核心任务": core_tasks,
        "生效状态": effective_status,
    }


def first_match(text: str, patterns: list[str], default: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            return clean_value(match.group(1))
    return default


def clean_value(value: str) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip(" ：:《》")


def is_placeholder_education_title(value: str) -> bool:
    cleaned = clean_value(value)
    if not cleaned:
        return True
    if re.fullmatch(r"新建(?:文本文档|文档)(?:\s*\(\d+\))?(?:\.[A-Za-z0-9]+)?", cleaned):
        return True
    return cleaned in {"教育培训方向", "培训方向", "专业方向", "课程方向", "方向"}


def clean_education_title_candidate(value: str) -> str:
    normalized = re.sub(r"^#+\s*", "", value or "")
    cleaned = clean_value(normalized)
    if not cleaned or is_placeholder_education_title(cleaned):
        return ""
    if is_generic_education_section_heading(cleaned):
        return ""
    if len(cleaned) > 40:
        return ""
    if any(token in cleaned for token in ["。", "；", "!", "?", "现将", "具体如下", "如下："]):
        return ""
    if cleaned.count("，") >= 2 or cleaned.count("、") >= 4:
        return ""
    return cleaned


def is_generic_education_section_heading(value: str) -> bool:
    cleaned = clean_value(value)
    if not cleaned:
        return True
    generic_titles = {
        "建设方向",
        "课程建设",
        "体系图",
        "资源开发流程",
        "教学资源开发流程",
        "部分建设案例",
        "公司介绍",
        "合作案例",
    }
    if cleaned in generic_titles:
        return True
    if re.fullmatch(r"模块[一二三四五六七八九十0-9]+", cleaned):
        return True
    if re.fullmatch(r"(?:module|part)\s*[a-z0-9一二三四五六七八九十]+", cleaned, re.IGNORECASE):
        return True
    return False


def fallback_education_title(sample: SampleRecord) -> str:
    if sample.title_hint and not is_placeholder_education_title(sample.title_hint):
        return clean_value(sample.title_hint)
    return ""


def infer_policy_title(sample: SampleRecord, text: str) -> str:
    title = first_match(
        text,
        [
            r"文件名称[:：]\s*《?([^\n》]+)》?",
            r"现公布《([^》]+)》",
            r"^\s*([^\n]+政策措施[^\n]*)",
            r"^\s*([^\n]+条例[^\n]*)$",
        ],
        sample.title_hint,
    )
    cleaned = clean_value(title)
    if not cleaned:
        return ""
    if re.match(r"^\d+(?:\.\d+)+", cleaned):
        return sample.title_hint
    if any(token in cleaned for token in ["；", "。", "资格条件", "投标", "供应商", "采购文件", "招标", "评标"]):
        return sample.title_hint
    if cleaned.startswith("符合《"):
        return sample.title_hint
    if "条例" in cleaned and len(cleaned) > 40:
        return sample.title_hint
    return cleaned



def infer_policy_document_number(sample: SampleRecord, text: str) -> str:
    labeled_number = first_match(text, [r"发文字号[:：]\s*([^\n]+)"], "")
    if labeled_number:
        return labeled_number
    source_number = re.search(r"[（(]([^）)]*第\d+号)[）)]", sample.source_path or "")
    if source_number:
        return clean_value(source_number.group(1))
    return first_match(text, [r"^\s*(第\d+号)\s*$"], "")



def infer_policy_issuing_unit(sample: SampleRecord, text: str) -> str:
    labeled_unit = first_match(text, [r"发文单位[:：]\s*([^\n]+)"], "")
    if labeled_unit:
        return labeled_unit
    if "国务院" in text and "中央军事委员会" in text:
        return "国务院、中央军委"
    return sample.unit_name_hint



def infer_policy_issue_date(text: str) -> str:
    raw_date = first_match(
        text,
        [
            r"成文日期[:：]\s*([^\n]+)",
            r"^\s*(20\d{2}年\d{1,2}月\d{1,2}日)\s*$",
        ],
        "",
    )
    return normalize_policy_date(raw_date)



def extract_policy_tasks(text: str) -> list[str]:
    tasks = re.findall(r"^\s*([一二三四五六七八九十]+、[^\n]+)", text, re.MULTILINE)
    cleaned = [clean_value(item) for item in tasks if clean_value(item)]
    if cleaned:
        return cleaned[:8]

    chapter_titles = re.findall(r"^\s*#\s*(第[一二三四五六七八九十百零〇]+章\s*[^\n]+)", text, re.MULTILINE)
    chapter_cleaned = [clean_value(item.replace("  ", " ")) for item in chapter_titles if clean_value(item)]
    if chapter_cleaned:
        return chapter_cleaned[:8]
    return []


def extract_supplier_fields(sample: SampleRecord, extraction: ExtractionResult) -> dict[str, Any]:
    text = extraction.extracted_text or ""
    company_name = infer_supplier_company_name(sample, text)
    company_type = infer_supplier_type(text)
    # 供应商资料经常来自画册/宣传册，不一定有标准字段标签，因此这里增加正文兜底抽取。
    business_direction = first_match(text, [r"主营方向[:：]\s*([^\n]+)", r"主营业务[:：]\s*([^\n]+)"], "") or infer_supplier_business_direction(text)
    core_products = extract_labeled_list(text, [r"核心产品[:：]\s*([^\n]+)", r"代表产品[:：]\s*([^\n]+)"]) or infer_supplier_products(text)
    core_capabilities = extract_labeled_list(text, [r"核心能力[:：]\s*([^\n]+)", r"能力介绍[:：]\s*([^\n]+)"]) or infer_supplier_capabilities(text)
    return {
        "企业名称": company_name,
        "企业类别": company_type,
        "主营方向": business_direction,
        "核心产品": core_products,
        "核心能力": core_capabilities,
    }


def extract_contact_fields(sample: SampleRecord, extraction: ExtractionResult) -> dict[str, Any]:
    text = extraction.extracted_text or ""
    unit_name = first_match(
        text,
        [r"单位名称[:：]\s*([^\n]+)", r"采购单位[:：]\s*([^\n]+)", r"责任单位[:：]\s*([^\n]+)"],
        sample.unit_name_hint or sample.subject_name_hint,
    )
    unit_type = infer_unit_type(text)
    contact_name = first_match(text, [r"联系人[:：]\s*([^\n，,（( ]+)"], "")
    contact_role = first_match(text, [r"联系人角色[:：]\s*([^\n]+)", r"职务[:：]\s*([^\n]+)"], "")
    contact_info = first_match(text, [r"联系方式[:：]\s*([^\n]+)", r"联系电话[:：]\s*([^\n]+)", r"电话[:：]\s*([^\n]+)"], "")
    contact_clues = extract_contact_clues(text)
    return {
        "单位名称字段": unit_name,
        "单位类型字段": unit_type,
        "联系人姓名": contact_name,
        "联系人角色字段": contact_role,
        "联系方式字段": contact_info,
        "对接线索字段": contact_clues,
    }


def extract_product_fields(sample: SampleRecord, extraction: ExtractionResult) -> dict[str, Any]:
    text = extraction.extracted_text or ""
    product_name = infer_product_name(sample, text)
    model_name = infer_product_model(sample, text)
    supplier_name = infer_product_supplier(sample, text)
    product_type = infer_product_type(sample, text)
    core_usage = infer_product_usage(text)
    core_params = infer_product_params(text)
    application_scene = infer_product_scene(sample, text)
    relation_summary = infer_product_relations(text)
    evidence_type = infer_product_evidence_type(sample, text)
    report_document_type = infer_report_document_type(sample, text)
    product_serial_no = infer_product_serial_no(text)
    test_basis = infer_test_basis(text)
    test_result = infer_test_result(text)
    test_organization = infer_test_organization(text)
    report_no = infer_report_no(text)
    report_date = infer_report_date(text)
    expire_date = infer_expire_date(text)
    return {
        "产品名称字段": product_name,
        "型号字段": model_name,
        "供应商名称字段": supplier_name,
        "产品类别字段": product_type,
        "核心用途字段": core_usage,
        "核心参数字段": core_params,
        "适用场景字段": application_scene,
        "搭配关系字段": relation_summary,
        "产品证据类型字段": evidence_type,
        "报告文档类型字段": report_document_type,
        "产品编号字段": product_serial_no,
        "检定依据字段": test_basis,
        "检定结果字段": test_result,
        "检测机构字段": test_organization,
        "报告编号字段": report_no,
        "报告日期字段": report_date,
        "有效期至字段": expire_date,
    }


# 方案类样例形态差异很大，这里先按规则做最小字段兜底，后续再接模型增强抽取。
def extract_solution_fields(sample: SampleRecord, extraction: ExtractionResult) -> dict[str, Any]:
    text = extraction.extracted_text or ""
    solution_name = infer_solution_name(sample, text)
    scene_name = infer_solution_scene(sample, text)
    customer_name = infer_solution_customer(sample, text)
    file_date = infer_solution_file_date(sample, text)
    problem_summary = infer_solution_problem(text)
    product_capability = infer_solution_products(text)
    implementation = infer_solution_implementation(text)
    budget_summary = infer_solution_budget(text)
    effect_summary = infer_solution_effect(text)
    reuse_summary = infer_solution_reuse(text)
    evidence_type = infer_solution_evidence_type(sample, text)
    return {
        "方案名称字段": solution_name,
        "所属场景字段": scene_name,
        "客户名称字段": customer_name,
        "文件日期字段": file_date,
        "解决问题字段": problem_summary,
        "产品能力字段": product_capability,
        "实施方式字段": implementation,
        "预算组织字段": budget_summary,
        "效果数据字段": effect_summary,
        "可复用经验字段": reuse_summary,
        "证据类型字段": evidence_type,
    }


# 招标/采购文件先做保守规则抽取，命中不稳的字段留空，避免把目录词误写成正式事实。
def extract_procurement_fields(sample: SampleRecord, extraction: ExtractionResult) -> dict[str, Any]:
    text = extraction.extracted_text or ""
    return {
        "文件标题": infer_procurement_title(sample, text),
        "项目编号字段": infer_procurement_project_number(text),
        "采购人字段": infer_procurement_purchaser(sample, text),
        "采购代理机构字段": infer_procurement_agency(text),
        "采购方式字段": infer_procurement_method(text),
        "文件日期字段": infer_procurement_file_date(sample, text),
        "预算最高限价字段": infer_procurement_budget(text),
        "评分办法字段": infer_procurement_scoring_method(text),
        "采购需求摘要字段": infer_procurement_requirement_summary(text),
    }


def infer_supplier_type(text: str) -> str:
    if "制造" in text or "生产" in text:
        return "厂家"
    if "代理" in text:
        return "代理商"
    if "集成" in text:
        return "集成商"
    return "未注明"


def infer_procurement_title(sample: SampleRecord, text: str) -> str:
    labeled_title = first_match(
        text,
        [
            r"项目名称[:：]\s*([^\n]+)",
            r"采购项目名称[:：]\s*([^\n]+)",
            r"招标项目名称[:：]\s*([^\n]+)",
            r"文件名称[:：]\s*《?([^\n》]+)》?",
        ],
        sample.title_hint,
    )
    cleaned = clean_value(labeled_title)
    if not cleaned:
        return clean_value(sample.title_hint)
    if any(keyword in cleaned for keyword in ["供应商须知", "采购公告", "评标方法", "采购需求", "响应文件格式"]):
        return clean_value(sample.title_hint)
    return cleaned


def infer_procurement_project_number(text: str) -> str:
    return first_match(
        text,
        [
            r"项目编号[:：]\s*([^\n]+)",
            r"招标编号[:：]\s*([^\n]+)",
            r"采购编号[:：]\s*([^\n]+)",
        ],
        "",
    )


def infer_procurement_purchaser(sample: SampleRecord, text: str) -> str:
    purchaser = first_match(
        text,
        [
            r"采购人[:：]\s*([^\n]+)",
            r"采购单位[:：]\s*([^\n]+)",
            r"招标人[:：]\s*([^\n]+)",
        ],
        sample.unit_name_hint or sample.subject_name_hint,
    )
    if any(keyword in purchaser for keyword in ["代理", "有限公司", "公司"]):
        direct = first_match(text, [r"采购人名称[:：]\s*([^\n]+)"], "")
        if direct:
            return direct
    return purchaser


def infer_procurement_agency(text: str) -> str:
    return first_match(
        text,
        [
            r"采购代理机构[:：]\s*([^\n]+)",
            r"代理机构[:：]\s*([^\n]+)",
            r"招标代理机构[:：]\s*([^\n]+)",
        ],
        "",
    )


def infer_procurement_method(text: str) -> str:
    labeled_method = first_match(text, [r"采购方式[:：]\s*([^\n]+)", r"招标方式[:：]\s*([^\n]+)"], "")
    if labeled_method:
        return labeled_method
    for keyword in ["公开招标", "邀请招标", "竞争性磋商", "竞争性谈判", "询价", "单一来源采购"]:
        if keyword in text:
            return keyword
    return ""


def infer_procurement_file_date(sample: SampleRecord, text: str) -> str:
    raw_date = first_match(
        text,
        [
            r"文件日期[:：]\s*([^\n]+)",
            r"编制日期[:：]\s*([^\n]+)",
            r"采购文件(?:发布时间|日期)?[:：]\s*([^\n]+)",
            r"^\s*(20\d{2}年\d{1,2}月\d{1,2}日)\s*$",
            r"^\s*(20\d{2}年\d{1,2}月)\s*$",
        ],
        "",
    )
    if raw_date:
        normalized = normalize_policy_date(raw_date)
        if re.fullmatch(r"20\d{2}(?:-\d{2})?(?:-\d{2})?", normalized):
            return normalized
    return ""


def infer_procurement_budget(text: str) -> str:
    return first_match(
        text,
        [
            r"预算金额[:：]\s*([^\n]+)",
            r"项目预算[:：]\s*([^\n]+)",
            r"采购预算[:：]\s*([^\n]+)",
            r"最高限价[:：]\s*([^\n]+)",
            r"最高投标限价[:：]\s*([^\n]+)",
        ],
        "",
    )


def infer_procurement_scoring_method(text: str) -> str:
    labeled = first_match(
        text,
        [
            r"评分办法[:：]\s*([^\n]+)",
            r"评标办法[:：]\s*([^\n]+)",
            r"评审方法[:：]\s*([^\n]+)",
        ],
        "",
    )
    if labeled:
        return labeled
    lines = [clean_value(line) for line in text.splitlines()]
    for line in lines:
        if not line:
            continue
        if "综合评分法" in line:
            return "综合评分法"
        if "最低评标价法" in line:
            return "最低评标价法"
    for line in lines:
        if not line:
            continue
        if "评标方法和评标标准" in line:
            return line
    return ""


def infer_procurement_requirement_summary(text: str) -> str:
    requirement_patterns = [
        r"采购需求[:：]\s*([^\n]+)",
        r"项目概况[:：]\s*([^\n]+)",
        r"项目概述[:：]\s*([^\n]+)",
        r"采购内容[:：]\s*([^\n]+)",
        r"服务内容[:：]\s*([^\n]+)",
    ]
    labeled = first_match(text, requirement_patterns, "")
    if labeled and len(labeled) <= 120:
        return labeled

    lines = [clean_value(line) for line in text.splitlines()]
    for index, line in enumerate(lines):
        if not line:
            continue
        if line in {"采购需求", "第四章 采购需求", "第五章 采购需求"}:
            for candidate in lines[index + 1 : index + 5]:
                if not candidate:
                    continue
                if any(keyword in candidate for keyword in ["评分", "供应商须知", "合同", "响应文件格式"]):
                    continue
                if len(candidate) > 120:
                    continue
                return candidate
        if "采购需求" in line and len(line) <= 120 and not line.startswith("第"):
            return line
    return ""


def infer_unit_type(text: str) -> str:
    if any(keyword in text for keyword in ["公共数据", "数据开放", "开放平台", "接口地址", "data.cq.gov.cn"]):
        return "政府数据接口/公共数据平台相关单位"
    if any(keyword in text for keyword in ["人民政府", "管理局", "委员会", "政府"]):
        return "政府部门"
    if any(keyword in text for keyword in ["医院", "学校", "研究院"]):
        return "事业单位"
    if "有限公司" in text or "公司" in text:
        return "企业"
    return "未注明"


def extract_contact_clues(text: str) -> str:
    clues: list[str] = []
    interface_url = first_match(text, [r"接口地址[:：]?\s*([^\s\n]+)"], "")
    if interface_url and "localhost" not in interface_url.lower():
        clues.append(f"接口地址：{interface_url}")

    support_format = first_match(text, [r"支持格式[:：]?\s*([^\n]+)"], "")
    if support_format:
        clues.append(f"支持格式：{support_format}")

    request_method = first_match(text, [r"请求方式[:：]?\s*([^\n]+)"], "")
    if request_method:
        clues.append(f"请求方式：{request_method}")

    interface_desc = first_match(text, [r"接口描述[:：]?\s*([^\n]+)", r"接口用途[:：]\s*([^\n]+)"], "")
    if interface_desc:
        clues.append(f"接口用途：{interface_desc}")

    return "；".join(clues)


def extract_labeled_list(text: str, patterns: list[str]) -> list[str]:
    raw = first_match(text, patterns, "")
    if not raw:
        return []
    parts = re.split(r"[；;、,，/]", raw)
    return [clean_value(part) for part in parts if clean_value(part)]


def infer_supplier_company_name(sample: SampleRecord, text: str) -> str:
    _partner_prefixes = ("合作方", "甲方", "乙方", "供应商", "客户", "委托方", "受托方")
    _placeholder_names = ("某公司", "某集团", "某企业", "某某公司", "XXX公司")

    def _is_valid_company(name: str) -> bool:
        if not name or len(name) > 30:
            return False
        if name in _placeholder_names:
            return False
        if any(name.startswith(p) for p in _partner_prefixes):
            return False
        return True

    title_hint = sample.title_hint or sample.subject_name_hint or ""
    title_company_match = re.search(
        r"([^\n]{0,30}(?:有限公司|股份有限公司|集团|公司))", title_hint,
    )
    if title_company_match:
        candidate = clean_value(title_company_match.group(1))
        candidate = re.sub(r"^(?:公司名称|企业名称)[:：]\s*", "", candidate)
        if _is_valid_company(candidate):
            return candidate

    source_base = Path(sample.source_path or "").stem if sample.source_path else ""
    source_company_match = re.search(
        r"([^\n]{0,30}(?:有限公司|股份有限公司|集团|公司))", source_base,
    )
    if source_company_match:
        candidate = clean_value(source_company_match.group(1))
        candidate = re.sub(r"^(?:公司名称|企业名称)[:：]\s*", "", candidate)
        if _is_valid_company(candidate):
            return candidate

    first_500_chars = text[:500] if text else ""
    cover_company_match = re.search(
        r"^\s*([^\n]{0,30}(?:有限公司|股份有限公司|集团))\s*$",
        first_500_chars, re.MULTILINE,
    )
    if cover_company_match:
        candidate = clean_value(cover_company_match.group(1))
        candidate = re.sub(r"^(?:公司名称|企业名称)[:：]\s*", "", candidate)
        if _is_valid_company(candidate):
            return candidate

    preferred_names = [
        first_match(text, [r"企业名称[:：]\s*([^\n]+)", r"公司名称[:：]\s*([^\n]+)"], ""),
        first_match(text, [r"^\s*([^\n]+集团)\s*$"], ""),
        first_match(text, [r"^\s*([^\n]+股份有限公司)\s*$", r"^\s*([^\n]+有限公司)\s*$"], ""),
        sample.unit_name_hint,
        sample.subject_name_hint,
    ]
    for name in preferred_names:
        cleaned = clean_value(name or "")
        cleaned = re.sub(r"^(?:公司名称|企业名称)[:：]\s*", "", cleaned)
        if _is_valid_company(cleaned):
            return cleaned
    return sample.unit_name_hint or sample.subject_name_hint or ""


def infer_supplier_business_direction(text: str) -> str:
    if "工业无人机系统生产商与服务商" in text:
        return "工业无人机系统生产与行业服务"
    if "专业从事无人机" in text and "企业集团" in text:
        return "工业级无人机研发制造与行业应用服务"
    if "解决方案提供商" in text:
        return "人工智能无人机解决方案"

    product_lines = extract_supplier_product_lines(text)
    if product_lines:
        return "；".join(product_lines)

    overview_match = re.search(r"公司概况\s*([\s\S]{0,120})", text)
    if not overview_match:
        return ""
    overview = clean_value(overview_match.group(1))
    return overview[:80]


def extract_supplier_product_lines(text: str) -> list[str]:
    ordered_lines = ["全域安防", "安全应急", "智能感知", "无人系统", "智慧交通", "低空防御"]
    matched = [item for item in ordered_lines if item in text]
    if len(matched) >= 3:
        return matched[:5]

    line_match = re.search(r"形成以\s*([^\n]{0,80})等五大产品线", text)
    if not line_match:
        return []

    raw_items = re.split(r"[、,，\s]+", line_match.group(1))
    product_lines: list[str] = []
    for item in raw_items:
        cleaned = clean_value(item)
        if cleaned and cleaned not in product_lines:
            product_lines.append(cleaned)
    return product_lines[:5]


def extract_supplier_key_products(text: str) -> list[str]:
    preferred_products = [
        "镧影R6000倾转旋翼飞行器",
        "TD550无人直升机",
        "TD220无人直升机",
        "Q100农业无人机",
        "镭影Q20无人机",
        "Q12多旋翼无人机",
        "Q3管道巡查无人机",
        "Q4仓库巡检无人机",
        "Q5隧道巡查无人机",
        "共轴带尾推高速无人直升机",
        "雷达探测设备 SC-R3000 | SC-R5000",
        "雷达探测设备 SC-R8000",
        "无人机探测定位一体设备 SC-P5000+",
        "频谱探测设备 SC-S3000",
        "频谱探测设备 SC-S3000+",
        "分布式侦测定位系统",
        "箱组式反无人机系统",
        "诱骗式主动防御系统",
        "便携式无人机管制设备",
        "车载式反无人机系统",
    ]
    products: list[str] = []
    for item in preferred_products:
        if item in text and item not in products:
            products.append(item)

    generic_matches = re.findall(
        r"^\s*([^\n]{1,40}(?:系统|设备|雷达|探测仪|一体设备)(?:\s+[A-Z][A-Z0-9+\-| ]{1,20})?)\s*$",
        text,
        re.MULTILINE,
    )
    for item in generic_matches:
        cleaned = clean_value(item)
        if cleaned and cleaned not in products and "产品展示" not in cleaned:
            products.append(cleaned)
    return products[:10]


def looks_like_markdown_table_header(value: str) -> bool:
    stripped = clean_value(value)
    if not stripped:
        return False
    if stripped.count("|") < 2:
        return False
    normalized = stripped.replace(" ", "")
    return normalized in {
        "|类别|参数项|参数值|",
        "|项目|参数|",
        "|序号|名称|型号|规格参数|",
        "|序号|产品名称|型号|备注|",
    }


def looks_like_product_table_noise(value: str) -> bool:
    stripped = clean_value(value)
    if not stripped:
        return True
    if looks_like_markdown_table_header(stripped):
        return True
    if stripped.count("|") >= 2 or stripped.startswith("# 工作表：") or stripped.startswith("---"):
        return True
    noise_keywords = ("序号", "名称", "产品名称", "项目", "型号", "规格", "参数", "参数项", "参数值", "单位", "数量", "备注", "工作表")
    if sum(1 for keyword in noise_keywords if keyword in stripped) >= 2:
        return True
    # 检查是否包含重量、尺寸等参数信息
    param_patterns = (
        r"\d+\.?\d*\s*(?:千克|kg|公斤|克|g)",
        r"\d+\.?\d*\s*(?:毫米|mm|厘米|cm|米|m)",
        r"\d+\.?\d*\s*(?:伏|V|安|A|毫安|mAh)",
        r"(?:配备|包含|不包含)",
        r"(?:空机重量|最大轴距|外形尺寸)",
    )
    if any(re.search(pattern, stripped) for pattern in param_patterns):
        return True
    return False


def infer_product_name(sample: SampleRecord, text: str) -> str:
    labeled_name = first_match(text, [r"产品名称[:：]\s*([^\n]+)"], "")
    if labeled_name and not looks_like_product_table_noise(labeled_name):
        return labeled_name
    if sample.product_name_hint and not looks_like_product_table_noise(sample.product_name_hint):
        return sample.product_name_hint
    # 从文件名中提取产品名称
    title = sample.title_hint or ""
    # 清理文件名中的常见后缀和无关词汇
    suffix_pattern = r"(?:参数|规格|说明书|手册|画册|简介|介绍|资料|文档)$"
    cleaned_title = re.sub(suffix_pattern, "", title).strip()
    cleaned_title = re.sub(r"[_\-]\s*$", "", cleaned_title).strip()
    # 从正文中提取产品名称（优先找包含产品关键词的行）
    product_keywords = ("无人机", "飞行器", "雷达", "相机", "传感器", "机库", "清洗机", "检测仪", "气象站")
    # 先在正文中找包含产品关键词的行
    for line in text.split("\n")[:20]:  # 只看前20行
        line = line.strip()
        if not line or len(line) > 50:
            continue
        if any(keyword in line for keyword in product_keywords):
            if not looks_like_product_table_noise(line):
                return line
    # 如果正文没找到，使用清理后的文件名
    if cleaned_title and not looks_like_product_table_noise(cleaned_title):
        return cleaned_title
    # 最后使用subject_name_hint
    return sample.subject_name_hint or ""


def infer_product_model(sample: SampleRecord, text: str) -> str:
    labeled_model = first_match(text, [r"型号[:：]\s*([^\n]+)"], "")
    if labeled_model and not looks_like_product_table_noise(labeled_model):
        return labeled_model
    hint_match = re.search(r"([A-Z]{1,4}-?[A-Z0-9]{1,8})", sample.product_name_hint or sample.title_hint)
    if hint_match:
        return hint_match.group(1)
    text_matches = re.findall(r"([A-Z]{1,4}-?[A-Z0-9]{1,8})", text)
    for candidate in text_matches:
        if looks_like_product_table_noise(candidate):
            continue
        if candidate.upper() in {"GPS", "GNSS", "RTK", "IMU", "CPU", "APP"}:
            continue
        if not re.search(r"\d", candidate):
            continue
        battery_pattern = r"\d+" + re.escape(candidate) + r"(?:毫安|mah|mAh|锂电池)"
        if re.search(r"\d{4,}", candidate) and re.search(battery_pattern, text, re.IGNORECASE):
            continue
        return candidate
    return ""


def infer_product_supplier(sample: SampleRecord, text: str) -> str:
    labeled_supplier = first_match(text, [r"供应商名称[:：]\s*([^\n]+)", r"生产单位[:：]\s*([^\n]+)"], "")
    if labeled_supplier:
        return labeled_supplier
    # 只匹配以中文开头的紧凑公司名（2-15字），避免混入英文前缀
    company = first_match(text, [r"(?:^|[^一-鿿])([一-鿿]{2,15}(?:有限公司|研究院|集团|公司))"], "")
    if company:
        return company
    return sample.unit_name_hint or sample.subject_name_hint


def infer_product_type(sample: SampleRecord, text: str) -> str:
    combined = " ".join([
        sample.title_hint,
        sample.product_name_hint,
        " ".join(sample.tags),
        " ".join(sample.notes),
        text,
    ])
    if "检测报告" in combined or ("报告" in (sample.title_hint or "") and sample.evidence_level == "L1"):
        return "检测报告"
    if "气象仪" in combined:
        return "气象设备"
    if "无人机" in combined:
        return "无人机设备"
    if "雷达" in combined:
        return "雷达设备"
    return "未注明"


def infer_product_usage(text: str) -> str:
    if "气象" in text:
        return "用于气象监测与环境数据采集"
    if "检测" in text:
        return "用于检测验证与性能证明"
    return first_match(text, [r"核心用途[:：]\s*([^\n]+)"], "")


def infer_product_params(text: str) -> str:
    params = re.findall(r"([^\n]{0,20}(?:续航|载荷|精度|量程|等级|风速|温度)[^\n]{0,20})", text)
    cleaned: list[str] = []
    for item in params:
        value = clean_value(item)
        if not value or value in cleaned:
            continue
        # 正则抓的是固定 20 字窗口，容易在半句处截断；末尾不是自然标点时补 "…" 提示后续被截断。
        if not value.endswith(("。", "；", "，", "、", ";", ",", ".", "℃", "%", ")", "）", "]", "】")):
            value = value + "…"
        cleaned.append(value)
    return "；".join(cleaned[:5])


def infer_product_scene(sample: SampleRecord, text: str) -> str:
    combined = " ".join([
        sample.title_hint,
        sample.product_name_hint,
        " ".join(sample.tags),
        " ".join(sample.notes),
        text,
    ])
    if "气象" in combined:
        return "气象监测"
    if "应急" in combined:
        return "应急保障"
    if "巡检" in combined:
        return "巡检作业"
    return "未提取"


def infer_product_relations(text: str) -> str:
    if "检测报告" in text:
        return "当前更适合作为产品检测证据层，后续需挂接产品主档"
    if any(keyword in text for keyword in ["挂载", "配件", "载荷"]):
        return "存在挂载/配件关系，建议后续拆出配件层"
    return "未提取"


def infer_product_evidence_type(sample: SampleRecord, text: str) -> str:
    combined = " ".join([
        sample.title_hint,
        sample.product_name_hint,
        " ".join(sample.tags),
        " ".join(sample.notes),
        text,
    ])
    if "检测报告" in combined or ("报告" in (sample.title_hint or "") and sample.evidence_level == "L1"):
        return "检测报告"
    if "参数" in combined:
        return "参数卡"
    return "说明书"


def infer_report_document_type(sample: SampleRecord, text: str) -> str:
    combined = " ".join([
        sample.title_hint,
        sample.product_name_hint,
        " ".join(sample.tags),
        text,
    ])
    if "校准报告" in combined or "校准" in combined:
        return "设备校准报告"
    if "检定报告" in combined or "检定" in combined:
        return "设备检定报告"
    if "检验报告" in combined or "检验" in combined:
        return "设备检验报告"
    if "检测报告" in combined or ("报告" in (sample.title_hint or "") and sample.evidence_level == "L1"):
        return "设备检测报告"
    return ""


def infer_product_serial_no(text: str) -> str:
    return first_match(
        text,
        [
            r"出厂编号[:：]\s*([^\n]+)",
            r"产品编号[:：]\s*([^\n]+)",
            r"序列号[:：]\s*([^\n]+)",
            r"Serial(?:\s+No\.?|\s+Number)?[:：]\s*([^\n]+)",
        ],
        "",
    )


def infer_test_basis(text: str) -> str:
    return first_match(
        text,
        [
            r"检定依据[:：]\s*([^\n]+)",
            r"校准依据[:：]\s*([^\n]+)",
            r"检测依据[:：]\s*([^\n]+)",
            r"依据标准[:：]\s*([^\n]+)",
            r"执行标准[:：]\s*([^\n]+)",
        ],
        "",
    )


def infer_test_result(text: str) -> str:
    labeled_result = first_match(
        text,
        [
            r"检定结果[:：]\s*([^\n]+)",
            r"校准结果[:：]\s*([^\n]+)",
            r"检测结论[:：]\s*([^\n]+)",
            r"检测结果[:：]\s*([^\n]+)",
        ],
        "",
    )
    if labeled_result:
        return labeled_result
    result_match = re.search(r"(合格|不合格|准用|停用)", text)
    return result_match.group(1) if result_match else ""


def infer_test_organization(text: str) -> str:
    return first_match(
        text,
        [
            r"检测机构[:：]\s*([^\n]+)",
            r"检验机构[:：]\s*([^\n]+)",
            r"检定机构[:：]\s*([^\n]+)",
            r"校准机构[:：]\s*([^\n]+)",
            r"检测单位[:：]\s*([^\n]+)",
        ],
        "",
    )


def infer_report_no(text: str) -> str:
    return first_match(
        text,
        [
            r"报告编号[:：]\s*([^\n]+)",
            r"证书编号[:：]\s*([^\n]+)",
            r"编号[:：]\s*([^\n]+)",
        ],
        "",
    )


def infer_report_date(text: str) -> str:
    raw_date = first_match(
        text,
        [
            r"报告日期[:：]\s*([^\n]+)",
            r"签发日期[:：]\s*([^\n]+)",
            r"日期[:：]\s*(20\d{2}[年./-]\d{1,2}[月./-]\d{1,2}日?)",
        ],
        "",
    )
    return normalize_report_date(raw_date)


def infer_expire_date(text: str) -> str:
    raw_date = first_match(
        text,
        [
            r"有效期至[:：]\s*([^\n]+)",
            r"有效期[:：]\s*([^\n]+)",
            r"下次检定日期[:：]\s*([^\n]+)",
        ],
        "",
    )
    return normalize_report_date(raw_date)


def normalize_report_date(value: str) -> str:
    cleaned = clean_value(value)
    if not cleaned:
        return ""
    match = re.search(r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})", cleaned)
    if match:
        year, month, day = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return cleaned


def is_tabular_solution_catalog(sample: SampleRecord, text: str) -> bool:
    normalized_text = text.lstrip()
    table_line_count = len(re.findall(r"^\|.*\|$", text, re.MULTILINE))
    if not normalized_text.startswith("# 工作表："):
        return False
    if (sample.source_path or "").lower().endswith((".xlsx", ".xls")):
        return table_line_count >= 2
    if sample.split_required and table_line_count >= 3:
        return True
    return any(tag in sample.tags for tag in ["场景分类", "项目机会", "官方场景清单"]) and table_line_count >= 3


def looks_like_table_noise(value: str) -> bool:
    stripped = value.strip()
    return stripped.count("|") >= 2 or stripped.startswith("# 工作表：") or stripped.startswith("| ---")


def looks_like_event_material(sample: SampleRecord, text: str) -> bool:
    combined_hints = " ".join([sample.title_hint, sample.subject_name_hint, text[:500]])
    return any(keyword in combined_hints for keyword in ["博览会", "展会", "会展", "峰会", "论坛", "研讨会", "对接会", "大会", "赛事"])


def looks_like_news_material(sample: SampleRecord, text: str) -> bool:
    title_hint = clean_value(sample.title_hint or sample.subject_name_hint)
    if not title_hint:
        return False
    if "：" not in title_hint and ":" not in title_hint:
        return False
    preview_text = text[:1200]
    return any(keyword in preview_text for keyword in ["告诉记者", "据了解", "来源：", "来源:", "记者", "初夏的清晨", "接下来"])


def looks_like_verbose_sentence(value: str) -> bool:
    cleaned = clean_value(value)
    if not cleaned:
        return False
    if len(cleaned) > 50:
        return True
    if cleaned.endswith(("。", "！", "？")):
        return True
    if cleaned.count("，") >= 1 and len(cleaned) > 35:
        return True
    return any(keyword in cleaned for keyword in ["告诉记者", "据了解", "目前，", "接下来", "初夏的清晨"])


def is_noisy_solution_customer_candidate(value: str) -> bool:
    # 方案正文里常混入公司介绍模块、基地介绍或动作句，不能误当成客户名称。
    cleaned = clean_value(value)
    if not cleaned or len(cleaned) > 40:
        return True
    if looks_like_verbose_sentence(cleaned):
        return True
    if re.search(r"^[A-Z]\d+", cleaned):
        return True
    if cleaned in {"公司总部", "总部", "公司介绍", "企业介绍", "公司简介", "客户名称", "客户/使用单位", "使用单位", "中试基地", "杭州基地", "指挥中心"}:
        return True
    if re.fullmatch(r".{1,4}(?:基地|中心)", cleaned):
        return True
    if cleaned.startswith(("并", "为", "向", "在", "对", "将", "把", "于")):
        return True
    noise_keywords = ("公司总部", "总部地址", "目录", "某方向", "示意", "公司介绍", "发展历程", "荣誉资质", "发现异常", "及时", "决策依据")
    return any(keyword in cleaned for keyword in noise_keywords)


def infer_solution_name(sample: SampleRecord, text: str) -> str:
    if looks_like_event_material(sample, text) or looks_like_news_material(sample, text):
        return ""
    if is_tabular_solution_catalog(sample, text):
        return sample.title_hint or sample.subject_name_hint
    meeting_keywords = ["说明会", "线上会", "分享会", "交流会", "路演", "主讲人", "请勿外传"]
    combined_hints = " ".join([sample.title_hint, sample.subject_name_hint, text[:300]])
    if any(keyword in combined_hints for keyword in meeting_keywords):
        return ""
    if any(keyword in combined_hints for keyword in ["调研", "考察", "汇报", "总结"]):
        return sample.title_hint or sample.subject_name_hint
    if "清单" in sample.title_hint or "清单" in (sample.subject_name_hint or ""):
        return sample.title_hint or sample.subject_name_hint
    labeled_name = first_match(text, [r"(?:项目名称|方案名称|案例名称)[:：]\s*([^\n]+)"], "")
    if labeled_name and len(labeled_name) >= 6 and not looks_like_table_noise(labeled_name) and not looks_like_verbose_sentence(labeled_name):
        return labeled_name
    first_line = first_match(text, [r"^\s*([^\n]*(?:方案|案例|清单)[^\n]*)"], "")
    if first_line and len(first_line) >= 6 and "附件" not in first_line and not looks_like_table_noise(first_line) and not looks_like_verbose_sentence(first_line):
        return first_line
    title_line = first_match(text, [r"(?:附件\s*\d+\s*)?(20\d{2}\s*年[^\n]*(?:方案|案例|清单))"], "")
    if title_line and not looks_like_table_noise(title_line) and not looks_like_verbose_sentence(title_line):
        return title_line
    source_title = clean_value(sample.title_hint or sample.subject_name_hint)
    if source_title and any(keyword in source_title for keyword in ["解决方案", "技术方案", "巡检方案", "标准方案"]):
        return source_title
    return ""


def infer_solution_scene(sample: SampleRecord, text: str) -> str:
    if looks_like_event_material(sample, text) or looks_like_news_material(sample, text):
        return ""
    if is_tabular_solution_catalog(sample, text):
        combined_hints = " ".join([sample.title_hint, sample.subject_name_hint, " ".join(sample.tags)])
        if any(keyword in combined_hints for keyword in ["应用场景", "场景分类", "官方场景清单"]):
            return "低空应用场景"
        if any(keyword in combined_hints for keyword in ["项目机会", "新建项目", "项目清单"]):
            return "低空项目机会"
        return "低空应用场景" if "低空" in text else ""
    combined_title_hints = " ".join([sample.title_hint, sample.subject_name_hint, " ".join(sample.tags)])
    if "低空" in combined_title_hints and any(keyword in combined_title_hints for keyword in ["应用场景机会清单", "场景机会清单", "机会清单", "项目机会"]):
        return "低空项目机会"
    if "应用场景清单" in sample.title_hint or "官方场景清单" in sample.tags or "场景分类" in sample.tags or (
        "低空" in combined_title_hints and any(keyword in combined_title_hints for keyword in ["应用场景能力清单", "场景能力清单", "能力清单", "应用场景清单"])
    ):
        return "低空应用场景"

    combined_hints = " ".join([sample.title_hint, sample.subject_name_hint, sample.unit_name_hint, text])
    medical_transport_phrases = (
        "医疗运输",
        "医疗转运",
        "检验转运",
        "检验低空转运",
        "血液配送",
        "血液运输",
        "医疗物资运输",
        "医疗物资的运输",
        "急救物流",
        "绿色生命通道",
    )
    medical_transport_pairs = (("检验", "转运"), ("血液", "配送"), ("医共体", "转运"))
    if sample.unit_name_hint and any(keyword in sample.unit_name_hint for keyword in ["医院", "卫生院", "医共体"]):
        return "医疗运输"
    if any(keyword in combined_hints for keyword in medical_transport_phrases):
        return "医疗运输"
    if any(left in combined_hints and right in combined_hints for left, right in medical_transport_pairs):
        return "医疗运输"
    if any(keyword in text for keyword in ["应急救援", "航空应急", "救援平台", "服务圈"]):
        return "应急救援"
    scene_hints = " ".join([sample.title_hint, sample.subject_name_hint, " ".join(sample.tags)])
    if "低空应用" in scene_hints or ("应用场景" in scene_hints and "低空" in combined_hints):
        return "低空应用场景"
    return first_match(text, [r"所属场景[:：]\s*([^\n]+)"], "")


def infer_solution_customer(sample: SampleRecord, text: str) -> str:
    combined_hints = " ".join([sample.title_hint, sample.subject_name_hint])
    if looks_like_event_material(sample, text) or looks_like_news_material(sample, text):
        return ""
    if any(keyword in combined_hints for keyword in ["说明会", "线上会", "分享会", "交流会", "路演"]):
        return ""
    labeled = first_match(text, [r"(?:客户/使用单位|客户名称|使用单位|项目单位|建设单位)[:：]\s*([^\n]+)"], "")
    if labeled and not is_noisy_solution_customer_candidate(labeled):
        return labeled
    if sample.unit_name_hint and not is_noisy_solution_customer_candidate(sample.unit_name_hint):
        return sample.unit_name_hint
    candidate = first_match(
        text,
        [r"([\u4e00-\u9fa5A-Za-z0-9]+(?:医院|卫生院|医共体|机场|基地|中心))"],
        "",
    )
    if candidate and not is_noisy_solution_customer_candidate(candidate):
        return candidate
    return ""


def infer_solution_file_date(sample: SampleRecord, text: str) -> str:
    if looks_like_event_material(sample, text) or looks_like_news_material(sample, text):
        return ""
    labeled_date = first_match(text, [r"文件日期[:：]\s*(20\d{2}\s*年(?:\d{1,2}\s*月)?(?:\d{1,2}\s*日)?)"], "")
    if labeled_date:
        return labeled_date
    title_year = re.search(r"(20\d{2})\s*年", sample.title_hint or "")
    if title_year:
        return f"{title_year.group(1)}年"
    year_matches = list(dict.fromkeys(re.findall(r"(20\d{2})\s*年", text)))
    if len(year_matches) == 1:
        return f"{year_matches[0]}年"
    return ""


def infer_solution_problem(text: str) -> str:
    if "不受地面环境制约" in text or "二次污染" in text:
        return "解决医疗物资地面运输慢、污染风险高、偏远地区覆盖不足的问题"
    if "应用场景清单" in text:
        return "用于梳理区域低空重点项目和应用场景，支撑场景拆分与机会识别"
    return first_match(text, [r"(?:解决的问题|解决问题|痛点问题)[:：]\s*([^\n]+)"], "")


def infer_solution_products(text: str) -> str:
    matches = re.findall(r"(无人机(?:管理调度云平台)?|自动化急救枢纽站|急救物流无人机|大型无人直升机救援平台|中型复合翼无人机救援平台)", text)
    deduped: list[str] = []
    for item in matches:
        if item not in deduped:
            deduped.append(item)
    return "；".join(deduped[:6])


def infer_solution_implementation(text: str) -> str:
    if "航线规划" in text and "禁飞区查询" in text:
        return "先做禁飞区查询与航线规划，再执行运输、换电与运行保障"
    if "重点项目和应用场景清单" in text:
        return "按项目清单逐条列示建设内容、投入规模和年度推进节点"
    return first_match(text, [r"实施方式[:：]\s*([^\n]+)"], "")


def infer_solution_budget(text: str) -> str:
    meeting_keywords = ("说明会", "线上会", "分享会", "交流会", "路演", "主讲人", "请勿外传")
    if any(keyword in text for keyword in meeting_keywords):
        return ""
    if "成本预算" in text or "报价" in text:
        return "含预算/报价内容，需与方案正文拆层处理"
    if re.search(r"总投资\s*\d+\s*亿元", text):
        return first_match(text, [r"(总投资\s*\d+\s*亿元)"], "")
    return ""


def infer_solution_effect(text: str) -> str:
    if "时效提升" in text:
        return "无人机运输相较地面运输具备明显时效提升"
    if "3 小时无人机服务圈" in text:
        return "目标打造 3 小时无人机服务圈，提升区域航空应急能力"
    return first_match(text, [r"(?:结果与效果数据|效果数据|效果说明)[:：]\s*([^\n]+)"], "")


def infer_solution_reuse(text: str) -> str:
    if "分级诊疗" in text:
        return "可复用于医疗检验转运、血液配送、基层医疗协同场景"
    if "应用场景清单" in text:
        return "可复用于区域项目机会清单、场景条目拆分和时间边界标注"
    return ""


def infer_solution_evidence_type(sample: SampleRecord, text: str) -> str:
    if "报价" in sample.title_hint or "成本预算" in text:
        return "混合型资料"
    if is_tabular_solution_catalog(sample, text):
        return "清单型资料"
    if "清单" in sample.title_hint or "清单" in (sample.subject_name_hint or ""):
        return "清单型资料"
    return "方案总纲"


# 教育培训模板优先按显式字段与常见教培关键词做规则抽取；信息不确定时保留空值，避免误写成正式事实。
def extract_education_training_fields(sample: SampleRecord, extraction: ExtractionResult) -> dict[str, Any]:
    text = extraction.extracted_text or ""
    return {
        "文件标题": infer_education_training_title(sample, text),
        "单位名称字段": infer_education_training_unit(sample, text),
        "培训主题字段": infer_education_training_topic(sample, text),
        "适用对象字段": infer_education_training_audience(text),
        "培训类型字段": infer_education_training_type(sample, text),
        "专业方向字段": infer_education_training_specialty(text),
        "课程体系字段": infer_education_training_courses(text),
        "实施方式字段": infer_education_training_delivery(text),
        "核心内容字段": infer_education_training_core_content(text),
    }


def infer_education_training_title(sample: SampleRecord, text: str) -> str:
    fallback_title = fallback_education_title(sample)
    labeled_title = first_match(
        text,
        [
            r"文件名称[:：]\s*《?([^\n》]+)》?",
            r"标题[:：]\s*([^\n]+)",
            r"文件标题[:：]\s*([^\n]+)",
        ],
        "",
    )
    cleaned_labeled_title = clean_education_title_candidate(labeled_title)
    if cleaned_labeled_title:
        return cleaned_labeled_title

    title_keywords = r"(?:教育培训|培训方案|课程体系|专业目录|职业教育|教培材料|人才培养|产教融合|专业建设|建设方案|研修班|培训班)"
    text_lines = text.splitlines()
    for index, line in enumerate(text_lines):
        candidate = clean_education_title_candidate(line)
        if not candidate:
            continue
        if not re.search(title_keywords, candidate):
            continue
        if (
            fallback_title
            and candidate in fallback_title
            and len(fallback_title) > len(candidate)
            and any(keyword in fallback_title for keyword in ["研修班", "培训班"])
        ):
            return fallback_title
        return candidate

    bracket_title = first_match(text, [r"《([^》]{1,40})》"], "")
    if clean_education_title_candidate(bracket_title):
        return clean_education_title_candidate(bracket_title)

    return fallback_title


def infer_education_training_unit(sample: SampleRecord, text: str) -> str:
    return first_match(
        text,
        [
            r"编制单位[:：]\s*([^\n]+)",
            r"培训单位[:：]\s*([^\n]+)",
            r"主办单位[:：]\s*([^\n]+)",
            r"申报单位[:：]\s*([^\n]+)",
            r"学校名称[:：]\s*([^\n]+)",
            r"院校名称[:：]\s*([^\n]+)",
            r"单位名称[:：]\s*([^\n]+)",
        ],
        sample.unit_name_hint or sample.subject_name_hint,
    )


def infer_education_training_topic(sample: SampleRecord, text: str) -> str:
    labeled = clean_education_title_candidate(
        first_match(text, [r"培训主题[:：]\s*([^\n]+)", r"主题[:：]\s*([^\n]+)"], "")
    )
    if labeled:
        return labeled

    title = infer_education_training_title(sample, text)
    if not title:
        return ""
    if any(keyword in title for keyword in ["研修班", "培训班"]):
        return title
    # 仅当标题完全来自样本兜底且正文中没有再次出现时，才禁止回填为培训主题。
    if title == fallback_education_title(sample):
        title_present_in_text = any(clean_education_title_candidate(line) == title for line in text.splitlines())
        if not title_present_in_text:
            return ""
    if any(keyword in title for keyword in ["人才培养模式", "建设方案", "课程体系解决方案", "专业建设"]):
        return ""

    topic = clean_value(re.sub(r"(?:职业教育|教育培训|培训方案|课程体系|教培材料|专业目录|人才培养|建设方案)", "", title))
    if topic in {"", "方向", "目录", "体系", "材料", "方案", "建设", "融合"}:
        return ""
    if any(keyword in topic for keyword in ["教育培训方向", "培训方向", "专业方向", "课程方向"]):
        return ""
    if re.fullmatch(r"20\d{2}(?:年)?(?:增补清单)?", topic):
        return ""
    if len(topic) <= 2 and any(keyword in (sample.subject_name_hint or "") for keyword in ["方向", "目录", "体系"]):
        return ""
    if len(topic) > 20:
        return ""
    return topic


def infer_education_training_audience(text: str) -> str:
    labeled = first_match(
        text,
        [
            r"适用对象[:：]\s*([^\n]+)",
            r"培训对象[:：]\s*([^\n]+)",
            r"招生对象[:：]\s*([^\n]+)",
            r"适用人群[:：]\s*([^\n]+)",
        ],
        "",
    )
    if labeled:
        return labeled

    block_heading_matches = (
        re.search(r"(?:^|\n)\s*#*\s*招生对象\s*\n+\s*([^\n#][^\n]*)", text),
        re.search(r"(?:^|\n)\s*#*\s*适用对象\s*\n+\s*([^\n#][^\n]*)", text),
        re.search(r"(?:^|\n)\s*#*\s*培训对象\s*\n+\s*([^\n#][^\n]*)", text),
    )
    collected_block_lines: list[str] = []
    for match in block_heading_matches:
        if not match:
            continue
        first_line = clean_value(match.group(1))
        if first_line and first_line not in collected_block_lines:
            collected_block_lines.append(first_line)
    if collected_block_lines:
        return "；".join(collected_block_lines[:3])

    service_match = re.search(r"服务全国([^\n]*院校)", text)
    if service_match:
        audience = clean_value(service_match.group(1))
        if audience:
            return audience

    audience_keywords = ("院校", "学生", "学员", "教师", "师资", "从业人员", "企业家", "相关产业人员")
    preferred_keywords = ("服务全国", "合作院校", "院校学生", "培训对象")
    fallback_candidates: list[str] = []
    for line in text.splitlines():
        cleaned = clean_value(line)
        if not cleaned or len(cleaned) > 60:
            continue
        if not any(keyword in cleaned for keyword in audience_keywords):
            continue
        if any(noise in cleaned for noise in ["课程", "体系", "内容", "案例", "公司介绍", "无人机专业建设", "培养模式", "解决方案", "高层次人才", "人才计划", "人才项目", "审核", "录取通知书"]):
            continue
        if any(keyword in cleaned for keyword in preferred_keywords):
            return cleaned
        fallback_candidates.append(cleaned)
    return fallback_candidates[0] if fallback_candidates else ""


def infer_education_training_type(sample: SampleRecord, text: str) -> str:
    combined = " ".join([sample.title_hint, sample.subject_name_hint, text])
    if any(keyword in combined for keyword in ["职业教育", "专业目录", "专业设置"]):
        return "职业教育"
    if any(keyword in combined for keyword in ["培训方案", "培养方案", "实施方案"]):
        return "培训方案"
    if any(keyword in combined for keyword in ["课程体系", "课程设置", "教学大纲"]):
        return "课程体系"
    if any(keyword in combined for keyword in ["教培材料", "培训教材", "课件"]):
        return "教培材料"
    if "教育培训" in combined or "培训" in combined:
        return "教育培训资料"
    return ""


def infer_education_training_specialty(text: str) -> str:
    bracket_specialty = first_match(text, [r"《([^》]{2,20}专业)》"], "")
    if bracket_specialty and not _is_noisy_education_training_specialty(bracket_specialty):
        return bracket_specialty

    labeled = first_match(
        text,
        [
            r"专业方向[:：]\s*([^\n]+)",
            r"专业名称[:：]\s*([^\n]+)",
            r"专业目录[:：]\s*([^\n]+)",
            r"方向设置[:：]\s*([^\n]+)",
        ],
        "",
    )
    if labeled and not _is_noisy_education_training_specialty(labeled):
        return labeled

    topic_labels = extract_education_training_topic_labels(text)
    if topic_labels:
        return "；".join(topic_labels[:4])
    deduped: list[str] = []
    fallback_generic = ""
    for line in text.splitlines():
        cleaned_line = clean_value(line)
        if not cleaned_line or "Module" in cleaned_line or "模块" in cleaned_line:
            continue
        matches = re.findall(r"([^；;，,、\s]{2,20}(?:专业|方向))", cleaned_line)
        for item in matches:
            cleaned = clean_value(item)
            if cleaned.startswith(("基于", "推动")):
                continue
            if not cleaned or _is_noisy_education_training_specialty(cleaned) or cleaned in deduped:
                continue
            if cleaned == "无人机专业":
                fallback_generic = cleaned
                continue
            deduped.append(cleaned)
    if deduped:
        return "；".join(deduped[:4])
    return fallback_generic




# 研修班/培训班标题优先剥离机构名与班型尾巴，只保留稳定主题词。
def normalize_education_training_topic_line(value: str) -> str:
    cleaned = clean_education_outline_line(value)
    cleaned = re.sub(
        r"(?:高级|专题|专修|定制)?(?:研修班|培训班|研讨班|训练营|课程班|招生简章|课程表)(?:[（(][^）)]*[）)])?$",
        "",
        cleaned,
    )
    cleaned = re.sub(r"^[\u4e00-\u9fff]{2,16}(?:大学|学院|研究院|研究所|公司)", "", cleaned)
    return clean_value(cleaned)


def normalize_education_training_topic_part(value: str) -> str:
    cleaned = clean_value(value)
    cleaned = re.sub(r"^[\u4e00-\u9fff]{2,16}(?:大学|学院|研究院|研究所|公司)", "", cleaned)
    cleaned = re.sub(r"(?:协同|高质量|创新|融合)?发展$", "", cleaned)
    return clean_value(cleaned)


def extract_education_training_topic_labels(text: str) -> list[str]:
    labels: list[str] = []
    stop_headings = {
        "课程涵盖",
        "课程安排",
        "招生对象",
        "课程时间",
        "发展路径",
        "产业生态",
        "机遇与挑战",
        "低空经济名企参访",
    }
    title_lines = [normalize_education_training_topic_line(line) for line in text.splitlines()[:8]]
    for line in title_lines:
        if not line or len(line) > 24:
            continue
        if line in stop_headings or is_generic_education_section_heading(line):
            continue
        if line.endswith(("大学", "学院", "研究院", "研究所", "公司")):
            continue
        normalized_line = re.sub(r"发展$", "", line)
        for part in re.split(r"[与和及]", normalized_line):
            cleaned_part = normalize_education_training_topic_part(part)
            if not cleaned_part:
                continue
            for candidate in re.findall(r"[\u4e00-\u9fff]{2,12}(?:经济|产业|航空|无人机|通航)", cleaned_part):
                cleaned = clean_value(candidate)
                if cleaned and cleaned not in labels:
                    labels.append(cleaned)
    return labels


def _is_noisy_education_training_specialty(value: str) -> bool:
    if not value:
        return True
    if len(value) > 20:
        return True
    if is_generic_education_section_heading(value):
        return True
    noise_keywords = ["序号", "专业大类", "专业类", "目录", "代码", "2025年", "2024年", "职业教育专业", "某方向", "联合实验室", "实训台", "平台"]
    if any(keyword in value for keyword in noise_keywords):
        return True
    if re.search(r"[0-9]{2,}", value):
        return True
    if any(sep in value for sep in ["；", ";", "，", ",", "、", "（", "(", "-", "——"]):
        return True
    return False


def clean_education_outline_line(value: str) -> str:
    cleaned = re.sub(r"^#+\s*", "", value or "")
    cleaned = re.sub(r"^[★●•·\-*lL]\s*", "", cleaned)
    return clean_value(cleaned)


def extract_training_coverage_items(text: str) -> list[str]:
    if "课程涵盖" not in text:
        return []
    section_lines = text.split("课程涵盖", 1)[1].splitlines()
    stop_headings = {"课程安排", "招生对象", "学习费用", "课程时间", "上课地点", "报名程序", "学习证书"}
    category_headings = {"发展路径", "产业生态", "机遇与挑战", "低空经济名企参访"}
    items: list[str] = []
    current_category = ""
    for raw_line in section_lines:
        line = clean_education_outline_line(raw_line)
        if not line:
            continue
        if line in stop_headings:
            break
        if line in category_headings:
            current_category = line
            continue
        if len(line) > 80 or line.startswith(("日期时间", "7月", "博士,")):
            continue
        value = f"{current_category}：{line}" if current_category else line
        if value not in items:
            items.append(value)
    return items


def extract_training_schedule_titles(text: str) -> list[str]:
    if "课程安排" not in text:
        return []
    schedule_text = text.split("课程安排", 1)[1]
    for stop_heading in ["# 招生对象", "\n招生对象", "# 学习费用", "\n学习费用", "# 课程时间", "\n课程时间"]:
        if stop_heading in schedule_text:
            schedule_text = schedule_text.split(stop_heading, 1)[0]
            break
    titles: list[str] = []
    for title in re.findall(r"《([^》]{3,60})》", schedule_text):
        cleaned = clean_education_outline_line(title)
        if not cleaned or cleaned in titles:
            continue
        if any(noise in cleaned for noise in ["报名表", "协议书", "结业证书", "指导意见", "专项规划"]):
            continue
        titles.append(cleaned)
    return titles[:10]


def infer_education_training_courses(text: str) -> str:
    labeled = first_match(
        text,
        [
            r"课程体系[:：]\s*([^\n]+)",
            r"课程设置[:：]\s*([^\n]+)",
            r"核心课程[:：]\s*([^\n]+)",
        ],
        "",
    )
    if labeled:
        return labeled

    coverage_items = extract_training_coverage_items(text)
    if coverage_items:
        return "；".join(coverage_items[:10])

    schedule_titles = extract_training_schedule_titles(text)
    if schedule_titles:
        return "；".join(schedule_titles[:10])

    precise_service_match = re.search(r"(整体解决方案可为客户提供(?:7大)?服务[:：][^\n]*?教学环境搭建。?)", text)
    if precise_service_match:
        return clean_value(precise_service_match.group(1))

    service_match = re.search(r"(整体解决方案[^\n]{0,80}(?:课程体系|师资培训|人才服务|资格认证服务|赛事服务|定制服务|教学环境搭建)[^\n]{0,40})", text)
    if service_match:
        service_line = clean_value(service_match.group(1))
        service_line = re.sub(r"(?:7大服务|7大)\s*$", "", service_line).strip()
        return service_line

    resource_match = re.search(r"(精品微课、实操视频、录屏课程、虚拟仿真[^\n]+)", text)
    if resource_match:
        return clean_value(resource_match.group(1))

    lines = re.findall(r"^\s*([一二三四五六七八九十0-9]+[、.．]\s*[^\n]{0,40}(?:课程|实训|教学模块)[^\n]{0,40})", text, re.MULTILINE)
    cleaned = []
    for item in lines:
        value = clean_value(item)
        if not value:
            continue
        if any(noise in value for noise in ["以后的课程", "课程打下", "学习目标", "质量目标", "能力目标"]):
            continue
        cleaned.append(value)
    if cleaned:
        return "；".join(cleaned[:6])

    course_keywords = ("课程体系", "课程", "实训", "教学大纲", "题库", "教材", "微课", "虚拟仿真")
    fallback_lines: list[str] = []
    for line in text.splitlines():
        cleaned_line = clean_value(line)
        if not cleaned_line or len(cleaned_line) > 180:
            continue
        if "Module" in cleaned_line or "模块" in cleaned_line:
            fragment_match = re.search(r"(课程[^\n；;，,]*(?:体系图|体系|设置|建设图|建设))", cleaned_line)
            if fragment_match:
                fragment = clean_value(fragment_match.group(1))
                if fragment and fragment not in fallback_lines:
                    fallback_lines.append(fragment)
            continue
        if not any(keyword in cleaned_line for keyword in course_keywords):
            continue
        if any(noise in cleaned_line for noise in ["公司介绍", "合作案例", "模块", "建设方案"]):
            continue
        if cleaned_line not in fallback_lines:
            fallback_lines.append(cleaned_line)
    return "；".join(fallback_lines[:4])


def infer_education_training_delivery(text: str) -> str:
    return first_match(
        text,
        [
            r"实施方式[:：]\s*([^\n]+)",
            r"培训方式[:：]\s*([^\n]+)",
            r"教学方式[:：]\s*([^\n]+)",
            r"组织方式[:：]\s*([^\n]+)",
        ],
        "",
    )


def infer_education_training_core_content(text: str) -> str:
    labeled = first_match(
        text,
        [
            r"核心内容[:：]\s*([^\n]+)",
            r"培训内容[:：]\s*([^\n]+)",
            r"教学内容[:：]\s*([^\n]+)",
            r"培养目标[:：]\s*([^\n]+)",
        ],
        "",
    )
    if labeled:
        return labeled

    schedule_titles = extract_training_schedule_titles(text)
    if schedule_titles:
        return "；".join(schedule_titles[:10])

    coverage_items = extract_training_coverage_items(text)
    if coverage_items:
        return "；".join(coverage_items[:10])

    preferred_lines = [
        "未来低空经济产业人才培养模式探索",
        "产教融合下无人机创新教育课程体系建设",
        "基于智能飞行器应用技术的创新型专业师资培训",
    ]
    collected_preferred = [line for line in preferred_lines if line in text]
    if collected_preferred:
        return "；".join(collected_preferred)

    content_lines = re.findall(r"^\s*([一二三四五六七八九十0-9]+[、.．]\s*[^\n]{0,40}(?:培训|课程|教学|实训|能力)[^\n]{0,40})", text, re.MULTILINE)
    cleaned = [clean_value(item) for item in content_lines if clean_value(item)]
    if cleaned:
        return "；".join(cleaned[:5])

    project_match = re.search(r"([0-9]+\.\s*产教项目\s*[0-9]+\.\s*师资培训)", text)
    if project_match:
        return clean_value(project_match.group(1))

    core_keywords = ("人才培养", "培养模式", "师资培训", "专业建设", "产教融合", "课程建设", "五金建设")
    preferred_keywords = ("探索", "建设", "融合", "培养模式")
    generic_core_lines = {"产教融合", "人才培养", "培养模式", "专业建设", "课程建设", "五金建设", "教育培训"}
    fallback_candidates: list[str] = []
    for line in text.splitlines():
        cleaned_line = clean_value(line)
        if not cleaned_line or len(cleaned_line) > 80:
            continue
        if cleaned_line in generic_core_lines:
            continue
        if not any(keyword in cleaned_line for keyword in core_keywords):
            continue
        if any(noise in cleaned_line for noise in ["公司介绍", "合作案例", "课程体系", "无人机专业建设", "人才培养方案", "技术交流研讨"]):
            continue
        if any(keyword in cleaned_line for keyword in preferred_keywords):
            return cleaned_line
        fallback_candidates.append(cleaned_line)
    return fallback_candidates[0] if fallback_candidates else ""


def infer_supplier_products(text: str) -> list[str]:
    products = extract_supplier_key_products(text)
    products.extend(
        re.findall(
            r"^\s*([A-Z]{1,5}[A-Z0-9-]{0,8}[^\n]{0,20}(?:无人机|遥测仪|测速仪|系留箱|探测仪|雷达))\s*$",
            text,
            re.MULTILINE,
        )
    )
    products.extend(
        re.findall(r"^\s*([^\n]{1,30}(?:智能机库|软件平台|探测设备|防御系统|探测系统|一体设备))\s*$", text, re.MULTILINE),
    )
    deduped: list[str] = []
    skip_values = {"雷达探测设备", "频谱探测设备", "产品展示"}
    for item in products:
        cleaned = clean_value(item)
        if not cleaned or cleaned in skip_values or "�" in cleaned:
            continue
        if cleaned not in deduped:
            deduped.append(cleaned)
    return deduped[:8]


def infer_supplier_capabilities(text: str) -> list[str]:
    capabilities: list[str] = []
    if any(keyword in text for keyword in ["研发生产基地", "整机装配", "生产商", "重点研制企业"]):
        capabilities.append("研发制造")
    if any(keyword in text for keyword in ["飞行测试场地", "飞行测试", "技术验证"]):
        capabilities.append("测试验证")
    platform_hits = sum(1 for kw in ["智能化管控平台", "AI 图像识别系统", "云平台", "人工智能", "多源感知融合"] if kw in text)
    if platform_hits >= 2:
        capabilities.append("平台与算法")
    if any(keyword in text for keyword in ["解决方案提供商", "定制化解决方案", "解决方案"]):
        capabilities.append("行业解决方案")
    if any(keyword in text for keyword in ["开放合作", "高校紧密合作", "产学研合作"]):
        capabilities.append("产学研合作")
    if any(keyword in text for keyword in ["雷达", "光电", "电子侦察", "导航诱骗", "低空防御"]):
        capabilities.append("智能感知与低空防御")
    return capabilities[:6]


def normalize_policy_date(value: str) -> str:
    cleaned = clean_value(value)
    if not cleaned:
        return ""
    match = re.search(r"(20\d{2})[年./-](\d{1,2})(?:[月./-](\d{1,2}))?", cleaned)
    if not match:
        return ""
    year, month, day = match.groups()
    month_int = int(month)
    if month_int < 1 or month_int > 12:
        return ""
    if day is None:
        return f"{year}-{month_int:02d}"
    day_int = int(day)
    if day_int < 1 or day_int > 31:
        return ""
    return f"{year}-{month_int:02d}-{day_int:02d}"



def infer_policy_status(text: str) -> str:
    if "征求意见" in text:
        return "征求意见稿"
    if "试行" in text:
        return "试行"
    if "自印发之日起施行" in text or "自发布之日起施行" in text:
        return "已生效"

    effective_date_match = re.search(r"自\s*(20\d{2}年\d{1,2}月\d{1,2}日)起施行", text)
    if effective_date_match:
        normalized = normalize_policy_date(effective_date_match.group(1))
        try:
            effective_date = datetime.strptime(normalized, "%Y-%m-%d").date()
            return "已生效" if effective_date <= date.today() else "未生效"
        except ValueError:
            return "已生效"

    if re.search(r"有效期至[^\n]+", text):
        return "已生效"
    return "未注明"


def extract_contract_fields(sample: SampleRecord, extraction: ExtractionResult) -> dict[str, Any]:
    text = extraction.extracted_text or ""
    return {
        "合同名称字段": infer_contract_name(sample, text),
        "合同编号字段": infer_contract_number(text),
        "合同类型字段": infer_contract_type(sample, text),
        "甲方字段": infer_contract_party_a(sample, text),
        "乙方字段": infer_contract_party_b(text),
        "合同金额字段": infer_contract_amount(text),
        "合同期限字段": infer_contract_period(text),
        "签订日期字段": infer_contract_date(text),
        "合同标的字段": infer_contract_subject(text),
        "履约状态字段": infer_contract_status(text),
    }


def infer_contract_name(sample: SampleRecord, text: str) -> str:
    labeled_name = first_match(
        text,
        [
            r"合同名称[:：]\s*([^\n]+)",
            r"协议名称[:：]\s*([^\n]+)",
        ],
        "",
    )
    if labeled_name:
        return labeled_name
    title = clean_value(sample.title_hint or sample.subject_name_hint)
    if any(keyword in title for keyword in ["合同", "协议", "购销"]):
        return title
    first_line = first_match(text, [r"^\s*([^\n]*(?:合同|协议)[^\n]*)"], "")
    if first_line and len(first_line) <= 60:
        return first_line
    return title


def infer_contract_number(text: str) -> str:
    return first_match(
        text,
        [
            r"合同编号[:：]\s*([^\n]{1,40})",
            r"协议编号[:：]\s*([^\n]{1,40})",
            r"编号[:：]\s*([^\n]{1,40})",
        ],
        "",
    )


def infer_contract_party_a(sample: SampleRecord, text: str) -> str:
    labeled = first_match(
        text,
        [
            r"甲方[:：]\s*([^\n]+)",
            r"需方[:：]\s*([^\n]+)",
            r"采购方[:：]\s*([^\n]+)",
            r"买方[:：]\s*([^\n]+)",
        ],
        "",
    )
    if labeled:
        return clean_value(labeled.split("（")[0].split("(")[0])
    return sample.unit_name_hint or ""


def infer_contract_party_b(text: str) -> str:
    labeled = first_match(
        text,
        [
            r"乙方[:：]\s*([^\n]+)",
            r"供方[:：]\s*([^\n]+)",
            r"供应方[:：]\s*([^\n]+)",
            r"卖方[:：]\s*([^\n]+)",
        ],
        "",
    )
    if labeled:
        return clean_value(labeled.split("（")[0].split("(")[0])
    return ""


def infer_contract_amount(text: str) -> str:
    return first_match(
        text,
        [
            r"合同金额[:：]\s*([^\n]+)",
            r"总金额[:：]\s*([^\n]+)",
            r"合同总价[:：]\s*([^\n]+)",
            r"金额[:：]\s*([^\n]*元[^\n]*)",
        ],
        "",
    )


def infer_contract_date(text: str) -> str:
    raw_date = first_match(
        text,
        [
            r"签订日期[:：]\s*([^\n]+)",
            r"签署日期[:：]\s*([^\n]+)",
            r"合同日期[:：]\s*([^\n]+)",
            r"日期[:：]\s*(20\d{2}年\d{1,2}月\d{1,2}日)",
        ],
        "",
    )
    return normalize_policy_date(raw_date)


def infer_contract_subject(text: str) -> str:
    labeled = first_match(
        text,
        [
            r"合同标的[:：]\s*([^\n]+)",
            r"标的物[:：]\s*([^\n]+)",
            r"采购内容[:：]\s*([^\n]+)",
        ],
        "",
    )
    if labeled:
        return labeled
    if "无人机" in text:
        return "无人机设备采购"
    return ""


def infer_contract_status(text: str) -> str:
    if any(keyword in text for keyword in ["已履行", "履行完毕", "验收合格"]):
        return "已履行"
    if any(keyword in text for keyword in ["履行中", "执行中", "在履行"]):
        return "履行中"
    if any(keyword in text for keyword in ["解除", "终止", "作废"]):
        return "已终止"
    return "未注明"


def infer_contract_type(sample: SampleRecord, text: str) -> str:
    title = sample.title_hint or sample.subject_name_hint or ""
    type_keywords = [
        (["采购合同", "购销合同", "设备采购"], "采购合同"),
        (["服务合同", "技术服务", "咨询服务"], "服务合同"),
        (["销售合同", "供货合同"], "销售合同"),
        (["框架协议", "战略合作"], "框架协议"),
        (["租赁合同", "租用"], "租赁合同"),
        (["承揽合同", "定作合同", "委托合同"], "承揽合同"),
        (["保密协议", "竞业协议"], "保密协议"),
        (["合作协议", "合作合同"], "合作协议"),
    ]
    for keywords, contract_type in type_keywords:
        if any(kw in title or kw in text[:2000] for kw in keywords):
            return contract_type
    return "合同"


def infer_contract_period(text: str) -> str:
    labeled = first_match(
        text,
        [
            r"合同期限[:：]\s*([^\n]{1,40})",
            r"履行期限[:：]\s*([^\n]{1,40})",
            r"服务期限[:：]\s*([^\n]{1,40})",
            r"有效期[:：]\s*(\d+\s*(?:年|月|天))",
        ],
        "",
    )
    if labeled:
        return clean_value(labeled)
    date_range = re.search(r"(20\d{2}年\d{1,2}月\d{1,2}日)\s*[至到\-—]+\s*(20\d{2}年\d{1,2}月\d{1,2}日)", text)
    if date_range:
        return f"{date_range.group(1)}至{date_range.group(2)}"
    return ""


def extract_price_quote_fields(sample: SampleRecord, extraction: ExtractionResult) -> dict[str, Any]:
    text = extraction.extracted_text or ""
    return {
        "报价单名称字段": infer_price_quote_name(sample, text),
        "报价主体字段": infer_price_quote_provider(sample, text),
        "产品型号价格字段": extract_price_quote_items(text),
        "有效期字段": infer_price_quote_validity(text),
        "报价日期字段": infer_price_quote_date(sample, text),
        "价格类型字段": infer_price_quote_type(text),
    }


def infer_price_quote_name(sample: SampleRecord, text: str) -> str:
    labeled = first_match(
        text,
        [
            r"报价单名称[:：]\s*([^\n]+)",
            r"价格表名称[:：]\s*([^\n]+)",
        ],
        "",
    )
    if labeled:
        return labeled
    title = clean_value(sample.title_hint or sample.subject_name_hint)
    if any(keyword in title for keyword in ["报价", "价格"]):
        return title
    return title


def infer_price_quote_provider(sample: SampleRecord, text: str) -> str:
    labeled = first_match(
        text,
        [
            r"报价单位[:：]\s*([^\n]+)",
            r"供应商[:：]\s*([^\n]+)",
            r"厂家[:：]\s*([^\n]+)",
        ],
        "",
    )
    if labeled:
        return labeled
    company = first_match(text, [r"([^\n]{0,30}(?:有限公司|公司))"], "")
    return company or sample.unit_name_hint or ""


def extract_price_quote_items(text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    patterns = [
        r"([A-Z]{1,4}-?[A-Z0-9]{1,8})\s*[:：]?\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:元|万元)?",
        r"([A-Z]{1,4}-?[A-Z0-9]{1,8})[^\n]*?(\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*元",
        r"([^\n]{2,20}(?:系统|设备|平台|无人机|雷达|充电|电池|遥控|云台|相机))\s*[:：]?\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*元",
    ]
    seen_models: set[str] = set()
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for model, price in matches:
            if model in seen_models:
                continue
            if model.upper() in {"GPS", "GNSS", "RTK", "IMU", "CPU", "APP"}:
                continue
            seen_models.add(model)
            items.append({"型号": clean_value(model), "价格": f"{price}元"})
    return items[:10]


def infer_price_quote_validity(text: str) -> str:
    labeled = first_match(
        text,
        [
            r"有效期[:：]\s*([^\n]+)",
            r"报价有效期[:：]\s*([^\n]+)",
        ],
        "",
    )
    if labeled:
        return labeled
    if "当天有效" in text:
        return "当天有效"
    if "一周内有效" in text or "7日内有效" in text:
        return "7日内有效"
    if "一个月内有效" in text or "30日内有效" in text:
        return "30日内有效"
    return ""


def infer_price_quote_date(sample: SampleRecord, text: str) -> str:
    raw_date = first_match(
        text,
        [
            r"报价日期[:：]\s*([^\n]+)",
            r"日期[:：]\s*(20\d{2}年\d{1,2}月\d{1,2}日)",
            r"(20\d{2}年\d{1,2}月\d{1,2}日)[^\n]*有效",
        ],
        "",
    )
    if raw_date:
        return normalize_policy_date(raw_date)
    year_match = re.search(r"(20\d{2})", sample.title_hint or "")
    if year_match:
        return year_match.group(1)
    return ""


def infer_price_quote_type(text: str) -> str:
    if any(keyword in text for keyword in ["零售", "零售价", "指导价"]):
        return "零售指导价"
    if any(keyword in text for keyword in ["经销商", "代理价", "批发价"]):
        return "经销商价格"
    if any(keyword in text for keyword in ["阶梯", "批量", "起订"]):
        return "阶梯价格"
    if any(keyword in text for keyword in ["项目报价", "工程报价"]):
        return "项目报价"
    return "报价单"


def extract_reference_fields(sample: SampleRecord, extraction: ExtractionResult) -> dict[str, Any]:
    text = extraction.extracted_text or ""
    return {
        "文档名称": clean_value(sample.title_hint or sample.subject_name_hint or ""),
        "编制主体": infer_reference_organization(sample, text),
        "发布时间": infer_reference_date(sample, text),
        "版本信息": infer_version_info(sample.title_hint, sample.source_path),
        "适用领域": infer_reference_domain(text),
        "核心观点": infer_reference_key_points(text),
    }


def infer_reference_organization(sample: SampleRecord, text: str) -> str:
    labeled = first_match(
        text,
        [
            r"编制单位[:：]\s*([^\n]{1,40})",
            r"发布单位[:：]\s*([^\n]{1,40})",
            r"主编单位[:：]\s*([^\n]{1,40})",
            r"起草单位[:：]\s*([^\n]{1,40})",
        ],
        "",
    )
    if labeled:
        return clean_value(labeled)
    return sample.unit_name_hint or ""


def infer_reference_date(sample: SampleRecord, text: str) -> str:
    raw_date = first_match(
        text,
        [
            r"发布日期[:：]\s*([^\n]+)",
            r"发布时间[:：]\s*([^\n]+)",
            r"(20\d{2}年\d{1,2}月)\s*发布",
        ],
        "",
    )
    if raw_date:
        return normalize_policy_date(raw_date)
    return ""


def infer_reference_domain(text: str) -> str:
    domains = []
    if any(kw in text for kw in ["低空", "无人机", "UAV", "eVTOL"]):
        domains.append("低空经济")
    if any(kw in text for kw in ["5G", "通信", "网络", "物联网"]):
        domains.append("通信与网络")
    if any(kw in text for kw in ["人工智能", "AI", "大模型"]):
        domains.append("人工智能")
    if any(kw in text for kw in ["交通", "出行", "道路"]):
        domains.append("智慧交通")
    if any(kw in text for kw in ["安全", "应急", "救援"]):
        domains.append("安全应急")
    return "、".join(domains) if domains else ""


def infer_reference_key_points(text: str) -> str:
    summary = first_match(
        text,
        [
            r"核心观点[:：]\s*([^\n]{1,200})",
            r"摘要[:：]\s*([^\n]{1,200})",
            r"概述[:：]\s*([^\n]{1,200})",
        ],
        "",
    )
    return clean_value(summary) if summary else ""


def infer_version_info(title: str, source_name: str) -> str:
    for text in (title or "", source_name or ""):
        match = re.search(r"[Vv](\d+(?:\.\d+)+)", text)
        if match:
            return f"V{match.group(1)}"
        match = re.search(r"第([一二三四五六七八九十\d]+版)", text)
        if match:
            return f"第{match.group(1)}"
    return ""


def extract_industry_knowledge_fields(sample: SampleRecord, extraction: ExtractionResult) -> dict[str, Any]:
    text = extraction.extracted_text or ""
    title = sample.title_hint or Path(sample.source_path).stem
    source_name = Path(sample.source_path).name

    industry_domain = first_match(
        text,
        [
            r"(?:行业|领域|产业)[:：]\s*([^\n]{2,60})",
            r"(?:聚焦|面向|围绕)\s*([^\n]{2,40}(?:行业|领域|产业))",
        ],
        "",
    )
    if not industry_domain:
        for keyword in ("低空经济", "无人机", "智慧交通", "新能源", "人工智能", "智能制造"):
            if keyword in text[:3000] or keyword in title:
                industry_domain = keyword
                break

    chain_links = first_match(
        text,
        [
            r"产业链(?:环节|结构|分布)?[:：]\s*([^\n]{2,200})",
            r"(?:上游|中游|下游)[^。\n]{0,100}(?:上游|中游|下游)[^。\n]{0,100}(?:上游|中游|下游)",
        ],
        "",
    )
    if not chain_links:
        segments = []
        for label in ("上游", "中游", "下游"):
            if label in text:
                segments.append(label)
        if len(segments) >= 2:
            chain_links = "、".join(segments)

    market_scale = first_match(
        text,
        [
            r"市场规模[^。\n]{0,80}(\d[\d,.]+\s*(?:亿元|万亿|亿美元|万亿元)[^。\n]{0,60})",
            r"(\d[\d,.]+\s*(?:亿元|万亿|亿美元|万亿元))[^。\n]{0,40}市场规模",
            r"规模(?:约|达|超|为|预计)[^。\n]{0,20}(\d[\d,.]+\s*(?:亿元|万亿|亿美元|万亿元))",
        ],
        "",
    )

    core_players = first_match(
        text,
        [
            r"(?:核心玩家|主要企业|龙头企业|代表企业|重点企业)[:：]\s*([^\n]{2,200})",
            r"(?:核心玩家|主要企业|龙头企业|代表企业|重点企业)[^。\n]{0,20}(?:包括|有|为)\s*([^\n]{2,200})",
        ],
        "",
    )

    trend = first_match(
        text,
        [
            r"(?:发展趋势|未来趋势|行业趋势)[:：]\s*([^\n]{2,200})",
            r"(?:发展趋势|未来趋势|行业趋势)[^。\n]{0,20}(?:包括|为|是)\s*([^\n]{2,200})",
        ],
        "",
    )

    return {
        "文件标题": clean_value(title),
        "行业领域字段": clean_value(industry_domain),
        "产业链环节字段": clean_value(chain_links),
        "市场规模字段": clean_value(market_scale),
        "核心玩家字段": clean_value(core_players),
        "发展趋势字段": clean_value(trend),
    }
