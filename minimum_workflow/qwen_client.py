from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import requests

from minimum_workflow.contracts import ExtractionResult, SampleRecord


QWEN_MAX_RETRIES = 2
QWEN_BACKOFF_SECONDS = 2.0


def _qwen_post_with_retry(
    label: str,
    endpoint: str,
    headers: dict[str, str],
    request_body: dict[str, Any],
    timeout: int,
) -> requests.Response:
    delay = QWEN_BACKOFF_SECONDS
    last_exc: Exception | None = None
    for attempt in range(1, QWEN_MAX_RETRIES + 2):
        try:
            response = requests.post(endpoint, headers=headers, json=request_body, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_exc = exc
            if attempt > QWEN_MAX_RETRIES:
                raise
            print(
                f"[Qwen] {label} 第 {attempt}/{QWEN_MAX_RETRIES + 1} 次失败：{exc}，{int(delay)}s 后重试",
                flush=True,
            )
            time.sleep(delay)
            delay *= 2
    assert last_exc is not None
    raise last_exc


QWEN_TOP_LEVEL_CATEGORIES = [
    "政策法规与官方通知库",
    "标准规范与清单名录库",
    "场景需求与项目机会库",
    "方案案例与实施资料库",
    "产品设备与参数资料库",
    "检测检验与资质证照库",
    "供应商企业与厂家资料库",
    "商务报价与招采合同库",
    "政府单位与联系人库",
    "内部方法流程与话术库",
]

QWEN_ALLOWED_TEMPLATES = [
    "政策官方文件模板",
    "供应商企业模板",
    "单位联系人模板",
    "方案案例模板",
    "产品设备模板",
    "教育培训模板",
    "招标采购文件模板",
    "行业知识模板",
    "",
]

QWEN_FIELD_KEYS = [
    "文件标题",
    "发文字号",
    "发文单位",
    "成文日期",
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
    "文件日期字段",
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
    "行业领域字段",
    "产业链环节字段",
    "市场规模字段",
    "核心玩家字段",
    "发展趋势字段",
]

QWEN_LIST_FIELD_KEYS = {"核心任务", "核心产品", "核心能力"}
HEAVY_PDF_SUMMARY_STRING_KEYS = {
    "主体名称",
    "方案名称/案例名称",
    "所属场景",
    "客户/使用单位",
    "文件日期",
    "资料摘要",
    "资料形态判断",
}
HEAVY_PDF_SUMMARY_LIST_KEYS = {
    "应用背景",
    "解决的问题",
    "投入的产品/设备/能力",
    "实施方式",
    "预算、进度与组织方式",
    "结果与效果数据",
    "可复用经验",
    "入库与归档判断",
    "备注",
}


def normalize_qwen_list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r"[；;、,，\n]+", str(value))

    items: list[str] = []
    for item in raw_items:
        cleaned = re.sub(r"\s+", " ", str(item)).strip(" ：:")
        if cleaned:
            items.append(cleaned)
    return items


def normalize_qwen_field_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in QWEN_LIST_FIELD_KEYS:
        items = normalize_qwen_list_value(value)
        return items or None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return value


# Qwen 只做分类和字段补强，不替代原始文本抽取层；抽取失败时由上层走规则兜底。
def enrich_payload_with_qwen(
    sample: SampleRecord,
    extraction: ExtractionResult,
    payload: dict[str, Any],
    *,
    api_key: str,
    base_url: str,
    model: str,
) -> dict[str, Any]:
    if not (api_key and base_url and model):
        print("[Qwen] 凭据缺失，跳过字段补强（保持原规则链路结果）", flush=True)
        return {}
    if extraction.extraction_status != "已提取文本" or not extraction.extracted_text.strip():
        return {}

    response_data = request_qwen_classification_and_fields(
        sample,
        extraction,
        payload,
        api_key=api_key,
        base_url=base_url,
        model=model,
    )
    if not response_data:
        return {}

    updates: dict[str, Any] = {}
    for key in ["一级分类", "二级分类", "分类依据"]:
        value = response_data.get(key)
        if value:
            updates[key] = value

    confidence = response_data.get("分类置信度")
    if confidence not in {None, ""}:
        updates["分类置信度"] = confidence

    document_category = response_data.get("文档分类")
    if document_category:
        updates["文档分类"] = document_category

    recommended_template = response_data.get("推荐模板")
    if recommended_template in QWEN_ALLOWED_TEMPLATES and recommended_template:
        updates["推荐模板"] = recommended_template

    # 标准规范/行业标准/国家标准类资料，字段语义与政策官方文件最贴近，
    # 若 Qwen 选了"方案案例模板"或返回空，统一路由到 政策官方文件模板。
    _doc_cat = updates.get("文档分类") or ""
    _is_standard_doc = any(k in _doc_cat for k in ("标准规范", "行业标准", "国家标准", "技术标准"))
    if _is_standard_doc and updates.get("推荐模板") in {"", "方案案例模板", None}:
        updates["推荐模板"] = "政策官方文件模板"

    raw_fields = response_data.get("字段") or {}
    if isinstance(raw_fields, dict):
        for key in QWEN_FIELD_KEYS:
            value = normalize_qwen_field_value(key, raw_fields.get(key))
            if value is None:
                continue
            updates[key] = value

    return updates



def request_qwen_classification_and_fields(
    sample: SampleRecord,
    extraction: ExtractionResult,
    payload: dict[str, Any],
    *,
    api_key: str,
    base_url: str,
    model: str,
) -> dict[str, Any]:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    request_body = {
        "model": model,
        "temperature": 0.1,
        "top_p": 0.2,
        "max_tokens": 1600,
        "response_format": {"type": "json_object"},
        "messages": build_qwen_messages(sample, extraction, payload),
    }
    try:
        response = _qwen_post_with_retry(
            "分类请求",
            endpoint,
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            request_body,
            timeout=120,
        )
        data = response.json()
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        parsed = parse_json_content(content)
        return parsed if isinstance(parsed, dict) else {}
    except requests.RequestException as exc:
        logging.warning("Qwen分类请求失败: %s", exc)
        return {}
    except Exception as exc:
        logging.warning("Qwen分类响应解析异常: %s", exc)
        return {}



def build_qwen_messages(sample: SampleRecord, extraction: ExtractionResult, payload: dict[str, Any]) -> list[dict[str, str]]:
    preview_text = extraction.extracted_text[:6000]
    field_list = "、".join(QWEN_FIELD_KEYS)
    top_level_categories = "、".join(QWEN_TOP_LEVEL_CATEGORIES)
    allowed_templates = "、".join([item for item in QWEN_ALLOWED_TEMPLATES if item])
    return [
        {
            "role": "system",
            "content": (
                "你是长风知识整理系统的结构化分类与字段抽取助手。"
                "你必须只返回一个 JSON 对象，不要输出解释、Markdown、代码块。"
                "请优先依据正文内容进行分类和字段抽取；信息不确定时返回空字符串、空数组或较低置信度，不得编造。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"请对以下资料进行分类和字段补强。\n"
                f"一级分类只能从以下列表中选择：{top_level_categories}。\n"
                f"推荐模板只能从以下列表中选择：{allowed_templates}；若都不适合则返回空字符串。\n"
                f"字段只能从以下字段名中选择输出：{field_list}。\n"
                "返回 JSON 格式必须为：\n"
                "{\n"
                '  "一级分类": "",\n'
                '  "二级分类": "",\n'
                '  "文档分类": "",\n'
                '  "推荐模板": "",\n'
                '  "分类置信度": 0.0,\n'
                '  "分类依据": "",\n'
                '  "字段": {}\n'
                "}\n\n"
                f"当前规则预判文档分类：{payload.get('文档分类', '')}\n"
                f"当前规则预判模板：{payload.get('推荐模板', '')}\n"
                f"样例标题提示：{sample.title_hint}\n"
                f"样例主体提示：{sample.subject_name_hint}\n"
                f"样例标签：{'、'.join(sample.tags)}\n"
                f"正文内容：\n{preview_text}\n"
            ),
        },
    ]



def summarize_solution_document_with_qwen(
    source_name: str,
    extracted_text: str,
    *,
    api_key: str,
    base_url: str,
    model: str,
) -> dict[str, Any]:
    if not (api_key and base_url and model):
        print("[Qwen] 凭据缺失，跳过摘要生成", flush=True)
        return {}
    if not extracted_text.strip():
        return {}

    endpoint = base_url.rstrip("/") + "/chat/completions"
    request_body = {
        "model": model,
        "temperature": 0.1,
        "top_p": 0.2,
        "max_tokens": 2200,
        "response_format": {"type": "json_object"},
        "messages": build_solution_summary_messages(source_name, extracted_text),
    }
    try:
        response = _qwen_post_with_retry(
            "摘要请求",
            endpoint,
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            request_body,
            timeout=180,
        )
        data = response.json()
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        parsed = parse_json_content(content)
        return normalize_solution_summary_payload(parsed if isinstance(parsed, dict) else {})
    except requests.RequestException as exc:
        logging.warning("Qwen摘要请求失败: %s", exc)
        return {}
    except Exception as exc:
        logging.warning("Qwen摘要响应解析异常: %s", exc)
        return {}


# 重版式 PDF 的摘要提取必须显式忽略封面、水印、图表坐标和页面碎片，只保留可确认的方案主线信息。
def build_solution_summary_messages(source_name: str, extracted_text: str) -> list[dict[str, str]]:
    preview_text = extracted_text[:12000]
    return [
        {
            "role": "system",
            "content": (
                "你是长风知识整理系统的重版式 PDF 摘要助手。"
                "你必须只返回一个 JSON 对象，不要输出解释、Markdown、代码块。"
                "输入文本可能包含封面、水印、图表坐标、模板噪声、折行碎片和重复页脚。"
                "请只保留能够从文本中确认的事实；不确定时返回空字符串或空数组，不得编造。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"请把以下方案/案例类 PDF 的提取文本整理成适合 Dify 入库的摘要结构。\n"
                "重点保留：方案主线、应用背景、解决的问题、投入设备与能力、实施方式、预算结构、结果数据、可复用经验。\n"
                "必须忽略：模板封面词、包图网/水印、图表坐标、单独数字、重复页眉页脚、明显版式碎片。\n"
                "返回 JSON 字段必须严格为：\n"
                "{\n"
                '  "主体名称": "",\n'
                '  "方案名称/案例名称": "",\n'
                '  "所属场景": "",\n'
                '  "客户/使用单位": "",\n'
                '  "文件日期": "",\n'
                '  "资料摘要": "",\n'
                '  "应用背景": [],\n'
                '  "解决的问题": [],\n'
                '  "资料形态判断": "",\n'
                '  "投入的产品/设备/能力": [],\n'
                '  "实施方式": [],\n'
                '  "预算、进度与组织方式": [],\n'
                '  "结果与效果数据": [],\n'
                '  "可复用经验": [],\n'
                '  "入库与归档判断": [],\n'
                '  "备注": []\n'
                "}\n\n"
                f"源文件名：{source_name}\n"
                f"提取文本：\n{preview_text}\n"
            ),
        },
    ]


# 统一把模型摘要结果收敛成稳定字段，避免上层脚本再逐个判断字符串/列表两种形态。
def normalize_solution_summary_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key in HEAVY_PDF_SUMMARY_STRING_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            normalized[key] = "；".join(normalize_qwen_list_value(value))
        elif isinstance(value, str):
            normalized[key] = value.strip()
        else:
            normalized[key] = ""

    for key in HEAVY_PDF_SUMMARY_LIST_KEYS:
        value = payload.get(key)
        if value is None or value == "":
            normalized[key] = []
        else:
            normalized[key] = normalize_qwen_list_value(value)
    return normalized


def parse_json_content(content: str) -> dict[str, Any]:
    if not content:
        return {}
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", content)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
