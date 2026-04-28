from __future__ import annotations

import json
from pathlib import Path

from minimum_workflow.dify_import_service import (
    DifyClient,
    DifyRuntime,
    collect_batch_snapshot,
    resolve_dify_runtime,
    write_batch_state,
)
from minimum_workflow.review_overlay import (
    REVIEW_FILE_NAME,
    build_effective_payload,
    merge_review_outputs,
    save_review_overlay,
    update_import_overlay,
)


def _write_structured_sample(
    sample_dir: Path,
    *,
    sample_id: str,
    decision: str = "待审核",
    title: str = "测试文档",
    primary_category: str = "政策/官方文件",
) -> Path:
    sample_dir.mkdir(parents=True, exist_ok=True)
    structured_json_path = sample_dir / "structured.json"
    payload = {
        "标题": title,
        "文件标题": title,
        "原始文件名": f"{sample_id}.md",
        "原始路径": str(sample_dir / f"{sample_id}.md"),
        "文档分类": primary_category,
        "推荐模板": "政策官方文件模板",
        "分流结果": decision,
        "风险说明": [],
        "备注": [],
        "去重主键": [],
        "是否需要拆分": False,
        "拆分说明": "",
        "内容主题标签": [],
        "证据等级": "L1",
        "生成时间": "2026-04-22T12:00:00",
        "文本预览": "测试预览",
        "核心摘要": "测试摘要",
        "抽取说明": "测试抽取说明",
        "文件类型": "pdf",
        "文件格式": "pdf",
        "处理路径": "document_parse",
        "是否适合直接入库": decision == "直接入",
    }
    structured_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (sample_dir / "structured.md").write_text("# 原始文档\n", encoding="utf-8")
    return structured_json_path


def test_save_review_overlay_only_writes_sidecar(tmp_path: Path) -> None:
    structured_json_path = _write_structured_sample(tmp_path / "sample_a", sample_id="sample_a")
    original_content = structured_json_path.read_text(encoding="utf-8")

    review_path = save_review_overlay(
        structured_json_path,
        category="人工分类",
        dataset_ids=["dataset-1", "dataset-2"],
    )

    assert review_path.name == REVIEW_FILE_NAME
    assert structured_json_path.read_text(encoding="utf-8") == original_content
    review_payload = json.loads(review_path.read_text(encoding="utf-8"))
    assert review_payload["知识库分类"] == "人工分类"
    assert review_payload["目标知识库ID列表"] == ["dataset-1", "dataset-2"]
    assert review_payload["人工审核状态"] == "已审核"


def test_build_effective_payload_prefers_review_overlay(tmp_path: Path) -> None:
    structured_json_path = _write_structured_sample(tmp_path / "sample_b", sample_id="sample_b")
    save_review_overlay(
        structured_json_path,
        category="人工分类",
        dataset_ids=["dataset-9"],
    )

    effective_payload = build_effective_payload(structured_json_path)

    assert effective_payload["知识库分类"] == "人工分类"
    assert effective_payload["分类来源"] == "人工审核"
    assert effective_payload["目标知识库ID列表"] == ["dataset-9"]


def test_merge_review_outputs_writes_separate_files(tmp_path: Path) -> None:
    structured_json_path = _write_structured_sample(tmp_path / "sample_c", sample_id="sample_c")
    save_review_overlay(
        structured_json_path,
        category="人工分类",
        dataset_ids=["dataset-3"],
    )

    merged_json_path, merged_markdown_path = merge_review_outputs(structured_json_path)

    assert merged_json_path.exists()
    assert merged_markdown_path.exists()
    merged_payload = json.loads(merged_json_path.read_text(encoding="utf-8"))
    assert merged_payload["知识库分类"] == "人工分类"
    assert structured_json_path.exists()
    assert (tmp_path / "sample_c" / "structured.md").exists()


def test_collect_batch_snapshot_groups_pending_ready_and_history(tmp_path: Path) -> None:
    batch_dir = tmp_path / "batch_001"
    structured_output_dir = batch_dir / "structured_outputs"
    structured_output_dir.mkdir(parents=True)

    direct_ready = _write_structured_sample(structured_output_dir / "direct_ready", sample_id="direct_ready", decision="直接入")
    pending_plain = _write_structured_sample(structured_output_dir / "pending_plain", sample_id="pending_plain", decision="待审核")
    pending_reviewed = _write_structured_sample(structured_output_dir / "pending_reviewed", sample_id="pending_reviewed", decision="待审核")
    imported_sample = _write_structured_sample(structured_output_dir / "imported_sample", sample_id="imported_sample", decision="直接入")

    save_review_overlay(pending_reviewed, category="人工分类", dataset_ids=["dataset-a"])
    update_import_overlay(imported_sample, import_status="success", import_batch_id="batch-123", dataset_ids=["dataset-b"])

    write_batch_state(
        batch_dir,
        {
            "batch_id": "batch_001",
            "display_name": "batch_001",
            "created_at": "2026-04-22T12:00:00",
            "source_mode": "upload",
            "status": "completed",
            "structured_output_dir": str(structured_output_dir),
            "scan_report_path": str(batch_dir / "missing_report.json"),
        },
    )

    snapshot = collect_batch_snapshot(batch_dir, runtime=None)

    assert {item["sample_id"] for item in snapshot["pending_items"]} == {"pending_plain"}
    assert {item["sample_id"] for item in snapshot["ready_items"]} == {"direct_ready", "pending_reviewed"}
    assert {item["sample_id"] for item in snapshot["history_items"]} == {"imported_sample"}


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {}, ensure_ascii=False)

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("No JSON payload")
        return self._payload


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method: str, url: str, headers: dict | None = None, timeout: int = 30, **kwargs):
        self.calls.append((method, url, kwargs))
        if method == "GET" and url.endswith("/datasets/dataset-1/metadata"):
            return _FakeResponse(
                200,
                {"doc_metadata": [{"id": "field-1", "name": "知识库分类", "type": "string", "count": 0}]},
            )
        if method == "POST" and url.endswith("/datasets/dataset-1/documents/metadata"):
            return _FakeResponse(200, {"result": "success"})
        raise AssertionError(f"Unexpected request: {method} {url}")


def test_dify_client_updates_document_metadata_with_expected_payload() -> None:
    session = _FakeSession()
    runtime = DifyRuntime(api_url="http://unit.test/v1", api_key="secret", default_dataset_ids=[], verify_ssl=True)
    client = DifyClient(runtime, session=session)

    client.update_document_metadata("dataset-1", "document-1", {"知识库分类": "人工分类"})

    assert session.calls[0][0] == "GET"
    assert session.calls[1][0] == "POST"
    request_body = session.calls[1][2]["json"]
    assert request_body["operation_data"][0]["document_id"] == "document-1"
    assert request_body["operation_data"][0]["metadata_list"] == [
        {"id": "field-1", "name": "知识库分类", "value": "人工分类"}
    ]


def test_dify_client_wait_for_indexing_supports_list_data_payload() -> None:
    class _IndexSession:
        def __init__(self) -> None:
            self.calls = 0

        def request(self, method: str, url: str, headers: dict | None = None, timeout: int = 30, **kwargs):
            self.calls += 1
            return _FakeResponse(
                200,
                {
                    "data": [
                        {
                            "id": "doc-1",
                            "indexing_status": "completed",
                        }
                    ]
                },
            )

    runtime = DifyRuntime(api_url="http://unit.test/v1", api_key="secret", default_dataset_ids=[], verify_ssl=True)
    client = DifyClient(runtime, session=_IndexSession())

    payload = client.wait_for_indexing("dataset-1", "batch-1", timeout_seconds=1)

    assert payload["data"][0]["indexing_status"] == "completed"


def test_resolve_dify_runtime_keeps_ssl_verify_for_private_https() -> None:
    runtime = resolve_dify_runtime(
        api_url="https://192.168.110.78:18443/v1",
        api_key="secret",
        default_dataset_ids="",
    )

    assert runtime is not None
    assert runtime.verify_ssl is False


def test_resolve_dify_runtime_supports_disabling_ssl_verify() -> None:
    runtime = resolve_dify_runtime(
        api_url="https://192.168.110.78:18443/v1",
        api_key="secret",
        default_dataset_ids="",
        verify_ssl=False,
    )

    assert runtime is not None
    assert runtime.verify_ssl is False


def test_resolve_dify_runtime_accepts_http_url() -> None:
    runtime = resolve_dify_runtime(
        api_url="http://192.168.110.78:17001/v1",
        api_key="secret",
        default_dataset_ids="",
    )
    assert runtime is not None
    assert runtime.api_url == "http://192.168.110.78:17001/v1"


def test_ensure_category_bound_returns_warning_on_tag_schema_error() -> None:
    class _TagSession:
        def request(self, method: str, url: str, headers: dict | None = None, timeout: int = 30, verify: bool = True, **kwargs):
            if method == "POST" and url.endswith("/datasets/tags"):
                return _FakeResponse(
                    400,
                    text='{"code":"invalid_param","message":"1 validation error for DataSetTag\\nbinding_count\\n  Input should be a valid string","status":400}',
                )
            raise AssertionError(f"Unexpected request: {method} {url}")

    runtime = DifyRuntime(api_url="https://192.168.110.78:18443/v1", api_key="secret", default_dataset_ids=[], verify_ssl=True)
    client = DifyClient(runtime, session=_TagSession())

    warning = client.ensure_category_bound("dataset-1", "测试分类", {"dataset-1": {"id": "dataset-1", "name": "测试库", "tags": []}})

    assert warning is not None
    assert "已跳过知识库标签" in warning
