"""mineru_large_file 单元测试（C 类鲁棒性改造）。

主要覆盖：
1. 页数预算公式（纯计算）
2. chunk cache 读写
3. 分块级重试（mock run_mineru_batch：首跑部分失败，重试后成功）
4. cache 命中跳过上传

不打 MinerU 网络，不依赖 pypdf/pywin32。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from minimum_workflow import mineru_large_file as mlf


class PageAwarePollBudgetTest(unittest.TestCase):
    def test_zero_pages_returns_base(self):
        self.assertEqual(mlf._page_aware_max_polls(0), mlf.POLL_BASE)

    def test_small_pages_returns_base(self):
        # 1~9 页：不足 10 页 step，仍给 base
        self.assertEqual(mlf._page_aware_max_polls(5), mlf.POLL_BASE)

    def test_100_pages_reasonable(self):
        # 100 页：base 60 + 10*12 = 180 次轮询（约 15 分钟）
        self.assertEqual(mlf._page_aware_max_polls(100), 180)

    def test_180_pages_scales(self):
        # SPLIT_PAGES_PER_CHUNK 默认一片
        self.assertEqual(mlf._page_aware_max_polls(180), 60 + 18 * 12)

    def test_upper_cap(self):
        # 极大页数不超过 900
        self.assertEqual(mlf._page_aware_max_polls(10000), mlf.POLL_UPPER)


class SizeAwareFallbackTest(unittest.TestCase):
    def test_small_file_returns_base(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(b"x" * 1024)
            path = Path(tmp.name)
        try:
            self.assertEqual(mlf._size_aware_max_polls_fallback(path), mlf.POLL_BASE)
        finally:
            path.unlink()

    def test_nonexistent_path_safe(self):
        # OSError 时应走 0 MB → base
        self.assertEqual(
            mlf._size_aware_max_polls_fallback(Path("D:/__never_exists__.pdf")),
            mlf.POLL_BASE,
        )


class ChunkCacheTest(unittest.TestCase):
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            self.assertIsNone(mlf._load_chunk_cache(cache, 0))
            mlf._save_chunk_cache(cache, 0, "# chunk1 content")
            loaded = mlf._load_chunk_cache(cache, 0)
            self.assertEqual(loaded, "# chunk1 content")

    def test_load_none_when_cache_dir_is_none(self):
        self.assertIsNone(mlf._load_chunk_cache(None, 0))

    def test_empty_file_treated_as_miss(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            (cache / "part001.md").write_text("", encoding="utf-8")
            self.assertIsNone(mlf._load_chunk_cache(cache, 0))

    def test_path_numbering(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            self.assertEqual(mlf._chunk_cache_path(cache, 0).name, "part001.md")
            self.assertEqual(mlf._chunk_cache_path(cache, 9).name, "part010.md")
            self.assertEqual(mlf._chunk_cache_path(cache, 99).name, "part100.md")


class ExtractLargeFileRetryAndCacheTest(unittest.TestCase):
    """验证分块重试 + cache 行为。用 mock 替代 MinerU 网络 + pypdf。"""

    def _setup_mocks(self, chunks, batch_results_seq):
        """
        chunks: List[Path] 要模拟的分片文件路径
        batch_results_seq: List[List[dict]] 每次 run_mineru_batch 调用依次返回的 results
        返回：上下文管理器，批次号计数器
        """
        call_idx = {"n": 0}

        def fake_batch(paths, token, **kwargs):
            results = batch_results_seq[call_idx["n"]]
            call_idx["n"] += 1
            # 确保长度匹配
            assert len(results) == len(paths), (
                f"mock 失配：预期 {len(paths)} 结果，实际 {len(results)}"
            )
            return {"batch_id": f"B{call_idx['n']:03d}", "results": results}

        return fake_batch, call_idx

    def _patch_extract(self, fake_batch):
        return mock.patch("minimum_workflow.extractors.run_mineru_batch", side_effect=fake_batch)

    def _patch_split_and_pages(self, chunks_to_return, total_pages):
        """mock split_pdf_by_pages 和 count_pdf_pages 不读真实 PDF。"""
        return mock.patch.multiple(
            "minimum_workflow.mineru_large_file",
            split_pdf_by_pages=mock.MagicMock(return_value=chunks_to_return),
            count_pdf_pages=mock.MagicMock(return_value=total_pages),
        )

    def test_all_success_first_try(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # 伪造 3 个 chunk 文件
            chunks = []
            for i in range(3):
                p = tmp_path / f"part{i+1:03d}.pdf"
                p.write_bytes(b"fake pdf")
                chunks.append(p)

            batch_results = [[
                {"state": "done", "markdown": f"# chunk{i+1} body"}
                for i in range(3)
            ]]
            fake_batch, call_idx = self._setup_mocks(chunks, batch_results)

            with self._patch_split_and_pages(chunks, 400), self._patch_extract(fake_batch):
                result = mlf.extract_large_file_via_split(
                    tmp_path / "fake.pdf", "pdf", token="T",
                )
            self.assertEqual(call_idx["n"], 1)  # 只跑了一次
            self.assertIn("chunk1", result.extracted_text)
            self.assertIn("chunk2", result.extracted_text)
            self.assertIn("chunk3", result.extracted_text)
            self.assertEqual(result.extraction_status, "已提取文本")

    def test_retry_on_failure(self):
        """首跑 3 个分片，第 2 个失败；重试只送第 2 个，成功。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            chunks = []
            for i in range(3):
                p = tmp_path / f"part{i+1:03d}.pdf"
                p.write_bytes(b"fake pdf")
                chunks.append(p)

            first_batch = [
                {"state": "done", "markdown": "# chunk1 body"},
                {"state": "failed", "markdown": ""},
                {"state": "done", "markdown": "# chunk3 body"},
            ]
            retry_batch = [
                {"state": "done", "markdown": "# chunk2 body retried"},
            ]
            fake_batch, call_idx = self._setup_mocks(chunks, [first_batch, retry_batch])

            with self._patch_split_and_pages(chunks, 400), self._patch_extract(fake_batch):
                result = mlf.extract_large_file_via_split(
                    tmp_path / "fake.pdf", "pdf", token="T",
                )
            self.assertEqual(call_idx["n"], 2)  # 首跑 + 重试各一次
            self.assertIn("chunk1 body", result.extracted_text)
            self.assertIn("chunk2 body retried", result.extracted_text)
            self.assertIn("chunk3 body", result.extracted_text)
            # chunk 顺序应保留（chunk2 在 chunk1 之后 chunk3 之前）
            self.assertLess(
                result.extracted_text.index("chunk1"),
                result.extracted_text.index("chunk2"),
            )
            self.assertLess(
                result.extracted_text.index("chunk2"),
                result.extracted_text.index("chunk3"),
            )

    def test_retry_disabled(self):
        """max_retries=0 时失败分片不再重试。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            chunks = []
            for i in range(2):
                p = tmp_path / f"part{i+1:03d}.pdf"
                p.write_bytes(b"fake pdf")
                chunks.append(p)

            first_batch = [
                {"state": "done", "markdown": "# c1"},
                {"state": "failed", "markdown": ""},
            ]
            fake_batch, call_idx = self._setup_mocks(chunks, [first_batch])

            with self._patch_split_and_pages(chunks, 300), self._patch_extract(fake_batch):
                result = mlf.extract_large_file_via_split(
                    tmp_path / "fake.pdf", "pdf", token="T", max_retries=0,
                )
            self.assertEqual(call_idx["n"], 1)
            self.assertIn("c1", result.extracted_text)
            self.assertIn("最终失败", result.note)

    def test_cache_hit_skips_upload(self):
        """cache_dir 传入且 part001.md 已存在 → 跳过该 chunk 的上传。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cache_dir = tmp_path / "cache"
            cache_dir.mkdir()
            # 预置 chunk0 的 cache
            (cache_dir / "part001.md").write_text("# cached chunk1", encoding="utf-8")

            chunks = []
            for i in range(2):
                p = tmp_path / f"part{i+1:03d}.pdf"
                p.write_bytes(b"fake pdf")
                chunks.append(p)

            # 只剩 chunk2 需要送 MinerU
            first_batch = [
                {"state": "done", "markdown": "# chunk2 fresh"},
            ]
            fake_batch, call_idx = self._setup_mocks(chunks, [first_batch])

            with self._patch_split_and_pages(chunks, 300), self._patch_extract(fake_batch):
                result = mlf.extract_large_file_via_split(
                    tmp_path / "fake.pdf", "pdf", token="T", cache_dir=cache_dir,
                )
            self.assertEqual(call_idx["n"], 1)
            self.assertIn("cached chunk1", result.extracted_text)
            self.assertIn("chunk2 fresh", result.extracted_text)
            # chunk2 的 cache 应被写入
            self.assertTrue((cache_dir / "part002.md").exists())

    def test_cache_saves_after_success(self):
        """首跑全部成功后，所有 chunk 的 md 都写入 cache。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cache_dir = tmp_path / "cache"
            chunks = []
            for i in range(2):
                p = tmp_path / f"part{i+1:03d}.pdf"
                p.write_bytes(b"fake pdf")
                chunks.append(p)

            first_batch = [
                {"state": "done", "markdown": "# c1"},
                {"state": "done", "markdown": "# c2"},
            ]
            fake_batch, _ = self._setup_mocks(chunks, [first_batch])

            with self._patch_split_and_pages(chunks, 300), self._patch_extract(fake_batch):
                mlf.extract_large_file_via_split(
                    tmp_path / "fake.pdf", "pdf", token="T", cache_dir=cache_dir,
                )

            self.assertTrue((cache_dir / "part001.md").exists())
            self.assertTrue((cache_dir / "part002.md").exists())
            self.assertEqual(
                (cache_dir / "part001.md").read_text(encoding="utf-8"),
                "# c1",
            )


if __name__ == "__main__":
    unittest.main()
