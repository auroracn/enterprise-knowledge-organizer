from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from minimum_workflow.standardize_competitor_markdown import build_clear_markdown


SAMPLE_MARKDOWN = """---
company_name: 广州迪飞无人机科技有限公司
entity_key: e71e0d25e7644f3f80ca3db24afa8b25bc777795
focus_competitor: true
sample_type: manual_standard_sample
---

# 广州迪飞无人机科技有限公司

## 核心结论
人工指定重点竞争对手样本。主体已核验为广州迪飞无人机科技有限公司，业务覆盖无人机研发销售、培训考证、实训室建设和系统服务；对外在贵阳存在“贵阳迪飞低空经济/迪飞低空”账号线索，需作为贵州市场重点竞品持续跟踪。

## 主体与别名
- 工商主体：广州迪飞无人机科技有限公司
- 统一社会信用代码：91440101MA59LU9AX1
- 别名/账号线索：迪飞低空、贵阳迪飞低空经济、迪飞无人机学院

## 官网与联系线索
- 官网：http://www.gz-difei.com/1-1.html
- 联系页：http://www.gz-difei.com/4-1.html
- 电话：020-31062784、14749323180
- 邮箱：5585662@qq.com、979796881@qq.com

## 经营范围匹配
- 分类：direct_competitor
- 一致点：低空/无人机、信息系统集成、物联网/数据能力、工程/项目服务
- 冲突点：日用品/通用贸易

## 公开业绩摘要
- QCC 招投标摘要：累计58条记录，作为中标方42条。
- 近年样本方向：无人机培训服务、无人机实训室建设、无人机组件采购。

## 六维判断
- 资质：82分，具备无人机制造、销售、维修、培训及实训室建设相关经营范围，QCC 可见体系认证与经营资质线索。
- 业绩：84分，QCC 招投标摘要显示累计58条记录，其中作为中标方42条，近年中标集中于无人机培训、实训室建设、无人机组件采购。

## 风险提示
- 当前贵州本地落地项目原文仍需补链
- 账号名称与工商主体存在跨地域映射，后续需持续核验

## 来源链接
- http://www.gz-difei.com/1-1.html
- http://www.gz-difei.com/4-1.html
"""


class StandardizeCompetitorMarkdownTest(unittest.TestCase):
    def test_build_clear_markdown_keeps_required_metadata_and_sections(self) -> None:
        source_path = Path("D:/changfeng/长风知识整理系统/Claude输出/Claude输出/广州迪飞无人机科技有限公司-e71e0d25.md")

        markdown = build_clear_markdown(source_path, SAMPLE_MARKDOWN)

        self.assertIn("源文件名: 广州迪飞无人机科技有限公司-e71e0d25.md", markdown)
        self.assertIn("文件名hash后缀: e71e0d25", markdown)
        self.assertIn("## 主体", markdown)
        self.assertIn("## 别名", markdown)
        self.assertIn("## 联系线索", markdown)
        self.assertIn("## 业务匹配", markdown)
        self.assertIn("## 公开业绩", markdown)
        self.assertIn("## 六维判断", markdown)
        self.assertIn("## 风险提示", markdown)
        self.assertIn("## 待补证据", markdown)
        self.assertIn("## 来源链接", markdown)
        self.assertIn("- 迪飞低空", markdown)
        self.assertIn("- 贵阳迪飞低空经济", markdown)
        self.assertIn("- 账号名称与工商主体存在跨地域映射，后续需持续核验", markdown)

    def test_script_style_roundtrip_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "广州迪飞无人机科技有限公司-e71e0d25.md"
            output_path = Path(temp_dir) / "广州迪飞无人机科技有限公司-清晰要点版.md"
            source_path.write_text(SAMPLE_MARKDOWN, encoding="utf-8")

            markdown = build_clear_markdown(source_path, source_path.read_text(encoding="utf-8"))
            output_path.write_text(markdown, encoding="utf-8")

            self.assertTrue(output_path.exists())
            self.assertIn("重点竞对：true", output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
