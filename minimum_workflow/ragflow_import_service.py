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
from minimum_workflow.runtime_config import get_runtime_setting, load_runtime_settings


UI_BATCHES_DIR = GENERATED_DIR / "ui_batches"
BATCH_STATE_FILE_NAME = "ui_batch_state.json"
MANIFEST_FILE_NAME = "ragflow_import_manifest.json"
REPORT_FILE_NAME = "ragflow_import_report.json"


class RagflowApiError(RuntimeError):
    pass


@dataclass(slots=True)
class RagflowRuntime:
    api_url: str
    api_key: str
    default_dataset_ids: list[str]
    verify_ssl: bool


def _validate_ragflow_api_url(api_url: str) -> str:
    normalized = api_url.strip().rstrip("/")
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("RAGFlow API URL 必须使用 HTTP 或 HTTPS。")
    if not parsed.netloc:
        raise ValueError("RAGFlow API URL 格式不合法。")
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


def resolve_ragflow_runtime(
    *,
    api_url: str = "",
    api_key: str = "",
    default_dataset_ids: str = "",
    verify_ssl: object | None = None,
) -> RagflowRuntime | None:
    settings = load_runtime_settings()
    resolved_api_url = _validate_ragflow_api_url(
        api_url.strip()
        or get_runtime_setting("ragflow_api_url", "ragflow api url", "ragflow_api_url", settings=settings)
        or ""
    )
    resolved_api_key = (
        api_key.strip()
        or get_runtime_setting("ragflow_api_key", "ragflow api key", "ragflow_api_key", settings=settings)
        or ""
    ).strip()
    resolved_dataset_ids = _split_csv_ids(
        default_dataset_ids
        or get_runtime_setting("ragflow_default_dataset_ids", "ragflow default dataset ids", settings=settings)
        or ""
    )
    resolved_verify_ssl = _parse_verify_ssl(
        verify_ssl if verify_ssl is not None else get_runtime_setting("ragflow_verify_ssl", "ragflow verify ssl", settings=settings)
    )
    if not resolved_api_url or not resolved_api_key:
        return None
    return RagflowRuntime(
        api_url=resolved_api_url,
        api_key=resolved_api_key,
        default_dataset_ids=resolved_dataset_ids,
        verify_ssl=resolved_verify_ssl,
    )


class RagflowClient:
    """RAGFlow API 客户端，支持知识库管理和文档上传。"""

    def __init__(self, runtime: RagflowRuntime, session: requests.Session | None = None) -> None:
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
            hint = "请检查 RAGFlow HTTPS 证书，或在受信内网自签名场景关闭 SSL 验证。"
            raise RagflowApiError(f"{method} {path} SSL 验证失败：{exc}。{hint}") from exc
        except requests_exceptions.RequestException as exc:
            raise RagflowApiError(f"{method} {path} 请求失败：{exc}") from exc
        if response.status_code not in expected_statuses:
            message = response.text[:800].strip()
            raise RagflowApiError(f"{method} {path} 失败: HTTP {response.status_code} {message}")
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
            raise RagflowApiError(f"{method} {path} 返回了非 JSON 内容: {exc}") from exc

    def list_datasets(self) -> list[dict[str, Any]]:
        """列出所有知识库。"""
        result = self._request_json("GET", "/api/v1/datasets")
        return result.get("data", []) if isinstance(result, dict) else []

    def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        """获取知识库详情。"""
        return self._request_json("GET", f"/api/v1/datasets/{dataset_id}")

    def create_dataset(self, name: str, **kwargs: Any) -> dict[str, Any]:
        """创建知识库。"""
        payload = {"name": name, **kwargs}
        return self._request_json("POST", "/api/v1/datasets", json=payload, expected_statuses=(200, 201))

    def delete_dataset(self, dataset_id: str) -> dict[str, Any]:
        """删除知识库。"""
        return self._request_json("DELETE", f"/api/v1/datasets/{dataset_id}")

    def upload_document(self, dataset_id: str, file_path: Path, display_name: str | None = None) -> dict[str, Any]:
        """上传文档到指定知识库。"""
        file_name = display_name or file_path.name
        with file_path.open("rb") as file_obj:
            response = self._request_json(
                "POST",
                f"/api/v1/datasets/{dataset_id}/documents",
                expected_statuses=(200, 201),
                files={"file": (file_name, file_obj, "text/markdown")},
                timeout=120,
            )
        return response

    def list_documents(self, dataset_id: str) -> list[dict[str, Any]]:
        """列出知识库中的所有文档。"""
        result = self._request_json("GET", f"/api/v1/datasets/{dataset_id}/documents")
        if not isinstance(result, dict):
            return []
        data = result.get("data", {})
        if isinstance(data, dict):
            return data.get("docs", [])
        return data if isinstance(data, list) else []

    def delete_document(self, dataset_id: str, document_id: str) -> dict[str, Any]:
        """删除文档。"""
        return self._request_json("DELETE", f"/api/v1/datasets/{dataset_id}/documents/{document_id}")

    def parse_document(self, dataset_id: str, document_ids: list[str]) -> dict[str, Any]:
        """触发文档解析（向量化）。"""
        return self._request_json(
            "POST",
            f"/api/v1/datasets/{dataset_id}/chunks",
            json={"document_ids": document_ids},
            expected_statuses=(200, 201),
        )

    def get_document_status(self, dataset_id: str, document_id: str) -> dict[str, Any]:
        """获取文档解析状态。"""
        # RAGFlow 的单文档状态接口返回的是文档内容，需要从文档列表中获取状态
        docs = self.list_documents(dataset_id)
        for doc in docs:
            if doc.get("id") == document_id:
                return doc
        return {}

    def wait_for_parsing(self, dataset_id: str, document_id: str, *, timeout_seconds: int = 120) -> dict[str, Any]:
        """等待文档解析完成。"""
        deadline = time.time() + timeout_seconds
        last_payload: dict[str, Any] = {}
        while time.time() < deadline:
            last_payload = self.get_document_status(dataset_id, document_id)
            status = str(last_payload.get("status") or "").lower()
            if status in {"done", "completed", "finished"}:
                return last_payload
            if status in {"error", "failed"}:
                return last_payload
            time.sleep(2)
        return last_payload


def upload_markdown_to_ragflow(
    client: RagflowClient,
    dataset_id: str,
    markdown_path: Path,
    display_name: str | None = None,
) -> dict[str, Any]:
    """上传 Markdown 文件到 RAGFlow 知识库。"""
    file_name = display_name or markdown_path.name
    result = client.upload_document(dataset_id, markdown_path, file_name)

    # 触发解析
    document_id = None
    if isinstance(result, dict):
        document_id = result.get("document_id") or result.get("id")

    if document_id:
        try:
            client.parse_document(dataset_id, [document_id])
        except Exception:
            pass  # 解析触发失败不影响上传结果

    return result


def batch_upload_to_ragflow(
    client: RagflowClient,
    dataset_id: str,
    markdown_files: list[Path],
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """批量上传 Markdown 文件到 RAGFlow 知识库。"""
    results = []
    total = len(markdown_files)

    for index, file_path in enumerate(markdown_files, 1):
        if progress_callback:
            progress_callback({
                "phase": "uploading",
                "total": total,
                "done": index - 1,
                "message": f"[{index}/{total}] 上传 {file_path.name}",
            })

        try:
            result = upload_markdown_to_ragflow(client, dataset_id, file_path)
            results.append({
                "file": str(file_path),
                "status": "success",
                "result": result,
            })
        except Exception as exc:
            results.append({
                "file": str(file_path),
                "status": "failed",
                "error": str(exc),
            })

    if progress_callback:
        success_count = sum(1 for r in results if r["status"] == "success")
        progress_callback({
            "phase": "complete",
            "total": total,
            "done": total,
            "message": f"上传完成：成功 {success_count}/{total}",
        })

    return results
