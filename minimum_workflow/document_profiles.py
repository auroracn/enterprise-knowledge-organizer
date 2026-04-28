from __future__ import annotations

import re
from pathlib import Path

# 文档判型与轻量文本辅助独立成模块，避免主流程继续直接依赖历史大脚本。
POLICY_TITLE_KEYWORDS = ("通知", "公告", "意见", "办法", "条例", "规定", "纲要", "规划", "公示", "标准", "规范", "规则", "细则", "措施")
REFERENCE_TITLE_KEYWORDS = ("参考架构", "白皮书", "蓝皮书", "研究报告", "发展报告", "指南", "指引", "参考模型")
SOLUTION_TITLE_KEYWORDS = ("案例", "实施", "应用")
STRONG_SOLUTION_TITLE_KEYWORDS = ("解决方案", "技术方案", "巡检方案", "标准方案", "示范基地方案", "总体规划", "投资计划")
STRONG_SOLUTION_CONTENT_KEYWORDS = (
    "应用案例", "技术方案", "整体架构", "巡检流程", "部署方式",
    "部署架构", "应用赋能", "场景应用", "落地案例", "建设思路",
    "建设目标", "建设内容", "运营方案", "总体架构",
)
RESEARCH_TITLE_KEYWORDS = ("调研", "考察", "总结")
INDUSTRY_KNOWLEDGE_TITLE_KEYWORDS = ("产业链", "产业图谱", "行业分析", "行业研究", "行业概览", "市场分析", "赛道分析", "产业分析", "产业生态", "行业全景")
INDUSTRY_KNOWLEDGE_CONTENT_KEYWORDS = (
    "产业链", "上游", "中游", "下游", "全产业链", "市场规模",
    "行业格局", "竞争格局", "产业图谱", "产业生态", "价值链",
    "行业趋势", "市场份额", "行业壁垒", "细分市场", "赛道",
    "产业集群", "供应链", "产业政策", "行业驱动力",
)
PRODUCT_TITLE_KEYWORDS = ("说明书", "手册", "检测报告", "检验报告", "参数", "规格", "技术指标")
SUPPLIER_TITLE_KEYWORDS = ("公司介绍", "企业介绍", "企业简介", "公司简介", "厂家介绍", "企业画册", "品牌介绍", "业务概况", "公司概况", "企业概况", "总体介绍", "总体概况")
SUPPLIER_CONTENT_KEYWORDS = (
    "公司简介", "企业简介", "发展历程", "荣誉资质", "创始人简介",
    "分支机构", "公司总部", "国内布局", "全球布局", "核心团队",
    "业务概况", "主营业务", "核心业务", "总体介绍", "总体概况",
)
CONTRACT_TITLE_KEYWORDS = ("合同", "协议", "购销", "采购合同", "销售合同", "服务合同", "合作协议", "框架协议")
CONTRACT_CONTENT_KEYWORDS = ("甲方", "乙方", "供方", "需方", "签订日期", "合同编号", "协议双方", "经协商一致", "双方共同遵守", "本合同", "本协议")
PRICE_QUOTE_TITLE_KEYWORDS = ("报价", "价格", "报价单", "价格表", "报价表", "产品报价", "设备报价")
PRICE_QUOTE_CONTENT_KEYWORDS = ("有效期", "当天有效", "零售指导价", "经销商价格", "阶梯价", "单价", "总价", "报价有效期")
ENTERPRISE_LIST_TITLE_KEYWORDS = ("企业清单", "企业名录", "企业榜单", "低空经济企业", "链上企业")
ENTERPRISE_LIST_CONTENT_KEYWORDS = ("整机制造企业", "低空物流企业", "应急救援企业", "运营服务企业", "安全设备企业", "链上企业")
EDUCATION_TRAINING_TITLE_KEYWORDS = (
    "教育培训", "培训方案", "课程体系", "专业目录", "职业教育",
    "教培", "培训材料", "教学大纲", "人才培养", "产教融合",
    "研修班", "培训班",
)
MEETING_MATERIAL_KEYWORDS = (
    "说明会",
    "线上会",
    "分享会",
    "交流会",
    "宣讲",
    "汇报",
    "路演",
    "主讲人",
    "请勿外传",
    "内部资料",
    "PPT",
)
EVENT_TITLE_KEYWORDS = ("博览会", "展览会", "展会", "会展", "无人机展", "峰会", "论坛", "研讨会", "对接会", "大会", "赛事")
PROCUREMENT_FILE_KEYWORDS = (
    "采购文件",
    "招标文件",
    "投标文件",
    "竞争性磋商文件",
    "询价文件",
    "采购公告",
    "供应商须知",
    "评标方法和评标标准",
    "采购需求",
    "合同主要条款",
    "响应文件格式",
    "采购人",
    "采购代理机构",
    "采购方式",
    "公开招标",
    "投标保证金",
    "投标供应商",
    "项目编号",
)
PRODUCT_ENTITY_KEYWORDS = ("无人机", "飞行器", "飞行摩托", "飞艇", "eVTOL", "机库", "载荷", "热气球")
PRODUCT_PARAM_KEYWORDS = ("飞机轴距", "机身长宽高", "最大起飞重量", "额定载重", "载重", "续航时间", "巡航速度", "航程", "电池", "飞行高度", "冗余设计", "数据备份")
LOW_ALTITUDE_CATALOG_TITLE_KEYWORDS = ("应用场景机会清单", "应用场景能力清单", "应用场景清单", "场景机会清单", "场景能力清单", "机会清单", "能力清单")
LOW_ALTITUDE_CATALOG_CONTENT_KEYWORDS = ("场景机会名称", "场景能力名称", "合作需求", "场景能力说明")
SOLUTION_CONTENT_KEYWORDS = ("实施计划", "落地步骤", "评估结论", "合作方向", "应用场景", "行动号召", "市场规模")
EDUCATION_TRAINING_CONTENT_KEYWORDS = (
    "培训目标", "培训对象", "课程体系", "专业目录", "教学内容",
    "教学计划", "实施方式", "培养目标", "职业教育", "培训课时",
    "培训对象", "课程设置", "专业教学", "课程建设", "教学资源",
    "产教融合", "师资培训", "专业建设", "五金建设",
)
EDUCATION_TRAINING_STRONG_CONTENT_KEYWORDS = (
    "职业教育", "专业目录", "培训对象", "课程体系", "教学内容",
    "课程设置", "专业教学", "课程建设", "产教融合", "师资培训",
)
CONTACT_TITLE_KEYWORDS = ("联系人", "通讯录", "名片", "电话", "邮箱")
ORGANIZATION_SUFFIXES = ("人民政府", "政府办公厅", "管理委员会", "委员会", "管理局", "部", "厅", "局", "中心", "联盟", "研究院", "大学", "集团", "公司")
DATE_PATTERN = re.compile(r"20\d{2}年(?:\d{1,2}月(?:\d{1,2}日)?)?")


def clean_paragraph_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = text.replace("\r", "").replace("\t", " ")
    text = re.sub(r"[ \u3000]+", " ", text)
    return text.strip()


def split_text_to_blocks(text: str) -> list[str]:
    if not text:
        return []
    normalized_text = text.replace("\r", "").strip()
    if not normalized_text:
        return []
    blocks: list[str] = []
    for block in re.split(r"\n\s*\n", normalized_text):
        stripped = block.strip()
        if not stripped:
            continue
        # 去掉纯 HTML 注释块（例如大文件拆分链路插入的 "<!-- 分片：xxx -->"），
        # 否则会被当成标题候选污染文件标题推断。
        if re.fullmatch(r"(?:\s*<!--.*?-->\s*)+", stripped, flags=re.DOTALL):
            continue
        blocks.append(stripped)
    return blocks


def strip_markdown_heading(text: str) -> str:
    if not text:
        return ""
    return clean_paragraph_text(re.sub(r"^#+\s*", "", text))


def count_keyword_hits(text: str, keywords: tuple[str, ...]) -> int:
    if not text:
        return 0
    return sum(1 for keyword in keywords if keyword and keyword in text)


def count_title_and_filename_hits(title: str, filename: str, keywords: tuple[str, ...]) -> int:
    return count_keyword_hits(title, keywords) + count_keyword_hits(filename, keywords)


def _build_profile_dict(category: str, template: str, level: str,
                        org_field: str, org_name: str, date: str,
                        version: str, evidence: str, dify_ok: str,
                        title: str) -> dict[str, str]:
    return {
        "文档分类": category, "模板归属": template, "资料层级": level,
        "主体字段名": org_field, "主体名称": org_name, "发布时间": date,
        "版本信息": version, "证据边界": evidence,
        "是否适合直接入Dify": dify_ok, "文件标题": title,
    }


def infer_document_title(blocks: list[str], source_name: str) -> str:
    if not blocks:
        blocks = []
    if not source_name:
        return "未知标题"
    title_keywords = (
        POLICY_TITLE_KEYWORDS
        + REFERENCE_TITLE_KEYWORDS
        + SOLUTION_TITLE_KEYWORDS
        + RESEARCH_TITLE_KEYWORDS
        + PRODUCT_TITLE_KEYWORDS
        + EDUCATION_TRAINING_TITLE_KEYWORDS
        + CONTACT_TITLE_KEYWORDS
    )
    generic_section_titles = {
        "建设方向",
        "课程建设",
        "课程建设体系图",
        "教学资源开发流程",
        "资源开发流程",
        "部分建设案例",
        "公司介绍",
        "合作案例",
        "行业应用介绍",
        "产品介绍",
        "项目案例",
    }
    explicit_title_patterns = (
        re.compile(r"^(?:文件名称|文件名|标题|正式标题)[:：]\s*[《\"]?(.+?)[》\"]?$"),
        re.compile(r"^(?:文件名称|文件名|标题|正式标题)\s+[《\"]?(.+?)[》\"]?$"),
    )

    def normalize_event_title(line: str) -> str:
        cleaned = clean_paragraph_text(line.strip("《》\"“”"))
        cleaned = re.sub(
            r"[（(]\s*20\d{2}(?:年|[./-])\d{1,2}(?:月|[./-])\d{1,2}(?:日)?(?:\s*[-–—至]\s*\d{1,2}(?:日)?)?\s*[)）]$",
            "",
            cleaned,
        )
        return clean_paragraph_text(cleaned.strip())

    def is_title_candidate(line: str) -> bool:
        if not line or len(line) > 60:
            return False
        if re.fullmatch(r"\d+(?:\.\d+)*", line):
            return False
        if line in {"目录", "编委会", "核心编制单位", "参与编制单位（按拼音排序）", "会展赛事"}:
            return False
        if line in generic_section_titles:
            return False
        if re.fullmatch(r"[一二三四五六七八九十]+[、.]\s*.+", line):
            return False
        if re.fullmatch(r"\d+[.、]\s*.+", line):
            return False
        if re.fullmatch(r"第[一二三四五六七八九十百零〇]+[章节部分编]\s*.+", line):
            return False
        if re.fullmatch(r"模块[一二三四五六七八九十0-9]+(?:\s+Module\s*\d+)?\s*.*", line, re.IGNORECASE):
            return False
        if re.fullmatch(r"(?:Module|Part)\s*[A-Z0-9一二三四五六七八九十]+\s*.*", line, re.IGNORECASE):
            return False
        procurement_chapter_pattern = (
            r"第[一二三四五六七八九十百零〇]+章\s*"
            r"(?:采购公告|供应商须知|评标方法和评标标准|采购需求"
            r"|合同主要条款(?:（参考）)?|响应文件格式)"
            r"(?:\s*[.．·…]{2,}\s*\d+|\s+\d+)?"
        )
        if re.fullmatch(procurement_chapter_pattern, line):
            return False
        if line.count("|") >= 2 or line.startswith("# 工作表：") or line.startswith("| ---"):
            return False
        if re.search(r"[。！？]$", line):
            return False
        if len(line) > 35 and line.count("，") >= 1:
            return False
        if any(marker in line for marker in ("告诉记者", "据了解", "近年来", "目前，", "接下来")):
            return False
        event_meta_prefixes = (
            "主讲人", "分享嘉宾", "汇报人", "联系人", "电话", "邮箱", "微信",
            "日期", "时间", "地点", "议程", "主题", "展览场馆", "展会名称",
            "所属地区", "所属行业", "日期范围", "主办单位", "承办单位",
            "协办单位", "支持单位", "联合主办", "联合承办单位", "联合承办",
            "联办单位", "联办", "媒体支持", "举办地点", "展馆地址",
        )
        if re.match(r"^(?:" + "|".join(event_meta_prefixes) + r")[:：]", line):
            return False
        return True

    generic_meeting_titles = {"说明会", "线上说明会", "分享会", "交流会", "宣讲会", "汇报", "路演", "内部资料", "PPT"}
    education_training_priority_title_keywords = ("人才培养", "培养模式", "课程体系", "产教融合", "专业建设", "岗课赛证", "专业目录", "培训方案")
    supplier_cover_signal_keywords = SUPPLIER_TITLE_KEYWORDS + ("COMPANY PROFILE", "Company Introduction")
    company_cover_candidate = ""
    source_base_name = Path(source_name).stem[:200]
    cleaned_source_title = clean_paragraph_text(re.sub(r"20\d{2}(?:[-/.年]\d{1,2}){0,2}日?", "", source_base_name).strip(" _-"))
    meeting_title_candidate = ""
    education_cover_candidates: list[str] = []

    if any(keyword in source_base_name for keyword in EVENT_TITLE_KEYWORDS):
        return normalize_event_title(source_base_name)

    for block in blocks[:12]:
        for raw_line in block.splitlines():
            line = strip_markdown_heading(raw_line)
            for pattern in explicit_title_patterns:
                match = pattern.match(line)
                if match:
                    explicit_title = clean_paragraph_text(match.group(1).strip("《》\"“”"))
                    if explicit_title:
                        return explicit_title
            if not company_cover_candidate and re.fullmatch(r"[^\n]{2,40}(?:股份有限公司|有限公司|集团有限公司|集团)", line):
                company_cover_candidate = line
            if not is_title_candidate(line):
                continue
            if len(education_cover_candidates) < 6 and len(line) <= 30:
                education_cover_candidates.append(line)
            if any(keyword in line for keyword in EVENT_TITLE_KEYWORDS) and len(line) >= 8:
                return normalize_event_title(line)
            if any(keyword in line for keyword in education_training_priority_title_keywords):
                return line
            if (any(keyword in line for keyword in MEETING_MATERIAL_KEYWORDS)
                    and line not in generic_meeting_titles
                    and not meeting_title_candidate):
                meeting_title_candidate = line

    early_text = "\n".join(blocks[:6])
    if company_cover_candidate and any(keyword in early_text for keyword in supplier_cover_signal_keywords):
        return company_cover_candidate

    # 当文件名包含供应商类关键词时，优先使用文件名作为标题（但封面公司名已优先返回）
    if any(keyword in source_base_name for keyword in SUPPLIER_TITLE_KEYWORDS):
        return cleaned_source_title or source_base_name

    # 当文件名包含合同类关键词时，优先使用文件名作为标题
    if any(keyword in source_base_name for keyword in CONTRACT_TITLE_KEYWORDS):
        return cleaned_source_title or source_base_name

    # 当文件名包含报价类关键词时，优先使用文件名作为标题
    if any(keyword in source_base_name for keyword in PRICE_QUOTE_TITLE_KEYWORDS):
        return cleaned_source_title or source_base_name

    has_split_education_cover = (
        any(line.endswith(("大学", "学院")) for line in education_cover_candidates)
        and any(
            any(keyword in line for keyword in ("研修班", "培训班", "课程体系", "人才培养", "专业建设"))
            for line in education_cover_candidates
        )
    )
    if has_split_education_cover and any(keyword in source_base_name for keyword in EDUCATION_TRAINING_TITLE_KEYWORDS):
        return cleaned_source_title or source_base_name

    if meeting_title_candidate:
        return meeting_title_candidate

    title_match = re.search(r"《([^》]+)》", source_name)
    if title_match:
        quoted_source_title = clean_paragraph_text(title_match.group(1))
        if quoted_source_title and any(keyword in quoted_source_title for keyword in REFERENCE_TITLE_KEYWORDS):
            return quoted_source_title

    for block in blocks[:20]:
        for raw_line in block.splitlines():
            line = strip_markdown_heading(raw_line)
            if not is_title_candidate(line):
                continue
            if any(keyword in line for keyword in title_keywords):
                return line

    if title_match:
        return clean_paragraph_text(title_match.group(1))

    if any(keyword in source_base_name for keyword in EVENT_TITLE_KEYWORDS):
        return normalize_event_title(source_base_name)
    return cleaned_source_title or source_base_name


def normalize_organization_candidate(line: str) -> str:
    match = re.match(
        r"^(?:采购人|采购单位|招标人|采购代理机构|招标代理机构|发文单位|发布单位|编制单位|牵头单位)[:：]\s*(.+)$",
        line,
    )
    if match:
        return clean_paragraph_text(match.group(1))
    return line


def infer_primary_organization(blocks: list[str], title: str) -> str:
    if not blocks:
        blocks = []
    if not title:
        title = ""
    is_event_like_title = any(keyword in title for keyword in EVENT_TITLE_KEYWORDS)
    for block in blocks[:20]:
        for raw_line in block.splitlines():
            line = strip_markdown_heading(raw_line)
            normalized_line = normalize_organization_candidate(line)
            if not normalized_line or normalized_line == title or len(normalized_line) > 40:
                continue
            if DATE_PATTERN.search(normalized_line) or re.search(r"20\d{2}[-/.]\d{1,2}(?:[-/.]\d{1,2})?", normalized_line):
                continue
            if re.match(r"^(?:时间|地点|日期|议程)[:：]", normalized_line):
                continue
            if re.match(r"^(?:来源|前一个|后一个)[:：]", line):
                continue
            if is_event_like_title and re.match(
                r"^(?:主办单位|承办单位|协办单位|支持单位|联合主办"
                r"|联合承办单位|联合承办|联办单位|联办|媒体支持"
                r"|展览场馆|展会名称|所属地区|所属行业|日期范围"
                r"|举办地点|展馆地址)[:：]", line,
            ):
                continue
            if line in {"目录", "编委会", "主任", "副主任", "核心编制单位", "参与编制单位（按拼音排序）"}:
                continue
            if line.startswith(("一、", "二、", "三、", "四、", "五、", "（一）", "（二）", "（三）")):
                continue
            if re.match(r"^(?:项目编号|采购方式|招标方式|预算金额|采购预算|最高限价|最高投标限价)[:：]", line):
                continue
            if normalized_line.endswith(ORGANIZATION_SUFFIXES):
                return normalized_line
    return ""


def infer_document_date(blocks: list[str], source_name: str) -> str:
    if not blocks:
        blocks = []
    if not source_name:
        source_name = ""
    for block in blocks[:20]:
        for raw_line in block.splitlines():
            line = strip_markdown_heading(raw_line)
            if re.search(r"20\d{2}\s*[-–—/]\s*20\d{2}年", line):
                continue
            date_match = DATE_PATTERN.search(line)
            if date_match:
                candidate = clean_paragraph_text(date_match.group(0))
                if candidate.endswith("年") and "月" not in candidate and len(line) > len(candidate) + 6:
                    continue
                return candidate
            raw_date_match = re.search(r"20\d{2}[-/.]\d{1,2}(?:[-/.]\d{1,2})?", line)
            if raw_date_match:
                year, month, *rest = re.split(r"[-/.]", raw_date_match.group(0))
                if rest:
                    return f"{year}年{int(month)}月{int(rest[0])}日"
                return f"{year}年{int(month)}月"

    source_date_match = re.search(r"20\d{2}[-/.]\d{1,2}(?:[-/.]\d{1,2})?", source_name)
    if source_date_match:
        year, month, *rest = re.split(r"[-/.]", source_date_match.group(0))
        if rest:
            return f"{year}年{int(month)}月{int(rest[0])}日"
        return f"{year}年{int(month)}月"
    return ""


def infer_document_version(title: str, source_name: str) -> str:
    for text in (title or "", source_name or ""):
        version_match = re.search(r"(\d{4}版|V\d+(?:\.\d+)*)", text, re.IGNORECASE)
        if version_match:
            return version_match.group(1)
    return ""


# 文档判型只返回稳定字段，供 pipeline、目录 OCR、历史脚本共同复用。
def infer_document_profile(source_name: str, blocks: list[str]) -> dict[str, str]:
    if not blocks:
        blocks = []
    if not source_name:
        source_name = "未知文件"
    source_path = Path(source_name)
    source_base_name = source_path.stem[:200]
    source_suffix = source_path.suffix.lower()
    title = infer_document_title(blocks, source_name)
    organization = infer_primary_organization(blocks, title)
    document_date = infer_document_date(blocks, source_name)
    version = infer_document_version(title, source_name)
    combined_text = "\n".join(b for b in blocks[:80] if b)
    combined_for_title = "\n".join([source_base_name, title, combined_text])
    product_entity_hits = count_title_and_filename_hits(title, combined_text, PRODUCT_ENTITY_KEYWORDS)
    product_param_hits = count_keyword_hits(combined_text, PRODUCT_PARAM_KEYWORDS)
    enterprise_list_title_hits = count_title_and_filename_hits(title, source_base_name, ENTERPRISE_LIST_TITLE_KEYWORDS)
    enterprise_list_content_hits = count_keyword_hits(combined_text, ENTERPRISE_LIST_CONTENT_KEYWORDS)
    low_altitude_catalog_title_hits = count_title_and_filename_hits(title, source_base_name, LOW_ALTITUDE_CATALOG_TITLE_KEYWORDS)
    low_altitude_catalog_content_hits = count_keyword_hits(combined_text, LOW_ALTITUDE_CATALOG_CONTENT_KEYWORDS)
    solution_content_hits = count_keyword_hits(combined_text, SOLUTION_CONTENT_KEYWORDS)
    strong_solution_title_hits = count_title_and_filename_hits(title, source_base_name, STRONG_SOLUTION_TITLE_KEYWORDS)
    strong_solution_content_hits = count_keyword_hits(combined_text, STRONG_SOLUTION_CONTENT_KEYWORDS)
    supplier_title_hits = count_title_and_filename_hits(title, source_base_name, SUPPLIER_TITLE_KEYWORDS)
    supplier_content_hits = count_keyword_hits(combined_text, SUPPLIER_CONTENT_KEYWORDS)
    industry_knowledge_title_hits = count_title_and_filename_hits(title, source_base_name, INDUSTRY_KNOWLEDGE_TITLE_KEYWORDS)
    industry_knowledge_content_hits = count_keyword_hits(combined_text, INDUSTRY_KNOWLEDGE_CONTENT_KEYWORDS)
    education_training_title_hits = count_title_and_filename_hits(title, source_base_name, EDUCATION_TRAINING_TITLE_KEYWORDS)
    education_training_content_hits = count_keyword_hits(combined_text, EDUCATION_TRAINING_CONTENT_KEYWORDS)
    education_training_strong_content_hits = count_keyword_hits(combined_text, EDUCATION_TRAINING_STRONG_CONTENT_KEYWORDS)
    training_enrollment_keywords = ("招生对象", "学习费用", "课程时间", "报名程序", "结业证书", "研修班")
    training_enrollment_hits = sum(1 for keyword in training_enrollment_keywords if keyword in combined_for_title)
    meeting_material_hits = count_keyword_hits(title, MEETING_MATERIAL_KEYWORDS) + count_keyword_hits(combined_text, MEETING_MATERIAL_KEYWORDS)
    event_title_hits = count_keyword_hits(title, EVENT_TITLE_KEYWORDS)
    event_content_hits = count_keyword_hits(combined_text, EVENT_TITLE_KEYWORDS)
    is_event_like_title = event_title_hits >= 1
    has_markdown_table = "|" in combined_text and "---" in combined_text
    is_research_like = any(keyword in title for keyword in RESEARCH_TITLE_KEYWORDS)
    procurement_keyword_hits = (
        count_keyword_hits(title, PROCUREMENT_FILE_KEYWORDS)
        + count_keyword_hits(combined_text, PROCUREMENT_FILE_KEYWORDS)
    )
    procurement_title_strong = (
        "采购文件", "招标文件", "投标文件", "竞争性磋商文件",
        "询价文件", "标段", "采购公告", "招标公告", "中标公告", "成交公告",
    )
    procurement_filename_strong = (
        "采购文件", "招标文件", "投标文件", "标段", "采购公告", "招标公告",
    )
    procurement_table_keywords = (
        "评分标准", "评分项目", "投标供应商", "项目概况描述", "服务范围、内容",
        "防治专项方案", "服务质量保证措施", "商务部分", "报价部分",
    )
    is_procurement_file = (
        procurement_keyword_hits >= 3
        or any(keyword in title for keyword in procurement_title_strong)
        or any(keyword in source_base_name for keyword in procurement_filename_strong)
        or (has_markdown_table and count_keyword_hits(combined_text, procurement_table_keywords) >= 2)
    )
    policy_title_hits = count_keyword_hits(title, POLICY_TITLE_KEYWORDS)
    policy_content_hits = count_keyword_hits(combined_text, POLICY_TITLE_KEYWORDS)
    has_policy_cover_signals = bool(
        re.search(r"^(?:文件名称|文件名|标题|正式标题)[:：]", combined_text, re.MULTILINE)
        or re.search(r"^(?:发文字号|发文单位|成文日期)[:：]", combined_text, re.MULTILINE)
    )
    has_event_schedule_signals = bool(
        re.search(r"(?:时间|日期)\s*[:：][^\n]{0,40}(?:地点|地址)\s*[:：]", combined_text)
        or re.search(r"(?:地点|地址)\s*[:：][^\n]{0,40}(?:时间|日期)\s*[:：]", combined_text)
    )
    has_event_context_signals = any(keyword in combined_text for keyword in ("展会背景", "同期活动", "展品范围", "精准观众邀请", "会展中心", "论坛数量", "展览面积"))
    has_event_priority_signals = (
        event_title_hits >= 1
        and policy_title_hits == 0
        and (has_event_schedule_signals or has_event_context_signals or event_content_hits >= 2)
    )
    has_mixed_policy_meeting_signals = meeting_material_hits >= 2 and (policy_title_hits >= 1 or policy_content_hits >= 1)
    has_supplier_filename_signals = any(keyword in source_base_name for keyword in SUPPLIER_TITLE_KEYWORDS)
    has_supplier_priority_signals = supplier_title_hits >= 1 or supplier_content_hits >= 3 or has_supplier_filename_signals
    solution_article_keywords = (
        "系统架构", "技术路线", "落地实践", "监测预警系统", "核心能力", "感知层", "算法层", "应用层",
    )
    has_solution_priority_signals = (
        strong_solution_title_hits >= 1
        or strong_solution_content_hits >= 3
        or count_keyword_hits(combined_text, solution_article_keywords) >= 3
    )
    has_solution_catalog_priority_signals = (
        (
            any(keyword in " ".join([source_base_name, title]) for keyword in ("项目清单", "案例清单", "项目案例清单"))
            or (
                has_markdown_table
                and "项目名称" in combined_text
                and any(keyword in combined_text for keyword in ("应用场景", "项目简介", "案例简介", "项目概况"))
            )
        )
        and (has_markdown_table or solution_content_hits >= 1 or strong_solution_content_hits >= 1)
    )
    has_low_altitude_catalog_priority_signals = (
        "低空" in " ".join([source_base_name, title, combined_text])
        and low_altitude_catalog_title_hits >= 1
        and (low_altitude_catalog_content_hits >= 1 or "清单" in title or "清单" in source_base_name)
    )
    has_policy_priority_signals = (
        (has_policy_cover_signals or policy_title_hits >= 2 or (policy_title_hits >= 1 and policy_content_hits >= 2))
        and not is_procurement_file
        and not has_event_priority_signals
        and not has_supplier_priority_signals
        and not has_solution_priority_signals
        and education_training_title_hits == 0
    )

    if any(keyword in title for keyword in REFERENCE_TITLE_KEYWORDS):
        return _build_profile_dict(
            "行业参考架构/指导材料",
            "参考架构/白皮书口径（当前按原文全量提取Markdown输出）",
            "行业参考材料", "编制主体", organization,
            document_date, version,
            "行业参考架构/白皮书类材料，非正式政策文件；发布口径、适用效力与正式出处仍需结合原始发布来源复核。",
            "待审核", title,
        )

    has_industry_knowledge_signals = (
        industry_knowledge_title_hits >= 1
        or (industry_knowledge_content_hits >= 3 and not has_supplier_priority_signals)
    )
    if has_industry_knowledge_signals and not is_procurement_file and education_training_title_hits == 0:
        return _build_profile_dict(
            "行业产业链分析资料", "行业知识模板", "行业知识资料",
            "编制主体", organization, document_date, version,
            "行业/产业链分析类资料，市场规模、竞争格局与产业趋势数据具有时效性，需结合原始来源与发布日期复核。",
            "待审核", title,
        )

    education_training_wins_over_meeting_noise = (
        education_training_title_hits >= 1
        or education_training_strong_content_hits >= 2
        or education_training_content_hits >= 3
        or training_enrollment_hits >= 3
    )

    if has_event_priority_signals and not education_training_wins_over_meeting_noise:
        return _build_profile_dict(
            "方案/案例", "方案案例模板", "方案/案例资料",
            "编制主体", "", document_date, version,
            "会展/论坛类材料，活动安排、参展主体与执行状态需结合原始发布来源复核。",
            "待审核", title,
        )

    if has_policy_priority_signals:
        is_draft = any(keyword in title for keyword in ("草案", "征求意见稿", "公示"))
        evidence = (
            "草案/公示类政策材料，非正式生效版本；正式效力需结合官方发布来源复核。"
            if is_draft
            else "政策/官方材料，正式效力需结合原始发布来源复核。"
        )
        dify_ok = "待审核" if is_draft else "是"
        return _build_profile_dict(
            "政策/官方文件", "政策官方文件模板", "政策/官方依据",
            "发布单位", organization, document_date, version,
            evidence, dify_ok, title,
        )

    if has_mixed_policy_meeting_signals and not education_training_wins_over_meeting_noise:
        return _build_profile_dict(
            "方案/案例", "方案案例模板", "方案/案例资料",
            "编制主体", organization, "", version,
            "会议/PPT/说明会类混合材料，夹带政策截图或引用页；不按单一政策官方文件直入，需结合原件与用途复核。",
            "待审核", title,
        )

    if has_low_altitude_catalog_priority_signals:
        return _build_profile_dict(
            "方案/案例", "方案案例模板", "方案/案例资料",
            "编制主体", organization, document_date, version,
            "低空应用场景/机会/能力清单类资料，场景状态、合作需求、能力真实性与联系方式需结合原件或官方来源复核。",
            "待审核", title,
        )

    if has_solution_catalog_priority_signals:
        return _build_profile_dict(
            "方案/案例", "方案案例模板", "方案/案例资料",
            "编制主体", organization, document_date, version,
            "项目/案例清单类资料，项目名称、实施状态与清单完整性需结合原件复核。",
            "待审核", title,
        )

    if enterprise_list_title_hits >= 1 and enterprise_list_content_hits >= 2:
        return _build_profile_dict(
            "供应商/企业资料", "供应商企业模板", "供应商企业资料",
            "企业名称", "", document_date, version,
            "企业名录/榜单类资料，企业入选范围、排序口径与真实性需结合原件复核。",
            "待审核", title,
        )

    if has_supplier_priority_signals and (not has_solution_priority_signals or has_supplier_filename_signals) and education_training_title_hits == 0:
        return _build_profile_dict(
            "供应商/企业资料", "供应商企业模板", "供应商企业资料",
            "企业名称", organization, document_date, version,
            "企业介绍/厂家资料，企业能力、资质与对外合作情况需结合原件与官网信息复核。",
            "待审核", title,
        )

    if is_procurement_file:
        return _build_profile_dict(
            "招标/采购文件", "招标采购文件模板", "招标/采购资料",
            "采购人", organization, document_date, version,
            "招标/采购文件按原文保守抽取；预算、评分办法与采购需求等关键信息需结合原件复核。",
            "待审核", title,
        )

    contract_title_hits = count_title_and_filename_hits(title, source_base_name, CONTRACT_TITLE_KEYWORDS)
    contract_content_hits = count_keyword_hits(combined_text, CONTRACT_CONTENT_KEYWORDS)
    has_contract_signals = contract_title_hits >= 1 or contract_content_hits >= 3
    if has_contract_signals:
        return _build_profile_dict(
            "合同/商务", "合同商务模板", "合同/商务资料",
            "合同主体", organization, document_date, version,
            "合同/协议类资料，金额、履约状态与双方权利义务需结合原件复核；强时效价格不得写成长期稳定事实。",
            "待审核", title,
        )

    price_quote_title_hits = count_title_and_filename_hits(title, source_base_name, PRICE_QUOTE_TITLE_KEYWORDS)
    price_quote_content_hits = count_keyword_hits(combined_text, PRICE_QUOTE_CONTENT_KEYWORDS)
    has_price_quote_signals = (
        (price_quote_title_hits >= 1 or price_quote_content_hits >= 2)
        and not has_solution_priority_signals
        and not has_solution_catalog_priority_signals
    )
    if has_price_quote_signals:
        return _build_profile_dict(
            "报价/价格清单", "报价清单模板", "报价/价格资料",
            "报价主体", organization, document_date, version,
            "报价/价格清单类资料，价格具有强时效性，不得写成长期稳定事实；有效期、阶梯价格与实际成交价需结合原件复核。",
            "待审核", title,
        )

    # Excel 项目清单优先判定：避免误判为产品设备
    is_excel_project_list = (
        source_suffix in {'.xlsx', '.xls'}
        and has_markdown_table
        and (
            "项目名称" in combined_text
            or "案例名称" in combined_text
            or "项目清单" in " ".join([source_base_name, title])
            or "案例清单" in " ".join([source_base_name, title])
        )
    )
    if is_excel_project_list:
        return _build_profile_dict(
            "方案/案例", "方案案例模板", "方案/案例资料",
            "编制主体", organization, document_date, version,
            "项目/案例清单类资料，项目名称、实施状态与清单完整性需结合原件复核。",
            "待审核", title,
        )

    if (any(keyword in title for keyword in PRODUCT_TITLE_KEYWORDS) or (
        not is_research_like
        and not has_solution_priority_signals
        and "案例" not in title
        and "应用案例" not in combined_text
        and product_entity_hits >= 1
        and (product_param_hits >= 2 or has_markdown_table)
    )) and education_training_title_hits == 0:
        return _build_profile_dict(
            "产品/设备", "产品设备模板", "产品/设备资料",
            "编制主体", organization, document_date, version,
            "产品/设备材料，参数与适配关系需结合原件或检测报告复核。",
            "待审核", title,
        )

    if education_training_title_hits >= 1 or education_training_strong_content_hits >= 2 or (
        education_training_content_hits >= 2
        and any(keyword in title for keyword in ("目录", "方案", "体系", "材料", "教育", "培训"))
    ):
        return _build_profile_dict(
            "教育培训", "教育培训模板", "教育培训资料",
            "编制主体", organization, document_date, version,
            "教育培训资料，培训范围、执行版本与适用对象需结合原件复核。",
            "待审核", title,
        )

    if has_solution_priority_signals:
        return _build_profile_dict(
            "方案/案例", "方案案例模板", "方案/案例资料",
            "编制主体", organization, document_date, version,
            "方案/案例材料，是否已落地、预算是否已执行仍需结合项目证据复核。",
            "待审核", title,
        )

    if any(keyword in title for keyword in CONTACT_TITLE_KEYWORDS):
        return _build_profile_dict(
            "单位/联系人", "单位联系人模板", "联系人资料",
            "编制主体", organization, document_date, version,
            "联系人材料需复核公开边界与脱敏要求。",
            "待审核", title,
        )

    if any(keyword in title for keyword in SOLUTION_TITLE_KEYWORDS + EVENT_TITLE_KEYWORDS) or (
        any(keyword in title for keyword in RESEARCH_TITLE_KEYWORDS + ("报告", "项目")) and solution_content_hits >= 2
    ):
        return _build_profile_dict(
            "方案/案例", "方案案例模板", "方案/案例资料",
            "编制主体", "" if is_event_like_title else organization,
            document_date, version,
            "方案/案例材料，是否已落地、预算是否已执行仍需结合项目证据复核。",
            "待审核", title,
        )

    return _build_profile_dict(
        "待判定资料", "待人工补规则", "待判定资料",
        "编制主体", organization, document_date, version,
        "当前仅完成 OCR 原文提取，资料类型和模板归属仍需补规则确认。",
        "待审核", title,
    )
