"""F 类单元测试：--resume / failed_to_retry.csv / chunk_cache_dir_for_sample。"""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from minimum_workflow.cli import (
    chunk_cache_dir_for_sample,
    load_previous_failed_sources,
    run_source_dir,
    write_failed_to_retry_csv,
)


class LoadPreviousFailedSourcesTest(unittest.TestCase):
    def test_missing_report_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_previous_failed_sources(Path(tmp)), set())

    def test_malformed_report_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scan_report.json").write_text("not json", encoding="utf-8")
            self.assertEqual(load_previous_failed_sources(root), set())

    def test_filters_only_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scan_report.json").write_text(
                json.dumps({
                    "items": [
                        {"status": "success", "source_path": "D:/a.pdf"},
                        {"status": "failed", "source_path": "D:/b.pdf", "error": "x"},
                        {"status": "failed", "source_path": "D:/c.docx", "error": "y"},
                        {"status": "skipped_photo", "source_path": "D:/d.png"},
                    ]
                }),
                encoding="utf-8",
            )
            self.assertEqual(
                load_previous_failed_sources(root),
                {"D:/b.pdf", "D:/c.docx"},
            )


class WriteFailedToRetryCsvTest(unittest.TestCase):
    def test_writes_csv_with_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            failed = [
                {"sample_id": "scan_x", "source_path": "D:/x.pdf", "error": "timeout"},
                {"sample_id": "scan_y", "source_path": "D:/y.docx", "error": "mineru 500"},
            ]
            csv_path = write_failed_to_retry_csv(root, failed)
            self.assertIsNotNone(csv_path)
            self.assertTrue(csv_path.exists())
            # utf-8-sig BOM 让 Excel 正确识别中文
            content = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("sample_id,source_path,error", content)
            self.assertIn("scan_x,D:/x.pdf,timeout", content)
            self.assertIn("scan_y,D:/y.docx,mineru 500", content)

    def test_empty_list_returns_none_and_cleans_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale = root / "failed_to_retry.csv"
            stale.write_text("old content", encoding="utf-8")
            result = write_failed_to_retry_csv(root, [])
            self.assertIsNone(result)
            self.assertFalse(stale.exists())

    def test_truncates_long_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            long_err = "E" * 1000
            write_failed_to_retry_csv(root, [
                {"sample_id": "x", "source_path": "D:/x", "error": long_err},
            ])
            content = (root / "failed_to_retry.csv").read_text(encoding="utf-8-sig")
            # 被截到 500
            lines = list(csv.reader(content.splitlines()))
            self.assertEqual(len(lines[1][2]), 500)


class ChunkCacheDirForSampleTest(unittest.TestCase):
    def test_basic_path(self):
        root = Path("D:/tmp/internal")
        self.assertEqual(
            chunk_cache_dir_for_sample(root, "scan_样本方案"),
            root / "chunk_cache" / "scan_样本方案",
        )

    def test_sanitizes_unsafe_chars(self):
        root = Path("D:/tmp")
        p = chunk_cache_dir_for_sample(root, "scan/样本<方>案*")
        # 路径里不应再含这些字符
        for bad in "/<>*":
            self.assertNotIn(bad, p.name)

    def test_empty_sample_id_fallback(self):
        root = Path("D:/tmp")
        self.assertEqual(
            chunk_cache_dir_for_sample(root, ""),
            root / "chunk_cache" / "sample",
        )


class RunSourceDirResumeTest(unittest.TestCase):
    """验证 resume 流程：读 scan_report.json → 过滤来源 → 只跑失败项。"""

    def test_resume_without_report_exits_early(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_dir = tmp_path / "source"
            source_dir.mkdir()
            internal = tmp_path / "internal"
            internal.mkdir()

            # 无 scan_report.json
            rc = run_source_dir(
                source_dir,
                output_dir=tmp_path / "out",
                internal_output_dir=internal,
                pdf_extractor="mineru",
                mineru_token=None,
                enable_ocr=False,
                enable_qwen=False,
                qwen_runtime={},
                resume=True,
            )
            self.assertEqual(rc, 0)

    def test_resume_filters_to_previously_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_dir = tmp_path / "source"
            source_dir.mkdir()
            good_path = source_dir / "good.pdf"
            bad_path = source_dir / "bad.pdf"
            good_path.write_bytes(b"fake")
            bad_path.write_bytes(b"fake")

            internal = tmp_path / "internal"
            internal.mkdir()
            (internal / "scan_report.json").write_text(
                json.dumps({
                    "items": [
                        {"status": "success", "source_path": str(good_path), "sample_id": "scan_good"},
                        {"status": "failed", "source_path": str(bad_path), "sample_id": "scan_bad", "error": "x"},
                    ]
                }),
                encoding="utf-8",
            )

            fake_result = mock.Mock()
            fake_result.sample_id = "scan_bad"
            fake_result.output_dir = internal / "scan_bad"
            fake_result.output_dir.mkdir(parents=True, exist_ok=True)
            fake_result.structured_json_path = fake_result.output_dir / "structured.json"
            fake_result.structured_json_path.write_text(
                json.dumps({"抽取状态": "已提取文本"}, ensure_ascii=False),
                encoding="utf-8",
            )
            fake_result.structured_markdown_path = fake_result.output_dir / "structured.md"
            fake_result.structured_markdown_path.write_text("# bad", encoding="utf-8")

            with mock.patch("minimum_workflow.cli.load_contract", return_value=mock.Mock()), \
                 mock.patch("minimum_workflow.cli.run_pipeline", return_value=fake_result) as pipe:
                rc = run_source_dir(
                    source_dir,
                    output_dir=tmp_path / "out",
                    internal_output_dir=internal,
                    pdf_extractor="mineru",
                    mineru_token=None,
                    enable_ocr=False,
                    enable_qwen=False,
                    qwen_runtime={},
                    resume=True,
                )

            self.assertEqual(rc, 0)
            # 只应 pipeline 一次（bad 文件），good 被跳过
            self.assertEqual(pipe.call_count, 1)
            called_sample = pipe.call_args.args[0]
            self.assertEqual(called_sample.sample_id, "scan_bad")
            # chunk_cache_dir 被传入
            self.assertIn("chunk_cache_dir", pipe.call_args.kwargs)
            self.assertIn(
                "chunk_cache/scan_bad",
                str(pipe.call_args.kwargs["chunk_cache_dir"]).replace("\\", "/"),
            )

    def test_normal_run_writes_failed_to_retry_csv(self):
        """非 resume 模式：pipeline 抛错时也应产出 failed_to_retry.csv。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_dir = tmp_path / "source"
            source_dir.mkdir()
            (source_dir / "boom.pdf").write_bytes(b"fake")
            internal = tmp_path / "internal"

            with mock.patch("minimum_workflow.cli.load_contract", return_value=mock.Mock()), \
                 mock.patch(
                    "minimum_workflow.cli.run_pipeline",
                    side_effect=RuntimeError("boom"),
                 ):
                rc = run_source_dir(
                    source_dir,
                    output_dir=tmp_path / "out",
                    internal_output_dir=internal,
                    pdf_extractor="mineru",
                    mineru_token=None,
                    enable_ocr=False,
                    enable_qwen=False,
                    qwen_runtime={},
                )
            self.assertEqual(rc, 1)  # 失败退出码
            csv_path = internal / "failed_to_retry.csv"
            self.assertTrue(csv_path.exists())
            content = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("boom.pdf", content)
            self.assertIn("boom", content)


if __name__ == "__main__":
    unittest.main()
