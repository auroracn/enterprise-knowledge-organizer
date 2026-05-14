#!/usr/bin/env python
"""RAGFlow 集成测试脚本"""

import os
from pathlib import Path

from minimum_workflow.ragflow_import_service import (
    RagflowClient,
    RagflowRuntime,
    batch_upload_to_ragflow,
    upload_markdown_to_ragflow,
)


def test_ragflow_connection():
    """测试 RAGFlow API 连接"""
    runtime = RagflowRuntime(
        api_url="http://localhost:9380",
        api_key=os.environ.get("RAGFLOW_API_KEY", "YOUR_RAGFLOW_API_KEY"),
        default_dataset_ids=[],
        verify_ssl=False,
    )
    client = RagflowClient(runtime)

    try:
        datasets = client.list_datasets()
        print(f"[OK] RAGFlow API 连接成功")
        print(f"     当前知识库数量: {len(datasets)}")
        return client
    except Exception as e:
        print(f"[FAIL] RAGFlow API 连接失败: {e}")
        return None


def test_create_dataset(client: RagflowClient):
    """测试创建知识库"""
    try:
        result = client.create_dataset("集成测试知识库")
        dataset_id = result.get("data", {}).get("id")
        print(f"[OK] 创建知识库成功")
        print(f"     知识库 ID: {dataset_id}")
        return dataset_id
    except Exception as e:
        print(f"[FAIL] 创建知识库失败: {e}")
        return None


def test_upload_document(client: RagflowClient, dataset_id: str):
    """测试上传文档"""
    # 查找测试文件
    test_files = list(Path(".omc/generated/directory_review_markdown").glob("*.md"))[:1]
    if not test_files:
        print("[SKIP] 未找到测试用的 Markdown 文件")
        return None

    test_file = test_files[0]
    try:
        result = upload_markdown_to_ragflow(client, dataset_id, test_file, test_file.name)
        doc_id = result.get("data", [{}])[0].get("id") if isinstance(result.get("data"), list) else None
        print(f"[OK] 文档上传成功")
        print(f"     文件名: {test_file.name}")
        print(f"     文档 ID: {doc_id}")
        return doc_id
    except Exception as e:
        print(f"[FAIL] 文档上传失败: {e}")
        return None


def test_list_documents(client: RagflowClient, dataset_id: str):
    """测试列出文档"""
    try:
        docs = client.list_documents(dataset_id)
        print(f"[OK] 获取文档列表成功")
        print(f"     文档数量: {len(docs)}")
        for doc in docs[:3]:
            print(f"     - {doc.get('name', '未知')} (ID: {doc.get('id', '未知')})")
        return docs
    except Exception as e:
        print(f"[FAIL] 获取文档列表失败: {e}")
        return []


def main():
    print("=" * 60)
    print("RAGFlow 集成测试")
    print("=" * 60)

    # 测试连接
    client = test_ragflow_connection()
    if not client:
        return

    # 创建测试知识库
    dataset_id = test_create_dataset(client)
    if not dataset_id:
        return

    # 上传测试文档
    doc_id = test_upload_document(client, dataset_id)
    if not doc_id:
        return

    # 列出文档
    test_list_documents(client, dataset_id)

    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)
    print(f"\nRAGFlow Web UI: http://localhost:18090")
    print(f"测试知识库 ID: {dataset_id}")
    print(f"\n请访问 Web UI 查看上传的文档。")
    print(f"注意：文档解析需要配置 embedding 模型，请在 Web UI 中设置。")


if __name__ == "__main__":
    main()
