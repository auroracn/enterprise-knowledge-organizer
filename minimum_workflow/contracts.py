from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# 统一固定项目内的配置目录与生成目录，后续全量化时直接复用这套路径约定。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
GENERATED_DIR = PROJECT_ROOT / ".omc" / "generated"


@dataclass(slots=True)
class WorkflowContract:
    version: str
    minimum_json_fields: list[str]
    minimum_markdown_sections: list[str]
    decision_rules: dict[str, str]
    processing_routes: dict[str, str]


@dataclass(slots=True)
class SampleRecord:
    sample_id: str
    source_path: str
    document_category: str
    recommended_template: str
    title_hint: str
    subject_name_hint: str
    product_name_hint: str
    unit_name_hint: str
    tags: list[str]
    risks: list[str]
    notes: list[str]
    evidence_level: str
    fallback_decision: str
    split_required: bool
    split_note: str
    relative_path_hint: str = ""


@dataclass(slots=True)
class ExtractionResult:
    extractor_name: str
    extraction_status: str
    extracted_text: str
    preview_text: str
    text_length: int
    page_count: int | None
    source_encoding: str
    note: str
    extra_metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class PipelineResult:
    sample_id: str
    output_dir: Path
    structured_json_path: Path
    structured_markdown_path: Path
    status_path: Path
    extracted_text_path: Path


def load_json_file(file_path: Path) -> dict[str, Any]:
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_contract(config_path: Path | None = None) -> WorkflowContract:
    target = config_path or (CONFIG_DIR / "minimum_workflow_contract.json")
    data = load_json_file(target)
    return WorkflowContract(
        version=data["version"],
        minimum_json_fields=data["minimum_json_fields"],
        minimum_markdown_sections=data["minimum_markdown_sections"],
        decision_rules=data["decision_rules"],
        processing_routes=data["processing_routes"],
    )


def load_samples(config_path: Path | None = None) -> list[SampleRecord]:
    target = config_path or (CONFIG_DIR / "first_batch_samples.json")
    data = load_json_file(target)
    return [SampleRecord(**item) for item in data["samples"]]


def get_sample_by_id(sample_id: str, config_path: Path | None = None) -> SampleRecord:
    for sample in load_samples(config_path):
        if sample.sample_id == sample_id:
            return sample
    # 这里显式报错，避免执行时静默落到错误样例。
    raise KeyError(f"未找到样例: {sample_id}")
