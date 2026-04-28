"""产品参数确认函模块单元测试。"""

from __future__ import annotations

import unittest

from minimum_workflow.parameter_letter_module import (
    ParameterLetter,
    build_letter_filename,
    build_parameter_classifier_json,
    classify_parameter_letter,
    extract_letter_fields,
    process_parameter_letter,
    render_letter_md,
    split_letters,
)


_SAMPLE_SINGLE = """# 产品参数确认函

致：重庆市消防救援总队

我公司：博雅工道（北京）机器人科技有限公司（产品制造商名称）作为水下机器人（产品名称）生产厂家，配合新维度智能系统有限公司（供应商名称），参与贵单位组织的：重庆市消防救援总队自然灾害应急能力提升工程消防装备建设项目（结余资金部分）（包5-包8）（项目名称）、24WA0202（项目号）政府采购活动，现提供以下产品参数确认：

| 序号 | 产品名称 | 品牌型号 | 响应产品参数 | 备注 |
| --- | --- | --- | --- | --- |
| 1 | 水下机器人 | 博雅王道ROBOSEA-ROV-25 | 作业水深 350m | / |

制造商盖章：博雅工道（北京）机器人科技有限公司

日期：2026年04月02日
"""

_SAMPLE_TWO_LETTERS = _SAMPLE_SINGLE + """

# 产品参数确认函

致：重庆市消防救援总队

我公司：浙江丞士机器人有限公司（产品制造商名称）作为水上救生机器人（产品名称）生产厂家，配合新维度智能系统有限公司（供应商名称），参与贵单位组织的：项目 XYZ （项目名称）、24WA0202（项目号）政府采购活动。

| 序号 | 产品名称 | 品牌型号 | 响应产品参数 | 备注 |
| --- | --- | --- | --- | --- |
| 1 | 水上救生机器人 | 丞士SMJT50-165 | IPX8 | / |

制造商盖章：浙江丞士机器人有限公司

日期：2026年04月02日
"""


class ClassifierTest(unittest.TestCase):
    def test_dense_letter_classified(self):
        r = classify_parameter_letter(_SAMPLE_SINGLE)
        self.assertTrue(r.is_detection_report)
        self.assertGreaterEqual(r.score, 5)
        self.assertGreater(r.confidence, 0.5)

    def test_detection_report_not_classified_as_letter(self):
        md = """
# 检验报告
No Zb2017M1363
检验依据：GB 8181
检验结论：合格
国家消防装备质量监督检验中心
CNAS L0472
"""
        r = classify_parameter_letter(md)
        self.assertFalse(r.is_detection_report)
        self.assertLess(r.confidence, 0.3)

    def test_empty_rejected(self):
        self.assertFalse(classify_parameter_letter("").is_detection_report)


class SplitTest(unittest.TestCase):
    def test_single_letter(self):
        letters = split_letters(_SAMPLE_SINGLE)
        self.assertEqual(len(letters), 1)

    def test_two_letters(self):
        letters = split_letters(_SAMPLE_TWO_LETTERS)
        self.assertEqual(len(letters), 2)
        # 相邻段的起点应对齐
        self.assertTrue(letters[0].text.startswith("# 产品参数确认函"))
        self.assertTrue(letters[1].text.startswith("# 产品参数确认函"))

    def test_no_title_returns_empty(self):
        self.assertEqual(split_letters("blah blah"), [])


class FieldExtractionTest(unittest.TestCase):
    def test_all_core_fields(self):
        f = extract_letter_fields(_SAMPLE_SINGLE)
        self.assertIn("博雅工道", f["manufacturer"])
        self.assertIn("新维度智能", f["supplier"])
        self.assertEqual(f["product_name"], "水下机器人")
        self.assertIn("重庆市消防救援总队", f["addressee"])
        self.assertEqual(f["project_no"], "24WA0202")
        self.assertEqual(f["issue_date"], "2026-04-02")
        self.assertIn("ROBOSEA", f["model"])

    def test_second_letter_extraction(self):
        letters = split_letters(_SAMPLE_TWO_LETTERS)
        self.assertEqual(len(letters), 2)
        f2 = extract_letter_fields(letters[1].text)
        self.assertEqual(f2["product_name"], "水上救生机器人")
        self.assertIn("丞士", f2["manufacturer"])
        self.assertIn("SMJT", f2["model"])


class RenderingTest(unittest.TestCase):
    def test_filename_uses_fields(self):
        fields = {"product_name": "水下机器人", "model": "ROBOSEA-ROV-25", "issue_date": "2026-04-02"}
        self.assertEqual(
            build_letter_filename(fields),
            "参数确认函_水下机器人_ROBOSEA-ROV-25_2026-04-02.md",
        )

    def test_filename_fallback(self):
        self.assertEqual(
            build_letter_filename({}),
            "参数确认函_未知产品_未知型号_未知日期.md",
        )

    def test_render_has_yaml_and_original(self):
        letter = ParameterLetter(
            product_name="水下机器人",
            start_offset=0,
            end_offset=len(_SAMPLE_SINGLE),
            text=_SAMPLE_SINGLE,
            fields=extract_letter_fields(_SAMPLE_SINGLE),
        )
        _, md = render_letter_md(letter, {"source_file": "a.pdf"})
        self.assertTrue(md.startswith("---\n"))
        self.assertIn('document_type: "产品参数确认函"', md)
        self.assertIn("## 原文", md)
        self.assertIn("ROBOSEA", md)


class ProcessTopLevelTest(unittest.TestCase):
    def test_non_letter_returns_empty(self):
        cls, outputs, letters = process_parameter_letter("# 检验报告\n合格", {"source_file": "x.md"})
        self.assertFalse(cls.is_detection_report)
        self.assertEqual(outputs, [])

    def test_two_letters_split_and_render(self):
        cls, outputs, letters = process_parameter_letter(
            _SAMPLE_TWO_LETTERS, {"source_file": "a.pdf"}
        )
        self.assertTrue(cls.is_detection_report)
        self.assertEqual(len(outputs), 2)
        for (fname, body), letter in zip(outputs, letters):
            self.assertTrue(fname.endswith(".md"))
            self.assertIn("参数确认函_", fname)
            self.assertIsNotNone(letter.classifier)


class ClassifierJsonTest(unittest.TestCase):
    def test_payload_structure(self):
        cls, outputs, letters = process_parameter_letter(
            _SAMPLE_TWO_LETTERS, {"source_file": "a.pdf"}
        )
        payload = build_parameter_classifier_json(cls, letters, {"source_file": "a.pdf"})
        self.assertEqual(payload["document_type"], "产品参数确认函")
        self.assertIn("overall", payload)
        self.assertIn("letters", payload)
        self.assertEqual(len(payload["letters"]), 2)
        self.assertIn("hits", payload["letters"][0])


if __name__ == "__main__":
    unittest.main()
