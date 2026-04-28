"""
检测报告模块单元测试。

输入：已在全量验证中生成过的 27 份 MD（`Claude输出\D_检测报告_全量验证\`），
作为"真实样本回放"的测试数据。
"""

from __future__ import annotations

import re
import unittest

from minimum_workflow.detection_report_module import (
    ClassificationResult,
    SubReport,
    _normalize_report_no,
    build_classifier_json,
    build_filename,
    classify_detection_report,
    classify_segment,
    extract_fields,
    extract_report_numbers,
    has_detection_report_filename,
    process,
    process_with_details,
    render_subreport_md,
    split_subreports,
)


class FilenameSignalTest(unittest.TestCase):
    def test_positive_names(self):
        for name in [
            "习水县--检测报告.pdf",
            "xx--检验报告.docx",
            "产品检验检测报告.docx",
        ]:
            with self.subTest(name=name):
                self.assertTrue(has_detection_report_filename(name))

    def test_negative_names(self):
        for name in [
            "公司介绍.docx",
            "xx--参数偏离表.pdf",
            "xx--彩页.docx",
            "xx--说明书.docx",
            "xx--参数确认函.pdf",
        ]:
            with self.subTest(name=name):
                self.assertFalse(has_detection_report_filename(name))


class ClassifierTest(unittest.TestCase):
    def test_dense_feature_md_is_detection_report(self):
        md = """
# 检验报告
No Zb2017M1363
共07页第01页
认证委托人：兴化市金茂消防器材有限公司
生产企业：兴化市金茂消防器材有限公司
样品状态：完好
受理日期：2017年04月10日
抽样者：/
检验依据：GB 8181-2005《消防水枪》
检验结论：所检项目均符合标准的要求。
国家消防装备质量监督检验中心
检验检测专用章
CNAS L0472
"""
        r = classify_detection_report(md)
        self.assertTrue(r.is_detection_report)
        self.assertGreaterEqual(r.score, 7)

    def test_empty_md_rejected(self):
        self.assertFalse(classify_detection_report("").is_detection_report)

    def test_pure_promo_rejected(self):
        md = "# 超轻型卫星便携站\n产品特点：整机轻便\n技术指标：输出功率16W\n"
        self.assertFalse(classify_detection_report(md).is_detection_report)

    def test_parameter_confirmation_letter_rejected(self):
        """用户确认的边界样本：虽然文件名叫检测报告，实际只是参数确认函，应被拒。"""
        md = """
# 产品参数确认函
致：重庆市消防救援总队
我公司：博雅工道（北京）机器人科技有限公司
水下机器人参数：作业水深 350m，线缆长度 350m
"""
        r = classify_detection_report(md)
        self.assertFalse(r.is_detection_report)


class ReportNumberExtractionTest(unittest.TestCase):
    def test_various_formats(self):
        md = """
No Zb2017M1363
Some body.
No.(2024)GJCXF-WT00869
And later:
报告编号：H201811263115-01
No. Gn202501580-05
"""
        got = [no for no, _ in extract_report_numbers(md)]
        self.assertIn("Zb2017M1363", got)
        self.assertIn("(2024)GJCXF-WT00869", got)
        self.assertIn("H201811263115-01", got)
        self.assertIn("Gn202501580-05", got)

    def test_normalization_strips_whitespace_and_trailing_punct(self):
        self.assertEqual(_normalize_report_no("  Zb2017M1363#  "), "Zb2017M1363")
        self.assertEqual(_normalize_report_no("\tPRMS 220 8052 SB."), "PRMS2208052SB")

    def test_dedupe_by_normalized_value(self):
        md = "No Zb2017M1363\nNo:Zb2017M1363\nNo: Zb2017M1363"
        got = extract_report_numbers(md)
        self.assertEqual(len(got), 1)


class SplitSubReportsTest(unittest.TestCase):
    def test_single_number_single_subreport(self):
        md = "No Zb2017M1363\n产品名称：QLD6.0/8III\n检验结论：合格"
        subs = split_subreports(md)
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0].report_no, "Zb2017M1363")

    def test_two_numbers_split_at_first_occurrence(self):
        md = "intro\nNo A1111\nblock1 content\nNo B2222\nblock2 content"
        subs = split_subreports(md)
        self.assertEqual([s.report_no for s in subs], ["A1111", "B2222"])
        # 起点严格对齐 "No A1111"
        self.assertTrue(subs[0].text.startswith("No A1111"))
        self.assertTrue(subs[1].text.startswith("No B2222"))

    def test_no_numbers_returns_empty(self):
        self.assertEqual(split_subreports("just some text"), [])


class FieldExtractionTest(unittest.TestCase):
    def test_金茂_Zb_subreport(self):
        md = """
No Zb2017M1363
产品名称 直流喷雾水枪 型号 QLD6.0/8III 认证委托人 兴化市金茂消防器材有限公司 生产者 兴化市金茂消防器材有限公司 生产日期 2017年03月26日 生产企业 兴化市金茂消防器材有限公司
检验依据：GB 8181-2005《消防水枪》CNCA-C18-03:2014
检验结论 检验结果：所检项目均符合标准的要求。检验结论：合格。
签发日期 2017年03月26日
发（换）证日期：2024年06月21日 有效期至：2029年06月20日
# 国家消防装备质量监督检验中心
"""
        f = extract_fields(md)
        self.assertEqual(f["report_no"], "Zb2017M1363")
        self.assertEqual(f["product_name"], "直流喷雾水枪")
        self.assertEqual(f["model"], "QLD6.0/8III")
        self.assertIn("兴化市金茂", f["manufacturer"])
        self.assertEqual(f["test_result"], "合格")
        self.assertEqual(f["report_date"], "2017-03-26")
        self.assertEqual(f["expire_date"], "2029-06-20")
        self.assertIn("消防装备", f["test_organization"])

    def test_广电_IPX7_subreport(self):
        md = """
报告编号：H201811263115-01
委托单位：海能达通信股份有限公司
样品名称： 一体化微型基站
样品型号： DS-6260
检测依据：IEC60529-2013，H201811263115《服务委托单》
检测结论： 符合要求
广州广电计量检测股份有限公司
签发日期：2018/12/6
"""
        f = extract_fields(md)
        self.assertEqual(f["report_no"], "H201811263115-01")
        self.assertTrue(f["test_result"].startswith("符合"))
        self.assertEqual(f["report_date"], "2018-12-06")


class RenderingTest(unittest.TestCase):
    def test_filename_uses_fields(self):
        fields = {"model": "QLD6.0/8III", "report_no": "Zb2017M1363", "report_date": "2017-03-26"}
        name = build_filename(fields)
        self.assertEqual(name, "设备检验报告_QLD6.0_8III_Zb2017M1363_2017-03-26.md")

    def test_filename_falls_back_when_missing(self):
        name = build_filename({})
        self.assertEqual(name, "设备检验报告_未知型号_未知编号_未知日期.md")

    def test_render_has_yaml_frontmatter(self):
        sub = SubReport(
            report_no="Zb2017M1363",
            start_offset=0,
            end_offset=10,
            text="No Zb2017M1363\n检验结论：合格",
            fields={"report_no": "Zb2017M1363", "test_result": "合格", "model": "QLD"},
        )
        _, md = render_subreport_md(sub, {"source_file": "a.docx"})
        self.assertTrue(md.startswith("---\n"))
        self.assertIn('document_type: "设备检验报告"', md)
        self.assertIn('report_no: "Zb2017M1363"', md)
        self.assertIn("## 原文", md)


class ProcessTopLevelTest(unittest.TestCase):
    def test_non_detection_report_returns_empty_outputs(self):
        md = "# 产品彩页\n品牌：茂鑫\n技术参数：流量17L/s"
        cls, outputs = process(md, {"source_file": "彩页.docx"})
        self.assertFalse(cls.is_detection_report)
        self.assertEqual(outputs, [])

    def test_detection_report_produces_outputs(self):
        md = """
# 检验报告
No Zb2017M1363
共07页第01页
认证委托人：金茂 生产企业：金茂 样品状态：完好 受理日期：2017年04月10日 抽样者：/
检验依据：GB 8181-2005
检验结论：合格
国家消防装备质量监督检验中心
检验检测专用章
CNAS L0472
"""
        cls, outputs = process(md, {"source_file": "a.docx"})
        self.assertTrue(cls.is_detection_report)
        self.assertEqual(len(outputs), 1)
        filename, body = outputs[0]
        self.assertTrue(filename.endswith(".md"))
        self.assertIn("Zb2017M1363", filename)


class WeightedClassifierTest(unittest.TestCase):
    """B 类：加权打分 + 置信度。"""

    def test_dense_md_has_high_confidence(self):
        md = """
# 检验报告
No Zb2017M1363
共07页第01页
认证委托人：金茂 生产企业：金茂 样品状态：完好 受理日期：2017-04-10 抽样者：/
检验依据：GB 8181
检验结论：合格
国家消防装备质量监督检验中心
检验检测专用章
CNAS L0472
"""
        r = classify_detection_report(md)
        self.assertGreater(r.weighted_score, 10.0)
        self.assertGreater(r.confidence, 0.7)
        self.assertLessEqual(r.confidence, 1.0)

    def test_empty_md_confidence_zero(self):
        r = classify_detection_report("")
        self.assertEqual(r.weighted_score, 0.0)
        self.assertEqual(r.confidence, 0.0)

    def test_parameter_letter_low_confidence(self):
        md = """
# 产品参数确认函
致：重庆市消防救援总队
我公司：博雅工道（北京）机器人科技有限公司
水下机器人参数：作业水深 350m，线缆长度 350m
"""
        r = classify_detection_report(md)
        self.assertFalse(r.is_detection_report)
        self.assertLess(r.confidence, 0.3)


class SegmentClassifierTest(unittest.TestCase):
    """B 类：段级分类（阈值更低，容忍子报告里没有全局资质）。"""

    def test_segment_without_CNAS_still_classified(self):
        segment = """
No Zb2017M1363
共07页第01页
检验依据：GB 8181
检验结论：合格
"""
        r = classify_segment(segment)
        self.assertTrue(r.is_detection_report)
        self.assertGreaterEqual(r.score, 2)

    def test_too_sparse_segment_rejected(self):
        r = classify_segment("产品名称：xxx\n价格：100 元")
        self.assertFalse(r.is_detection_report)

    def test_process_with_details_attaches_segment_classifier(self):
        md = """
# 检验报告
No Zb2017M1363
共07页第01页
认证委托人：金茂 生产企业：金茂 样品状态：完好 受理日期：2017-04-10 抽样者：/
检验依据：GB 8181
检验结论：合格
国家消防装备质量监督检验中心
检验检测专用章
CNAS L0472
"""
        cls, outputs, subs = process_with_details(md, {"source_file": "a.docx"})
        self.assertTrue(cls.is_detection_report)
        self.assertEqual(len(subs), 1)
        self.assertIsNotNone(subs[0].classifier)
        self.assertGreater(subs[0].classifier.confidence, 0.0)


class ClassifierJsonTest(unittest.TestCase):
    def test_build_classifier_json_structure(self):
        md = """
# 检验报告
No Zb2017M1363
共07页第01页
委托人：X 受检单位：Y
检验依据：GB 8181
检验结论：合格
国家消防装备质量监督检验中心
检验检测专用章
CNAS L0472
"""
        cls, outputs, subs = process_with_details(md, {"source_file": "a.docx"})
        payload = build_classifier_json(cls, subs, {"source_file": "a.docx"})
        self.assertEqual(payload["source_file"], "a.docx")
        self.assertIn("overall", payload)
        self.assertIn("segments", payload)
        self.assertTrue(payload["overall"]["is_detection_report"])
        self.assertGreaterEqual(len(payload["segments"]), 1)
        self.assertIn("hits", payload["segments"][0])


class RenderClassifierFieldsTest(unittest.TestCase):
    def test_yaml_contains_classifier_fields(self):
        sub = SubReport(
            report_no="Zb2017M1363",
            start_offset=0,
            end_offset=10,
            text="No Zb2017M1363\n检验结论：合格",
            fields={"report_no": "Zb2017M1363"},
            classifier=classify_segment("No Zb2017M1363\n检验结论：合格\n检验依据：GB"),
        )
        _, md = render_subreport_md(sub, {"source_file": "a.docx"})
        self.assertIn("classifier_score:", md)
        self.assertIn("classifier_weighted:", md)
        self.assertIn("classifier_confidence:", md)


if __name__ == "__main__":
    unittest.main()
