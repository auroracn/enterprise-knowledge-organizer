from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests
from requests import exceptions as requests_exceptions

from minimum_workflow.contracts import GENERATED_DIR
from minimum_workflow.review_overlay import (
    STRUCTURED_JSON_FILE_NAME,
    build_effective_payload,
    infer_auto_category,
    load_review_overlay,
    merge_review_outputs,
    render_import_markdown,
    review_is_ready,
    save_review_overlay,
    update_import_overlay,
)
from minimum_workflow.runtime_config import get_runtime_setting, load_runtime_settings


UI_BATCHES_DIR = GENERATED_DIR / "ui_batches"
BATCH_STATE_FILE_NAME = "ui_batch_state.json"
MANIFEST_FILE_NAME = "dify_import_manifest.json"
REPORT_FILE_NAME = "dify_import_report.json"

DEFAULT_METADATA_FIELDS = (
    "知识库分类",
    "一级分类",
    "二级分类",
    "文档分类",
    "推荐模板",
    "内容主题标签",
    "原始路径",
    "分流结果",
    "人工审核状态",
    "生成时间",
    "版本时间戳",
    "来源URL",
)


class DifyApiError(RuntimeError):
    pass


@dataclass(slots=True)
class DifyRuntime:
    api_url: str
    api_key: str
    default_dataset_ids: list[str]
    verify_ssl: bool


def _validate_dify_api_url(api_url: str) -> str:
    normalized = api_url.strip().rstrip("/")
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Dify API URL 必须使用 HTTP 或 HTTPS。")
    if not parsed.netloc:
        raise ValueError("Dify API URL 格式不合法。")
    return normalized


def _split_csv_ids(raw_value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, (list, tuple)):
        raw_items = [str(item).strip() for item in raw_value]
    else:
        raw_items = [item.strip() for item in str(raw_value).split(",")]
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        placeholder_match = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", item)
        if placeholder_match:
            env_value = os.getenv(placeholder_match.group(1), "")
            for expanded_item in _split_csv_ids(env_value):
                if expanded_item in seen:
                    continue
                seen.add(expanded_item)
                result.append(expanded_item)
            continue
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _parse_verify_ssl(raw_value: object) -> bool:
    if isinstance(raw_value, bool):
        return raw_value
    text = "" if raw_value is None else str(raw_value).strip().lower()
    if not text:
        return False
    if text in {"0", "false", "no", "off"}:
        return False
    if text in {"1", "true", "yes", "on"}:
        return True
    return True


def resolve_dify_runtime(
    *,
    api_url: str = "",
    api_key: str = "",
    default_dataset_ids: str = "",
    verify_ssl: object | None = None,
) -> DifyRuntime | None:
    settings = load_runtime_settings()
    resolved_api_url = _validate_dify_api_url(
        api_url.strip()
        or get_runtime_setting("dify_api_url", "dify api url", "dify_api_url", settings=settings)
        or ""
    )
    resolved_api_key = (
        api_key.strip()
        or get_runtime_setting("dify_api_key", "dify api key", "dify_api_key", settings=settings)
        or ""
    ).strip()
    resolved_dataset_ids = _split_csv_ids(
        default_dataset_ids
        or get_runtime_setting("dify_default_dataset_ids", "dify default dataset ids", settings=settings)
        or ""
    )
    resolved_verify_ssl = _parse_verify_ssl(
        verify_ssl if verify_ssl is not None else get_runtime_setting("dify_verify_ssl", "dify verify ssl", settings=settings)
    )
    if not resolved_api_url or not resolved_api_key:
        return None
    return DifyRuntime(
        api_url=resolved_api_url,
        api_key=resolved_api_key,
        default_dataset_ids=resolved_dataset_ids,
        verify_ssl=resolved_verify_ssl,
    )


def ensure_ui_batches_dir(profile: str | None = None) -> Path:
    target = UI_BATCHES_DIR / profile if profile else UI_BATCHES_DIR
    target.mkdir(parents=True, exist_ok=True)
    return target


def batch_state_path(batch_dir: Path | str) -> Path:
    return Path(batch_dir) / BATCH_STATE_FILE_NAME


def manifest_path(batch_dir: Path | str) -> Path:
    return Path(batch_dir) / MANIFEST_FILE_NAME


def report_path(batch_dir: Path | str) -> Path:
    return Path(batch_dir) / REPORT_FILE_NAME


def write_batch_state(batch_dir: Path | str, payload: dict[str, Any]) -> Path:
    target = batch_state_path(batch_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def load_batch_state(batch_dir: Path | str) -> dict[str, Any]:
    target = batch_state_path(batch_dir)
    if not target.exists():
        recovered = _recover_batch_state(Path(batch_dir))
        if recovered is not None:
            return recovered
        raise FileNotFoundError(f"未找到批次状态文件: {target}")
    return json.loads(target.read_text(encoding="utf-8"))


def _recover_batch_state(batch_dir: Path) -> dict[str, Any] | None:
    structured_output_dir = batch_dir / "structured_outputs"
    review_output_dir = batch_dir / "review_markdown"
    try:
        has_recoverable_content = structured_output_dir.is_dir() or review_output_dir.is_dir()
    except OSError:
        return None
    if not has_recoverable_content:
        return None
    try:
        created_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(batch_dir.stat().st_ctime))
    except OSError:
        created_at = ""
    return {
        "batch_id": batch_dir.name,
        "display_name": f"{batch_dir.name} | recovered",
        "created_at": created_at,
        "source_mode": "unknown",
        "status": "recovered",
        "input_dir": str(batch_dir / "input"),
        "review_output_dir": str(review_output_dir),
        "structured_output_dir": str(structured_output_dir),
        "scan_report_path": str(structured_output_dir / "scan_report.json"),
        "batch_dir": str(batch_dir),
    }


def list_batch_states(profile: str | None = None) -> list[dict[str, Any]]:
    base = ensure_ui_batches_dir(profile)
    states: list[dict[str, Any]] = []
    seen_dirs: set[Path] = set()
    for state_file in base.glob(f"*/{BATCH_STATE_FILE_NAME}"):
        try:
            payload = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        payload["batch_dir"] = str(state_file.parent)
        seen_dirs.add(state_file.parent.resolve())
        states.append(payload)
    try:
        batch_dirs = [path for path in base.iterdir() if path.is_dir()]
    except OSError:
        batch_dirs = []
    for batch_dir in batch_dirs:
        try:
            resolved_batch_dir = batch_dir.resolve()
        except OSError:
            continue
        if resolved_batch_dir in seen_dirs:
            continue
        recovered = _recover_batch_state(batch_dir)
        if recovered is not None:
            states.append(recovered)
    return sorted(states, key=lambda item: str(item.get("created_at", "")), reverse=True)


def _load_json_file(file_path: Path) -> dict[str, Any]:
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _serialize_markdown_tags(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _build_document_metadata(payload: dict[str, Any]) -> dict[str, str]:
    source_url = ""
    original_markdown_metadata = payload.get("原始Markdown元数据") or {}
    if isinstance(original_markdown_metadata, dict):
        source_url = str(
            original_markdown_metadata.get("原文URL")
            or original_markdown_metadata.get("原文url")
            or original_markdown_metadata.get("source_url")
            or ""
        ).strip()
    generated_at = str(payload.get("生成时间") or "").strip()
    version_timestamp = generated_at.replace(":", "").replace("T", "_")
    return {
        "知识库分类": str(payload.get("知识库分类") or infer_auto_category(payload)),
        "一级分类": str(payload.get("一级分类") or ""),
        "二级分类": str(payload.get("二级分类") or ""),
        "文档分类": str(payload.get("文档分类") or ""),
        "推荐模板": str(payload.get("推荐模板") or ""),
        "内容主题标签": _serialize_markdown_tags(payload.get("内容主题标签")),
        "原始路径": str(payload.get("原始路径") or ""),
        "分流结果": str(payload.get("分流结果") or ""),
        "人工审核状态": str(payload.get("人工审核状态") or ""),
        "生成时间": generated_at,
        "版本时间戳": version_timestamp,
        "来源URL": source_url,
    }


def _is_tag_schema_error(error: Exception) -> bool:
    text = str(error)
    return "DataSetTag" in text and "binding_count" in text


class DifyClient:
    def __init__(self, runtime: DifyRuntime, session: requests.Session | None = None) -> None:
        self.runtime = runtime
        self.session = session or requests.Session()

    def _request(
        self,
        method: str,
        path: str,
        *,
        expected_statuses: tuple[int, ...] = (200,),
        **kwargs: Any,
    ) -> requests.Response:
        headers = dict(kwargs.pop("headers", {}))
        headers.setdefault("Authorization", f"Bearer {self.runtime.api_key}")
        url = f"{self.runtime.api_url}{path}"
        try:
            response = self.session.request(
                method,
                url,
                headers=headers,
                timeout=kwargs.pop("timeout", 30),
                verify=self.runtime.verify_ssl,
                **kwargs,
            )
        except requests_exceptions.SSLError as exc:
            hint = "请检查 Dify HTTPS 证书，或在受信内网自签名场景关闭“校验 Dify HTTPS 证书”。"
            raise DifyApiError(f"{method} {path} SSL 验证失败：{exc}。{hint}") from exc
        except requests_exceptions.RequestException as exc:
            raise DifyApiError(f"{method} {path} 请求失败：{exc}") from exc
        if response.status_code not in expected_statuses:
            message = response.text[:800].strip()
            raise DifyApiError(f"{method} {path} 失败: HTTP {response.status_code} {message}")
        return response

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        expected_statuses: tuple[int, ...] = (200,),
        **kwargs: Any,
    ) -> Any:
        response = self._request(method, path, expected_statuses=expected_statuses, **kwargs)
        if not response.text:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise DifyApiError(f"{method} {path} 返回了非 JSON 内容: {exc}") from exc

    def list_datasets(self) -> list[dict[str, Any]]:
        page = 1
        page_size = 100
        datasets: list[dict[str, Any]] = []
        while True:
            payload = self._request_json(
                "GET",
                f"/datasets?page={page}&limit={page_size}",
            )
            page_items = payload.get("data") or []
            if not isinstance(page_items, list):
                break
            datasets.extend(page_items)
            if len(page_items) < page_size:
                break
            page += 1
        return datasets

    def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/datasets/{dataset_id}")

    def get_dataset_map(self, scoped_dataset_ids: list[str] | None = None) -> dict[str, dict[str, Any]]:
        if scoped_dataset_ids:
            dataset_ids = scoped_dataset_ids
        else:
            dataset_ids = [str(item.get("id")) for item in self.list_datasets() if str(item.get("id") or "").strip()]
        result: dict[str, dict[str, Any]] = {}
        for dataset_id in dataset_ids:
            result[dataset_id] = self.get_dataset(dataset_id)
        return result

    def create_tag(self, tag_name: str) -> dict[str, Any]:
        return self._request_json(
            "POST",
            "/datasets/tags",
            expected_statuses=(200, 201),
            json={"name": tag_name, "type": "knowledge"},
        )

    def bind_tag_to_dataset(self, dataset_id: str, tag_id: str) -> None:
        try:
            self._request_json(
                "POST",
                "/datasets/tags/binding",
                expected_statuses=(200, 201),
                json={"tag_ids": [tag_id], "target_id": dataset_id},
            )
        except DifyApiError:
            refreshed = self.get_dataset(dataset_id)
            if any(str(tag.get("id") or "") == tag_id for tag in refreshed.get("tags") or []):
                return
            raise

    def ensure_category_bound(self, dataset_id: str, category_name: str, dataset_map: dict[str, dict[str, Any]]) -> str | None:
        dataset_detail = dataset_map.get(dataset_id) or self.get_dataset(dataset_id)
        for tag in dataset_detail.get("tags") or []:
            if str(tag.get("name") or "").strip() == category_name:
                return None

        existing_tag = None
        for dataset in dataset_map.values():
            for tag in dataset.get("tags") or []:
                if str(tag.get("name") or "").strip() == category_name:
                    existing_tag = tag
                    break
            if existing_tag:
                break

        if existing_tag is None:
            try:
                existing_tag = self.create_tag(category_name)
            except DifyApiError as exc:
                if _is_tag_schema_error(exc):
                    return "Dify tags 接口当前返回模型异常，已跳过知识库标签创建/绑定，仍继续导入文档与元数据。"
                if "already exists" not in str(exc):
                    raise
                dataset_map = self.get_dataset_map(list(dataset_map))
                for dataset in dataset_map.values():
                    for tag in dataset.get("tags") or []:
                        if str(tag.get("name") or "").strip() == category_name:
                            existing_tag = tag
                            break
                    if existing_tag:
                        break
                if existing_tag is None:
                    return "分类标签可能已创建，但当前接口无法返回 tag id，已跳过知识库标签绑定，仍继续导入文档与元数据。"

        tag_id = str(existing_tag.get("id") or "")
        if not tag_id:
            return f"分类标签缺少 id: {category_name}，已跳过知识库标签绑定，仍继续导入文档与元数据。"
        try:
            self.bind_tag_to_dataset(dataset_id, tag_id)
        except DifyApiError as exc:
            if _is_tag_schema_error(exc):
                return "Dify tags 绑定接口当前返回模型异常，已跳过知识库标签绑定，仍继续导入文档与元数据。"
            raise
        dataset_map[dataset_id] = self.get_dataset(dataset_id)
        return None

    def list_metadata_fields(self, dataset_id: str) -> dict[str, dict[str, Any]]:
        payload = self._request_json("GET", f"/datasets/{dataset_id}/metadata")
        result: dict[str, dict[str, Any]] = {}
        for field in payload.get("doc_metadata") or []:
            field_name = str(field.get("name") or "").strip()
            if field_name:
                result[field_name] = field
        return result

    def ensure_metadata_fields(self, dataset_id: str, field_names: list[str]) -> dict[str, dict[str, Any]]:
        existing = self.list_metadata_fields(dataset_id)
        for field_name in field_names:
            if field_name in existing:
                continue
            try:
                self._request_json(
                    "POST",
                    f"/datasets/{dataset_id}/metadata",
                    expected_statuses=(200, 201),
                    json={"name": field_name, "type": "string"},
                )
            except DifyApiError as exc:
                if "already exists" not in str(exc):
                    raise
            existing = self.list_metadata_fields(dataset_id)
        return existing

    def upload_markdown_document(self, dataset_id: str, markdown_path: Path, display_name: str) -> dict[str, Any]:
        with markdown_path.open("rb") as file_obj:
            response = self._request_json(
                "POST",
                f"/datasets/{dataset_id}/document/create-by-file",
                expected_statuses=(200, 201),
                data={
                    "data": json.dumps(
                        {
                            "name": display_name,
                            "indexing_technique": "high_quality",
                            "process_rule": {"mode": "automatic"},
                        },
                        ensure_ascii=False,
                    )
                },
                files={"file": (display_name, file_obj, "text/markdown")},
                timeout=120,
            )
        return response

    def update_document_metadata(self, dataset_id: str, document_id: str, metadata_payload: dict[str, str]) -> None:
        field_map = self.ensure_metadata_fields(dataset_id, list(metadata_payload))
        metadata_list = []
        for field_name, value in metadata_payload.items():
            field_def = field_map.get(field_name)
            if not field_def:
                continue
            metadata_list.append(
                {
                    "id": str(field_def.get("id") or ""),
                    "name": field_name,
                    "value": str(value or ""),
                }
            )
        if not metadata_list:
            return
        self._request_json(
            "POST",
            f"/datasets/{dataset_id}/documents/metadata",
            json={"operation_data": [{"document_id": document_id, "metadata_list": metadata_list}]},
        )

    def get_indexing_status(self, dataset_id: str, batch_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/datasets/{dataset_id}/documents/{batch_id}/indexing-status")

    def wait_for_indexing(self, dataset_id: str, batch_id: str, *, timeout_seconds: int = 90) -> dict[str, Any]:
        deadline = time.time() + timeout_seconds
        last_payload: dict[str, Any] = {}
        while time.time() < deadline:
            last_payload = self.get_indexing_status(dataset_id, batch_id)
            data_value = last_payload.get("data")
            if isinstance(data_value, dict):
                data_status = str(data_value.get("indexing_status") or "")
            elif isinstance(data_value, list) and data_value:
                first_item = data_value[0] if isinstance(data_value[0], dict) else {}
                data_status = str(first_item.get("indexing_status") or "")
            else:
                data_status = ""
            candidates = [
                str(last_payload.get("indexing_status") or ""),
                str(last_payload.get("status") or ""),
                data_status,
                str((last_payload.get("document") or {}).get("indexing_status") or ""),
            ]
            normalized = {value.lower() for value in candidates if value}
            if normalized & {"completed", "completed_indexing", "done", "finished"}:
                return last_payload
            if normalized & {"error", "failed", "stopped"}:
                return last_payload
            time.sleep(2)
        return last_payload


def _build_batch_label(state: dict[str, Any]) -> str:
    label = str(state.get("display_name") or state.get("batch_id") or Path(str(state.get("batch_dir") or "")).name)
    status = str(state.get("status") or "")
    if status:
        return f"{label} [{status}]"
    return label


def build_batch_choices(profile: str | None = None) -> list[tuple[str, str]]:
    choices: list[tuple[str, str]] = []
    for state in list_batch_states(profile):
        batch_dir = str(state.get("batch_dir") or "")
        if not batch_dir:
            continue
        choices.append((_build_batch_label(state), batch_dir))
    return choices


def _collect_sample_ids(structured_output_dir: Path, scan_report_path_value: str) -> list[str]:
    scan_report_path = Path(scan_report_path_value)
    if scan_report_path.exists():
        payload = _load_json_file(scan_report_path)
        sample_ids = [
            str(item.get("sample_id") or "").strip()
            for item in payload.get("items") or []
            if item.get("status") == "success" and str(item.get("sample_id") or "").strip()
        ]
        if sample_ids:
            return sample_ids
    return sorted(path.parent.name for path in structured_output_dir.glob(f"*/{STRUCTURED_JSON_FILE_NAME}"))


def collect_batch_snapshot(
    batch_dir: Path | str,
    *,
    runtime: DifyRuntime | None = None,
) -> dict[str, Any]:
    state = load_batch_state(batch_dir)
    structured_output_dir = Path(str(state.get("structured_output_dir") or ""))
    sample_ids = _collect_sample_ids(structured_output_dir, str(state.get("scan_report_path") or ""))
    dataset_map: dict[str, dict[str, Any]] = {}
    dataset_choices: list[tuple[str, str]] = []
    category_choices: set[str] = set()
    runtime_error = ""

    if runtime is not None:
        try:
            # 目标知识库列表始终拉取账户下全部 Dify 知识库；
            # runtime.default_dataset_ids 仅作为"默认勾选"提示，不再限制候选范围。
            dataset_map = DifyClient(runtime).get_dataset_map(None)
        except DifyApiError as exc:
            dataset_map = {}
            runtime_error = str(exc)
        for dataset in dataset_map.values():
            dataset_id = str(dataset.get("id") or "")
            dataset_name = str(dataset.get("name") or dataset_id)
            dataset_choices.append((dataset_name, dataset_id))
            category_choices.add(dataset_name)
            for tag in dataset.get("tags") or []:
                tag_name = str(tag.get("name") or "").strip()
                if tag_name:
                    category_choices.add(tag_name)

    pending_items: list[dict[str, Any]] = []
    ready_items: list[dict[str, Any]] = []
    history_items: list[dict[str, Any]] = []
    items_by_id: dict[str, dict[str, Any]] = {}

    for sample_id in sample_ids:
        structured_json_path = structured_output_dir / sample_id / STRUCTURED_JSON_FILE_NAME
        if not structured_json_path.exists():
            continue
        effective_payload = build_effective_payload(structured_json_path)
        review_payload = load_review_overlay(structured_json_path)
        title = str(effective_payload.get("标题") or effective_payload.get("文件标题") or sample_id)
        import_status = str(review_payload.get("导入状态") or "")
        target_dataset_ids = _split_csv_ids(review_payload.get("目标知识库ID列表"))
        item = {
            "sample_id": sample_id,
            "title": title,
            "decision": str(effective_payload.get("分流结果") or "待审核"),
            "auto_category": infer_auto_category(effective_payload),
            "effective_category": str(effective_payload.get("知识库分类") or ""),
            "review_status": str(review_payload.get("人工审核状态") or ""),
            "target_dataset_ids": target_dataset_ids,
            "import_status": import_status,
            "import_batch_id": str(review_payload.get("导入批次号") or ""),
            "structured_json_path": str(structured_json_path),
            "structured_import_path": str(structured_json_path.with_name("structured.import.md")),
        }
        items_by_id[sample_id] = item
        if item["effective_category"]:
            category_choices.add(item["effective_category"])

        if import_status:
            history_items.append(item)
            continue
        if item["decision"] == "待审核" and not review_is_ready(structured_json_path):
            pending_items.append(item)
        else:
            ready_items.append(item)

    manifest_payload = {
        "batch_dir": str(batch_dir),
        "batch_id": state.get("batch_id"),
        "created_at": state.get("created_at"),
        "source_mode": state.get("source_mode"),
        "ready_count": len(ready_items),
        "pending_count": len(pending_items),
        "history_count": len(history_items),
        "items": pending_items + ready_items + history_items,
    }
    manifest_path(batch_dir).write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "state": state,
        "dataset_map": dataset_map,
        "dataset_choices": sorted(dataset_choices, key=lambda item: item[0]),
        "category_choices": sorted(category_choices),
        "pending_items": pending_items,
        "ready_items": ready_items,
        "history_items": history_items,
        "items_by_id": items_by_id,
        "runtime_error": runtime_error,
    }


def save_manual_review(
    batch_dir: Path | str,
    *,
    sample_id: str,
    category: str,
    dataset_ids: list[str] | tuple[str, ...] | str,
    runtime: DifyRuntime | None = None,
) -> dict[str, Any]:
    snapshot = collect_batch_snapshot(batch_dir, runtime=runtime)
    item = snapshot["items_by_id"].get(sample_id)
    if item is None:
        raise ValueError(f"未找到待审核样本: {sample_id}")
    save_review_overlay(
        item["structured_json_path"],
        category=category,
        dataset_ids=dataset_ids,
    )
    return collect_batch_snapshot(batch_dir, runtime=runtime)


def merge_reviewed_documents(batch_dir: Path | str, *, runtime: DifyRuntime | None = None) -> dict[str, Any]:
    snapshot = collect_batch_snapshot(batch_dir, runtime=runtime)
    for item in snapshot["items_by_id"].values():
        structured_json_path = item["structured_json_path"]
        if review_is_ready(structured_json_path):
            merge_review_outputs(structured_json_path)
    return collect_batch_snapshot(batch_dir, runtime=runtime)


def _determine_target_datasets(
    item: dict[str, Any],
    *,
    runtime: DifyRuntime | None,
    dataset_map: dict[str, dict[str, Any]],
) -> list[str]:
    selected_ids = _split_csv_ids(item.get("target_dataset_ids"))
    if selected_ids:
        return [dataset_id for dataset_id in selected_ids if dataset_id in dataset_map]

    candidate_ids = runtime.default_dataset_ids if runtime and runtime.default_dataset_ids else list(dataset_map)
    if not candidate_ids and len(dataset_map) == 1:
        return list(dataset_map)

    effective_category = str(item.get("effective_category") or "").strip()
    if effective_category:
        matched = []
        for dataset_id in candidate_ids:
            dataset = dataset_map.get(dataset_id)
            if dataset is None:
                continue
            tag_names = {str(tag.get("name") or "").strip() for tag in dataset.get("tags") or []}
            dataset_name = str(dataset.get("name") or "").strip()
            if effective_category in tag_names or effective_category == dataset_name:
                matched.append(dataset_id)
        if matched:
            return matched

    if runtime and runtime.default_dataset_ids:
        return [dataset_id for dataset_id in runtime.default_dataset_ids if dataset_id in dataset_map]
    if len(dataset_map) == 1:
        return list(dataset_map)
    return []


def _build_import_name(item: dict[str, Any], effective_payload: dict[str, Any]) -> str:
    title = str(effective_payload.get("文件标题") or effective_payload.get("标题") or item["sample_id"]).strip()
    timestamp = str(effective_payload.get("生成时间") or "").strip().replace(":", "").replace("T", "_")
    timestamp = timestamp or time.strftime("%Y-%m-%d_%H%M%S")
    return f"{title}__{timestamp}.md"


def import_ready_documents(
    batch_dir: Path | str,
    *,
    runtime: DifyRuntime,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    def _notify(**payload: Any) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(payload)
        except Exception:
            pass

    client = DifyClient(runtime)
    snapshot = collect_batch_snapshot(batch_dir, runtime=runtime)
    dataset_map = snapshot["dataset_map"] or client.get_dataset_map(runtime.default_dataset_ids or None)
    results: list[dict[str, Any]] = []

    ready_items = snapshot["ready_items"]
    total = len(ready_items)
    _notify(phase="start", total=total, done=0, message=f"准备导入 {total} 个样本")

    for index, item in enumerate(ready_items, 1):
        sample_label = str(item.get("title") or item.get("sample_id") or "未命名样本")
        _notify(phase="sample_start", total=total, done=index - 1, message=f"[{index}/{total}] 处理 {sample_label}")
        structured_json_path = Path(item["structured_json_path"])
        effective_payload = build_effective_payload(structured_json_path)
        target_dataset_ids = _determine_target_datasets(item, runtime=runtime, dataset_map=dataset_map)
        if not target_dataset_ids:
            update_import_overlay(
                structured_json_path,
                import_status="failed",
                dataset_ids=[],
                category=str(effective_payload.get("知识库分类") or ""),
                classification_source=str(effective_payload.get("分类来源") or "自动推断"),
            )
            results.append(
                {
                    "sample_id": item["sample_id"],
                    "title": item["title"],
                    "status": "failed",
                    "reason": "未找到可用目标知识库，请先选择知识库或配置默认知识库。",
                    "dataset_ids": [],
                }
            )
            _notify(phase="sample_failed", total=total, done=index, message=f"[{index}/{total}] {sample_label} 未找到目标知识库")
            continue

        import_path = render_import_markdown(structured_json_path)
        metadata_payload = _build_document_metadata(effective_payload)
        batch_ids: list[str] = []
        per_dataset_results: list[dict[str, Any]] = []
        success_count = 0
        category_name = str(effective_payload.get("知识库分类") or "").strip()

        for dataset_id in target_dataset_ids:
            dataset_name = str((dataset_map.get(dataset_id) or {}).get("name") or dataset_id)
            _notify(
                phase="uploading",
                total=total,
                done=index - 1,
                message=f"[{index}/{total}] 上传 {sample_label} → {dataset_name}",
            )
            try:
                tag_warning = ""
                if category_name:
                    tag_warning = client.ensure_category_bound(dataset_id, category_name, dataset_map) or ""
                upload_payload = client.upload_markdown_document(
                    dataset_id,
                    import_path,
                    _build_import_name(item, effective_payload),
                )
                document = upload_payload.get("document") or {}
                document_id = str(document.get("id") or "")
                batch_id = str(upload_payload.get("batch") or "")
                if batch_id:
                    batch_ids.append(batch_id)
                if document_id:
                    client.update_document_metadata(dataset_id, document_id, metadata_payload)
                _notify(
                    phase="indexing",
                    total=total,
                    done=index - 1,
                    message=f"[{index}/{total}] 等待 {dataset_name} 索引完成",
                )
                indexing_payload = client.wait_for_indexing(dataset_id, batch_id) if batch_id else {}
                per_dataset_results.append(
                    {
                        "dataset_id": dataset_id,
                        "dataset_name": dataset_name,
                        "document_id": document_id,
                        "batch_id": batch_id,
                        "status": "success",
                        "warning": tag_warning,
                        "indexing": indexing_payload,
                    }
                )
                success_count += 1
            except Exception as exc:
                per_dataset_results.append(
                    {
                        "dataset_id": dataset_id,
                        "dataset_name": dataset_name,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                _notify(
                    phase="dataset_failed",
                    total=total,
                    done=index - 1,
                    message=f"[{index}/{total}] {sample_label} → {dataset_name} 失败：{exc}",
                )

        if success_count == len(target_dataset_ids):
            aggregate_status = "success"
        elif success_count > 0:
            aggregate_status = "partial_success"
        else:
            aggregate_status = "failed"

        update_import_overlay(
            structured_json_path,
            import_status=aggregate_status,
            import_batch_id=",".join(batch_ids),
            dataset_ids=target_dataset_ids,
            category=category_name or infer_auto_category(effective_payload),
            classification_source=str(effective_payload.get("分类来源") or "自动推断"),
        )
        results.append(
            {
                "sample_id": item["sample_id"],
                "title": item["title"],
                "status": aggregate_status,
                "dataset_ids": target_dataset_ids,
                "batch_ids": batch_ids,
                "details": per_dataset_results,
            }
        )
        _notify(
            phase="sample_done",
            total=total,
            done=index,
            message=f"[{index}/{total}] {sample_label} 完成（{aggregate_status}）",
        )

    report_payload = {
        "batch_dir": str(batch_dir),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "success_count": sum(1 for item in results if item["status"] == "success"),
        "partial_success_count": sum(1 for item in results if item["status"] == "partial_success"),
        "failed_count": sum(1 for item in results if item["status"] == "failed"),
        "items": results,
    }
    report_path(batch_dir).write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _notify(phase="complete", total=total, done=total, message=f"导入完成：成功 {report_payload['success_count']}、部分成功 {report_payload['partial_success_count']}、失败 {report_payload['failed_count']}")
    return collect_batch_snapshot(batch_dir, runtime=runtime)
